---
title: "Java 四种锁跑了一遍：synchronized、ReentrantLock、StampedLock、读写锁"
slug: java-locks
date: 2026-11-27 10:48:13
description: "在 JDK 21 上跑了两组锁的实测：8 线程 1600 万次自增，以及 95% 读的 800 万次操作。两个反直觉结论——读写锁比 synchronized 还慢 1.4 倍，而高争用下 AtomicLong 比 ReentrantLock 慢一倍。"
categories:
  - 技术
tags:
  - Java 锁
cover: /img/2026/11/java-locks.jpg
---

> 「用 ReentrantLock 比 synchronized 快」这句话在面试题里流传了十年，但很少有人说清快在哪、快多少。「读多写少用读写锁」也是一条被默认为正确的经验。这篇把这两条都测了：8 线程抢同一把锁做 1600 万次自增，ReentrantLock 111ms、synchronized 291ms，差 2.6 倍；换成 95% 读的负载，读写锁 305ms，反而比直接 synchronized 的 216ms 还慢 1.4 倍，而 StampedLock 乐观读只要 63ms。
>
> 还有一个更反直觉的：高争用下 AtomicLong 222ms，是无锁的写法，却比加锁的 ReentrantLock 慢一倍。环境：JDK 21.0.12.1 (Temurin)，16 逻辑核只开 8 个线程，Windows。不是 JMH，没有预热，绝对数字只能横向比。

## 1. 结论先行

| 场景 | 最快 | 最慢 | 差距 |
| --- | --- | --- | --- |
| 高争用自增，8 线程 × 200 万次 | StampedLock.write 110ms | synchronized 291ms | 2.6× |
| 读多写少 95/5，8 线程 800 万次 | StampedLock 乐观读 63ms | ReentrantReadWriteLock 305ms | 4.8× |

四句话说完：

1. **高争用互斥：** `synchronized` 291ms，`ReentrantLock` 111ms，`StampedLock.write` 110ms。后两者基本重合——它们都是「一个 state 上的 CAS + 一条 FIFO 队列」，属于同一条路径。
2. **读多写少：** 读写锁不是答案。`ReentrantReadWriteLock` 305ms，比读写互斥的 `synchronized` 216ms 还慢 41%。真正省事的是乐观读，63ms。
3. **无锁 ≠ 快：** `AtomicLong` 222ms，输给 `ReentrantLock` 一倍。单变量 CAS 在 8 线程下是 cache line 上的互相打脸。
4. **一句话选型：** 争用下要吞吐用 `ReentrantLock`；读多写少用 `StampedLock` 乐观读；计数用 `LongAdder`；`synchronized` 该用在临界区短、不需要额外能力的地方——它在高争用下是这四种里最慢的。

## 2. 实验怎么设的

两组基准，各自打成一个类跑，代码很短。

高争用的那组是不变量：8 个线程，每个线程 200 万次自增，总共 1600 万次，全部打在同一把锁 / 同一个 `AtomicLong` 上。计时用墙钟，等所有线程 `join` 完再停表。

```java
// 固定次数而不是固定时长：时间驱动的写法会让慢的那组跑更多轮，比不了
static long bench(int threads, int ops, Runnable op) throws Exception {
    Thread[] ts = new Thread[threads];
    long t0 = System.nanoTime();
    for (int i = 0; i < threads; i++) {
        ts[i] = new Thread(() -> { for (int k = 0; k < ops; k++) op.run(); });
        ts[i].start();
    }
    // 等全部线程结束，测的是总墙钟（吞吐），不是单次延迟
    for (Thread t : ts) t.join();
    return (System.nanoTime() - t0) / 1_000_000;
}
```

四个被测对象是同一份临界区，只换锁：

```java
static long counter = 0;                 // 所有线程都写的这个变量
static final Object mon = new Object();
static final ReentrantLock rl = new ReentrantLock();
static final StampedLock sl = new StampedLock();
static final AtomicLong al = new AtomicLong();

Runnable sync   = () -> { synchronized (mon) { counter++; } };
Runnable lock   = () -> { rl.lock(); try { counter++; } finally { rl.unlock(); } };
// StampedLock 的写锁返回版本戳，解锁时必须把戳原样还回去
Runnable stamp  = () -> { long s = sl.writeLock(); try { counter++; } finally { sl.unlockWrite(s); } };
Runnable atomic = () -> al.incrementAndGet();
```

读写那组是另一个类：8 个线程，总共 800 万次操作，每 20 次里有 1 次写（`k % 20 == 0`），也就是 95% 读 / 5% 写。读是读一个 `long`，写是 `value++`。

```java
// 每 20 次操作 1 次写，正好 5%；sink 是 volatile，防止读被 JIT 消掉
static volatile long sink;

for (int i = 0; i < THREADS; i++) {
    ts[i] = new Thread(() -> {
        for (int k = 0; k < TOTAL / THREADS; k++) {
            if (k % 20 == 0) write.run(); else sink = read.getAsLong();
        }
    });
}
```

三个实现的差别只在 `read` / `write` 怎么进临界区：

```java
// synchronized：读和写抢同一把锁，读之间也互斥
run("synchronized（读写互斥）",
    () -> { synchronized (RwBench.class) { return value; } },
    () -> { synchronized (RwBench.class) { value++; } });

// 读写锁：读锁共享，写锁独占
run("ReentrantReadWriteLock",
    () -> { rw.readLock().lock(); try { return value; } finally { rw.readLock().unlock(); } },
    () -> { rw.writeLock().lock(); try { value++; } finally { rw.writeLock().unlock(); } });

// 乐观读：先不加锁读，读完再验证这期间有没有写者
run("StampedLock 乐观读",
    () -> {
        long stamp = sl.tryOptimisticRead();
        long v = value;
        // 版本戳变了说明中间有写者提交过，降级成悲观读重读一次
        if (!sl.validate(stamp)) {
            stamp = sl.readLock();
            try { v = value; } finally { sl.unlockRead(stamp); }
        }
        return v;
    },
    () -> { long s = sl.writeLock(); try { value++; } finally { sl.unlockWrite(s); } });
```

三点前提必须先说清，否则下面的数字会被误读：

- **不是 JMH。** 没有 fork 隔离、没有 `Blackhole`、**没有预热轮次**。第一组（`synchronized`）还含着 JIT 编译的代价，真实差距可能比 2.6 倍小一些。要拿数字做决策，请用 JMH 复现。
- **16 逻辑核上只开 8 个线程**，CPU 不饱和，所以测到的差异来自锁本身，不是线程被抢占。
- 临界区都只有一个 `counter++`。这是一个极端短的临界区，结论也只在这个形状下成立——第 5 节会解释为什么这一点很关键。

## 3. 高争用四组：2.6 倍的差距在哪

8 线程 × 200 万次 = 1600 万次自增，全部命中同一个共享变量：

| 锁 | 耗时 ms | ops/ms |
| --- | --- | --- |
| synchronized | 291 | 54,983 |
| ReentrantLock | 111 | 144,144 |
| StampedLock.write | 110 | 145,455 |
| AtomicLong | 222 | 72,072 |

换算成吞吐：`synchronized` 每秒约 5500 万次，`ReentrantLock` 约 1.44 亿次。

`ReentrantLock` 和 `StampedLock.write` 相差 1ms，这不是巧合。两者的争用路径是同一个形状：一次 CAS 抢一个 state 字段，抢不到就进 FIFO 队列、`park` 睡觉，释放时把锁交给队首。`StampedLock` 的写锁没有比 `ReentrantLock` 更聪明，它的优势全在**读**上（下一节）。

`synchronized` 慢 2.6 倍，是因为它走的不是一条路。

## 4. 机制：monitor 的膨胀路径 vs AQS 的队列

先排除一个常见的误解：**JDK 21 上已经没有偏向锁了**。偏向锁在 JDK 15 由 JEP 374 默认关闭，实现后来被移除。所以「第一次 CAS 之后就永久免费」那条快路径不存在，`synchronized` 的争用成本是实打实要付的。

无争用时，`synchronized` 走轻量级锁：CAS 把对象头 mark word 指向线程栈上的 Lock Record，退出时再 CAS 还原。这条路径很便宜。问题出在**争用**时：

1. 线程 A 持有锁，线程 B 的 CAS 失败，先自适应自旋一小段；
2. 自旋还是拿不到，锁**膨胀**成重量级 monitor（HotSpot 里的 `ObjectMonitor`），对象头改成指向它；
3. 膨胀之后，每一次 `monenter` 都要在这个 monitor 上做事：CAS 抢 owner、维护递归计数、把抢不到自己的线程挂到 `cxq` / `EntryList` 上；
4. 挂上去的线程最终 `park`，从用户态掉进内核态等待；释放锁时由持有者 `unpark` 唤醒。

也就是说，高争用下 `synchronized` 每次进出临界区都在做「原子操作 + 竞争列表维护 + 可能的 park/unpark」，而且这些工作分散在**所有 8 个线程**上——每个线程每次都要试着抢一次，抢不到再排队。

`ReentrantLock` 把这件事拆成了两半：

- **快路径：** `tryAcquire` 一次 CAS，把 AQS 的 `state` 从 0 改成 1。成功就直接进临界区，完全不碰队列。所以无争用时它和 `synchronized` 一样便宜。
- **慢路径：** 失败就把自己包成 `Node` 入队，在 `acquireQueued` 里循环，只有当前驱是 head（下一个该轮到它）时才再试一次，否则立刻 `park`。抢不到的线程**马上睡着**，不空转、不反复 CAS 烧 cache 流量。
- **释放：** `state` 归零后 `unpark` 队首。锁是被**交接**出去的，不是让 8 个线程再抢一轮。

差别就在第 3 条：monitor 的 enter 每次都要在竞争列表上做原子操作，AQS 的争用者已经在队列里躺着了。至于 `synchronized` 为什么自旋救不回来——8 个线程的临界区只有一个 `counter++`，自旋窗口里别人根本来不及释放，自旋纯属浪费。

`ReentrantLock` 的额外能力也是这套结构给的，不是白送的：

- `lockInterruptibly()`：在队列里睡觉的线程能被中断唤醒，`park` 天然支持；
- `tryLock(timeout)`：带超时排队，超时就返回，不会无限期等；
- 公平锁：`tryAcquire` 前检查队列里有没有前驱（`hasQueuedPredecessors()`），保证先来先得。代价是每次都要多一次检查、且放弃了插队，吞吐会明显下降（本文没测，不编数字）；
- 多个 `Condition`：一个锁上挂多个等待队列，比 `wait/notify` 的单队列灵活。

## 5. 读多写少：读写锁输给了 synchronized

同一个变量，95% 读、5% 写，8 线程共 800 万次操作：

| 方案 | 耗时 |
| --- | --- |
| synchronized（读写互斥） | 216 ms |
| ReentrantReadWriteLock | 305 ms |
| StampedLock 乐观读 | 63 ms |

`synchronized` 216ms（约 3.7 万 ops/ms），读写锁 305ms（约 2.6 万 ops/ms），乐观读 63ms（约 12.7 万 ops/ms）。

**乐观读为什么这么快：** `StampedLock` 的全部状态是一个 64 位 `long`——低 7 位读者计数、第 8 位写标志、高位是版本号，每次写锁释放版本号 +1。

`tryOptimisticRead()` 只做一件事：读一下 state，确认当前没有写者，然后**把版本号当戳返回**。它不写任何共享变量，不做 CAS，8 个读者之间零争用，只有一次普通 load。

读完之后 `validate(stamp)` 检查「这期间有没有写者提交过」：版本号没变，说明读到的值有效；变了就降级成 `readLock()` 重读一遍。**写者从不等待乐观读者**，所以读也不挡写——这一点是读写锁做不到的（写锁必须等所有读者退出）。

代价也很实在：乐观读可能白读（`validate` 失败重做）、不可重入、没有 `Condition`、不支持中断。

**读写锁为什么反而更慢：**

- 读锁并不是免费的。AQS 的 state 高 16 位是读计数，`readLock().lock()` 和 `unlock()` 都是对同一个字做原子 RMW。8 个线程抢同一个 cache line——这点和互斥锁没区别，但每次操作还多了分支、掩码、可能的唤醒逻辑。
- 写锁要等**所有**读者退出，`tryAcquire` 得先确认读计数为 0。
- 非公平模式下 `readerShouldBlock()` 会看队首是不是排他节点：只要有一个写者在排队，**之后到达的读者一律阻塞**。5% 的写足以让读者反复被挡进队列，而读者进出队列的成本比直接抢 monitor 高。
- 临界区只有一个 `long` 的读。读侧省下来的那点并行度，抵不过每次 lock/unlock 的固定开销。

净结果：305 vs 216，读写锁多花 41%。这条结论的适用范围要说清——**临界区短到只有几行时，读写锁不划算**。读侧要做真实工作（遍历、计算、拷贝）时，读锁的并行度才摊得平成本。

## 6. 为什么 AtomicLong 反而慢

`AtomicLong` 高争用 222ms，比 `ReentrantLock` 的 111ms 慢一倍。它是「无锁」的，却输给了加锁的写法。

`incrementAndGet()` 是一个 CAS 循环：

```java
// 简化后的形状：读旧值 → 算新值 → CAS，失败就整个重来
long cur;
do {
    cur = value;                 // 读
} while (!compareAndSet(cur, cur + 1));   // 有人抢先改了，重试
```

8 个线程同时对同一个 `long` 做 CAS，每一轮只有 1 个成功，其余 7 个**全部失败、重读、再试**。两层成本叠在一起：

1. **真共享。** `AtomicLong` 的 `value` 独占一个 cache line，8 个核轮流把它拉进自己的 L1，MESI 的独占权在核之间来回转让。这是伪共享的反面——不是假共享，是真的所有人都在抢同一行。
2. **忙等。** CAS 失败的线程不会睡，它继续读、继续算、继续 CAS。失败者的工作全部是浪费的，同时还在加剧 cache line 的争抢。

对比一下锁：争用的线程 `park` 进内核态睡着，不烧 CPU，也不产生 cache 流量。一次加锁只有 1 个线程在干活，其余 7 个在队列里安静排队。**这就是 222ms 和 111ms 的来源**——「无锁」省掉的是锁的开销，付出的是重试的浪费，在 8 线程这种争用水平下，后者更贵。

所以 `AtomicLong` 的正确位置是**低争用**：1~2 个线程时，一次 CAS 就是全部开销，没有队列、没有 park，比锁便宜得多。争用一上来就该换 `LongAdder`：它内部是一个 `Cell` 数组，每个线程 CAS 到自己那个 cell，争用被摊到多个 cache line 上，`sum()` 时才汇总。本文没测它的具体数字，但从机制上看，它就是为这个场景设计的。

代价是 `sum()` 不再是一个 O(1) 的实时值，只有最终一致。需要严格单调序号的地方，`LongAdder` 不能替代 `AtomicLong`。

## 7. 选型表

| 场景 | 选什么 | 为什么 |
| --- | --- | --- |
| 临界区短、方法级同步、不需要公平/超时/中断 | `synchronized` | 代码最短，JIT 能做锁消除和粗化；无争用时几乎免费 |
| 高争用互斥、要吞吐 | `ReentrantLock` | 实测 111ms，比 monitor 快 2.6 倍；CAS 快路径 + 队列 park |
| 需要 tryLock 超时、可中断、公平锁、多 Condition | `ReentrantLock` | 这些能力 monitor 一个都没有 |
| 读远多于写，读侧要快，能接受不可重入 | `StampedLock` 乐观读 | 实测 63ms，读不写共享状态，读也不挡写 |
| 读多写少，但需要重入或 Condition | `ReentrantReadWriteLock` | 能用；临界区短时不如直接用 `synchronized` |
| 高争用计数 / 求和 | `LongAdder` | 摊到多个 cell，避免单点 CAS 重试 |
| 低争用单变量自增 | `AtomicLong` | 一次 CAS，无锁无队列 |
| 只读、初始化后不再变 | `final` / `volatile` | 根本不需要锁 |

两条容易被忽略的边界：

- **`StampedLock` 不是 `ReentrantReadWriteLock` 的升级版，是替代品。** 它拿走了重入、`Condition`、中断，换来乐观读。需要这些能力就退回读写锁。
- **`ReentrantReadWriteLock` 的写锁不能从读锁升级。** 持有读锁再去 `writeLock()` 会自己等自己。

## 8. 常见坑

1. **以为 `StampedLock` 可以重入。** 它不可重入，同一线程在 `writeLock()` 里再调 `writeLock()` 会永久阻塞，不报错、不超时，只是挂住。
2. **乐观读之后忘了 `validate`，或者验证失败只重读了一半字段。** 乐观读拿到的是可能撕裂的快照，验证失败必须把所有字段整体重读。把两个字段拼起来用之前不验证，就是读到一个写了一半的状态。
3. **`stamp` 用错或忘了还。** `writeLock()` / `readLock()` 返回的戳必须用对应的 `unlockWrite(s)` / `unlockRead(s)` 还回去；`tryOptimisticRead()` 的戳**不需要**、也不能 `unlock`。传错戳会抛 `IllegalMonitorStateException`。
4. **在读写锁上做锁升级。** 持有读锁再拿写锁 = 死锁，`ReentrantReadWriteLock` 不支持升级。正确做法是释放读锁、拿写锁、重新校验状态。
5. **把「无锁」当性能选项。** 实测 8 线程下 `AtomicLong` 222ms 输给 `ReentrantLock` 111ms，输一倍。
6. **相信「`synchronized` 已经和 `ReentrantLock` 一样快」。** 单线程成立，8 线程争用实测差 2.6 倍。偏向锁（JEP 374）在 JDK 15 就默认关闭了，那条「第一次 CAS 之后免费」的路径在 JDK 21 上不存在。
7. **把这些数字当基准用。** 没有预热、没有 JMH，第一组还含着 JIT 代价；换顺序、换 JVM 参数、换机器都会变。方向可以参考，绝对值不能。

## 9. 重点总结

**四个结论，都来自同一台机器上的对照：**

1. **高争用下 `synchronized` 最慢**：291ms vs `ReentrantLock` 111ms，差 2.6 倍。原因是 monitor 膨胀后每次 enter 都要在竞争列表上做原子操作并 park，而 AQS 的争用者已经在队列里睡着，释放时直接把锁交出去。
2. **读写锁不是读多写少的答案**：305ms，比读写互斥的 `synchronized` 216ms 还慢 41%。读锁同样要在同一个 state 上做 CAS，写锁还要等读者清空，写者一排队后来的读者就被挡。
3. **乐观读是**：63ms，比读写锁快 4.8 倍。`tryOptimisticRead()` 不写共享状态，读者之间零争用，只在 `validate` 失败时降级。
4. **无锁不等于快**：`AtomicLong` 222ms，输给加锁一倍。8 线程抢同一个 cache line，CAS 失败重试的浪费比 park 的代价更高。

**一句话选型：** 争用下要吞吐用 `ReentrantLock`，读多写少用 `StampedLock` 乐观读，高争用计数用 `LongAdder`，临界区短且不需要额外能力就用 `synchronized`——但要清楚它在争用时是这几种里最慢的，不是「优化过所以一样快」。

## 10. 参考

- [JEP 374: Deprecate and Disable Biased Locking](https://openjdk.org/jeps/374)（JDK 15 默认关闭偏向锁，本文 `synchronized` 实测的前提）
- [`StampedLock` javadoc](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/locks/StampedLock.html)（版本戳、乐观读、不可重入的官方说明）
- [`AbstractQueuedSynchronizer` javadoc](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/locks/AbstractQueuedSynchronizer.html)（AQS 的 state、CLH 队列、`park` 语义）
- [`ReentrantReadWriteLock` javadoc](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/locks/ReentrantReadWriteLock.html)（读写计数共用 state、锁升级限制、`readerShouldBlock`）
- [`LongAdder` javadoc](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/atomic/LongAdder.html)（`sum()` 最终一致的说明）
- [OpenJDK JMH](https://github.com/openjdk/jmh)（要拿数字做决策就用它，别用本文这种裸 `nanoTime` 的写法）
- 实测工程：JDK 21.0.12.1 (Temurin)，16 逻辑核 / 8 线程，Windows，`LockBench.java` 与 `RwBench.java` 两组基准，原始输出见正文
