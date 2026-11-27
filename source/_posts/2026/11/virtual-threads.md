---
title: "Java 21 虚拟线程：它提升的是等待的并发度，不是 CPU 吞吐"
slug: virtual-threads
date: 2026-11-26 11:24:07
description: "在 16 核机器上把虚拟线程和平台线程池跑了六组对照：sleep 型 IO、CPU 密集型、连接池受限、synchronized pinning、ThreadLocal 内存、五万线程存活开销。结论是虚拟线程只对「等待」有效，对有界资源和 CPU 计算毫无帮助，而 synchronized 的 pinning 会让它退化成串行——这一条在 JDK 26 上已经消失。"
categories:
  - 技术
tags:
  - 虚拟线程
cover: /img/2026/11/virtual-threads.jpg
---

> 虚拟线程的官方说法是「用同步写法拿到异步的吞吐」，但「吞吐」这个词掩盖了边界。这篇在 16 核机器上跑了六组对照，把边界一条条测出来：IO 等待型负载能快 20 倍，CPU 密集型完全没变化，有界资源（连接池、信号量）会把虚拟线程重新串行化到和线程池一样慢，而 JDK 21 的 `synchronized` pinning 能让 1000 个任务从 71ms 退化到 4 秒。
>
> 最后补一组 JDK 26 的对照：pinning 已经没有了。环境：JDK 21.0.12.1 (Temurin) 与 JDK 26.0.2.1，16 核，`-Xmx1g`，每组预热 3 轮取 5 次中位数。

## 1. 先给结论

| 负载类型 | 平台线程池 | 虚拟线程 | 结论 |
| --- | --- | --- | --- |
| sleep 型 IO，池 100，2000 任务 | 2178ms | 108ms | **20.1×**，虚拟线程完胜 |
| sleep 型 IO，池 2000，2000 任务 | 317ms | 108ms | 2.9×，池够大时差距缩小 |
| CPU 密集，并发=16 核 | 578ms | 579ms | **1.00×**，完全没变化 |
| 连接池 10，1000 任务 | 10864ms | 10894ms | **1.00×**，一样慢 |
| `synchronized` 内 sleep，1000 任务 | — | 4080ms | pinning，退化到接近串行 |
| `ReentrantLock` 内 sleep，1000 任务 | — | 62ms | 正常，并行 |
| 50000 个线程存活 | — | 89.1MB | 平台线程 20000 个就要 9.6MB 栈外开销 |

一句话：**虚拟线程解决的是「线程被阻塞时占用操作系统线程」这一件事**。凡是瓶颈不在等待上的场景，它不会带来任何提升；凡是有界资源卡住并发度的场景，它会和线程池一样慢。

## 2. 它到底改变了什么

平台线程是操作系统线程的一对一映射。你开 1000 个，JVM 就要向操作系统要 1000 个线程，每个默认占 1MB 左右的栈（`-Xss`），加上内核调度开销。所以「一万个并发连接」在平台线程模型下是做不到的，只能靠回调或者响应式框架把等待拆成事件。

虚拟线程把这一层解耦了：**JVM 自己调度虚拟线程，把它们多路复用到少量载体线程（carrier thread）上**。载体线程数量默认等于 CPU 核数。当一个虚拟线程调用 `Thread.sleep`、阻塞 IO、`park` 时，JVM 把它从载体线程上卸下来（unmount），载体线程立刻去跑别的虚拟线程；等它被唤醒再装回去（mount）。

所以虚拟线程的成本不在「线程」上，而在「挂起和恢复」上——这是一次用户态的栈拷贝，比内核线程切换便宜几个数量级。

这就是为什么它只对**等待**有效：等待的时候，栈被搬走了，载体线程可以复用；计算的时候，虚拟线程就实实在在占着一个载体线程，和平台线程没有区别。

## 3. 实验一：IO 等待型负载

2000 个任务，每个 `sleep(100)`，对比固定大小线程池和「每任务一个虚拟线程」。

```java
// 作用：同样的 sleep 负载，分别丢进固定池和虚拟线程执行器
static void withPlatform(int conc, int tasks, Runnable body) {
    try (ExecutorService ex = Executors.newFixedThreadPool(conc)) {
        List<Future<?>> fs = new ArrayList<>();
        for (int i = 0; i < tasks; i++) fs.add(ex.submit(body));
        for (Future<?> f : fs) f.get();
    }
}

static void withVirtual(int tasks, Runnable body) {
    // 每任务一个虚拟线程，没有池化，也没有队列
    try (ExecutorService ex = Executors.newVirtualThreadPerTaskExecutor()) {
        List<Future<?>> fs = new ArrayList<>();
        for (int i = 0; i < tasks; i++) fs.add(ex.submit(body));
        for (Future<?> f : fs) f.get();
    }
}
```

结果：

```text
[io] conc=100  tasks=2000 platform=2178ms virtual=108ms speedup=20.1x
[io] conc=2000 tasks=2000 platform=317ms  virtual=108ms speedup=2.9x
```

两组数字都值得看：

**池 100 时，平台线程池的耗时是 2178ms**。算一下就知道这是纯排队：2000 个任务 ÷ 100 个线程 = 20 批，每批 100ms，理论值 2000ms。虚拟线程 108ms，基本就是一批的时间——它把 2000 个任务全并行起来了。

**池 2000 时，平台线程池只慢 2.9 倍**。因为池已经开到 2000，等于每任务一个平台线程，没有排队了。剩下的差距来自创建 2000 个操作系统线程的开销（约 200ms）。

这两组数字放在一起说明一件事：**虚拟线程不是「更快」，是「没有队列」**。当你的线程池足够大，两者的差距就只剩线程创建成本。

## 4. 实验二：CPU 密集型

固定计算量，并发数设成核数（16），预热后取中位数。为了防止 JIT 把循环优化掉，结果写进一个 `volatile` 字段：

```java
// 作用：写 volatile 保证循环不被 JIT 消除，否则测的是空转
static volatile double SINK;

Runnable work = () -> {
    double x = 0;
    for (int i = 0; i < iters; i++) x += Math.sqrt(i) * 1.0000001;
    SINK = x;
};
```

结果：

```text
cores=16 tasks=64  iters=30000000 platform=578ms  virtual=579ms  ratio=1.00
cores=16 tasks=400 iters=30000000 platform=3561ms virtual=3527ms ratio=1.01
```

**1.00 和 1.01。** 完全没有区别，符合预期：计算任务不会挂起，虚拟线程就一直占着载体线程，行为等价于平台线程。400 个任务时甚至略快一点，因为虚拟线程的创建比平台线程便宜。

这条结论的实际意义是：**不要把虚拟线程当成「性能优化开关」全局替换掉线程池**。CPU 密集的服务用它没有任何收益，只是多了一层间接。

## 5. 实验三：有界资源会让它重新串行化

这是最容易被忽略的一组。真实系统里 IO 后面往往跟着一个连接池，而连接池的大小是固定的。

模拟：1000 个任务，每个占用 100ms，但同时只允许 N 个持有资源。

```java
// 作用：虚拟线程 + 信号量模拟连接池，对比「线程池大小 = 连接数」的写法
Semaphore sem = new Semaphore(permits);
try (ExecutorService ex = Executors.newVirtualThreadPerTaskExecutor()) {
    for (int i = 0; i < tasks; i++) {
        fs.add(ex.submit(() -> {
            sem.acquire();
            try { body.run(); } finally { sem.release(); }
            return null;
        }));
    }
    for (Future<?> f : fs) f.get();
}
```

结果：

```text
permits=10 tasks=1000 platform=10864ms virtual+sem=10894ms ratio=1.00
permits=50 tasks=1000 platform=2178ms  virtual+sem=2189ms  ratio=1.01
```

**1.00 和 1.01。** 一模一样。

原因很直接：并发度被信号量钉死在 10，虚拟线程再多也只能排队。1000 个任务 ÷ 10 个许可 = 100 批 × 100ms ≈ 10000ms，实测 10864ms，对得上。

所以「虚拟线程 + 连接池」这个组合的真实效果是：

- 虚拟线程负责让你**不用为了等待而开大线程池**；
- 但**吞吐上限仍然由最小的那个池决定**——连接池、文件句柄、下游 QPS 配额，哪个最小就是哪个。

一个反直觉的推论：**虚拟线程下线程池大小不再是「并发度」的旋钮，连接池才是**。以前调 `maxThreads` 就是在调并发度，现在这个旋钮移到了连接池上，而线程数应该彻底不设上限。

## 6. 实验四：`synchronized` 的 pinning

这是 JDK 21 上最需要警惕的坑。虚拟线程在 `synchronized` 块里阻塞时**无法卸载**——它会把载体线程一起钉住（pinning），载体线程数只有 16，于是 1000 个任务退化到 16 路并行。

每任务一个独立锁（排除互相争用，剩下的差异纯粹来自 pinning）：

```java
// 作用：每任务独立锁，对比 synchronized 与 ReentrantLock 在虚拟线程下的行为
fs.add(ex.submit(() -> {
    switch (kind) {
        case "sync" -> { synchronized (mon) { Thread.sleep(sleepMs); } }
        case "lock" -> { rl.lock(); try { Thread.sleep(sleepMs); } finally { rl.unlock(); } }
        default     -> { Thread.sleep(sleepMs); }
    }
    return null;
}));
```

JDK 21 结果：

```text
none tasks=1000 sleep=50ms wall=71ms
sync tasks=1000 sleep=50ms wall=4080ms
lock tasks=1000 sleep=50ms wall=79ms
```

**71ms → 4080ms，57 倍差距。** 1000 × 50ms ÷ 16 个载体线程 ≈ 3125ms，实测 4080ms（有额外调度开销），完全对得上「退化到 16 路并行」这个模型。

任务翻倍到 2000，耗时也翻倍到 10605ms，进一步确认是线性串行化，不是偶发。

用 `-Djdk.tracePinnedThreads=full` 可以直接抓到现场：

```text
VirtualThread[#39]/runnable@ForkJoinPool-1-worker-4 reason:MONITOR
    java.base/java.lang.VirtualThread$VThreadContinuation.onPinned(VirtualThread.java:199)
    java.base/jdk.internal.vm.Continuation.onPinned0(Continuation.java:393)
    java.base/java.lang.VirtualThread.parkNanos(VirtualThread.java:635)
    VtFull.lambda$pin$3(VtFull.java:61) <== monitors:1
```

`reason:MONITOR` 和 `<== monitors:1` 就是证据：这个虚拟线程在持有一个 monitor 的情况下 park 了。

换成 `ReentrantLock` 立刻恢复：79ms，和完全不加锁的 71ms 基本一致。

### 6.1. JDK 26 上这一条已经消失

同一个脚本，换 JDK 26 跑：

```text
openjdk version "26.0.2.1" 2026-08-18 LTS
sync tasks=1000 sleep=50ms wall=63ms
lock tasks=1000 sleep=50ms wall=63ms
none tasks=1000 sleep=50ms wall=64ms
```

**63ms、63ms、64ms，三者完全一致。** pinning 没了。

这是 JEP 491（Synchronize Virtual Threads without Pinning），从 JDK 24 开始生效。它重写了 monitor 的实现，让虚拟线程在 `synchronized` 里阻塞时也能卸载。

所以这条坑的准确表述是：**JDK 21 到 23 上必须避开 `synchronized` 里阻塞，JDK 24 之后不用了**。如果你的项目还锁在 JDK 21（LTS，很多生产环境如此），这条仍然是最重要的迁移注意事项；`-Djdk.tracePinnedThreads` 也仍然是排查工具。

## 7. 实验五：ThreadLocal 的内存账

`ThreadLocal` 在平台线程池下的经典问题是「线程长期存活，ThreadLocal 内容跟着不释放」。虚拟线程是每任务一个、用完就回收，理论上更安全。实测：

```java
// 作用：每个线程塞 1MB 进 ThreadLocal，看任务结束后堆里还剩多少
static final ThreadLocal<byte[]> CACHE = ThreadLocal.withInitial(() -> new byte[1024 * 1024]);
```

```text
=== JDK 21 ===
pool    tasks=5000 heapUsed=203.9MB
virtual tasks=5000 heapUsed=3.7MB
=== JDK 26 ===
pool    tasks=5000 heapUsed=204.5MB
virtual tasks=5000 heapUsed=4.2MB
```

平台线程池 100 个线程，每个 1MB，实测 203.9MB——**因为池还活着，这 100 份内容一直占着**，哪怕 5000 个任务早就跑完了。

虚拟线程 3.7MB，因为每个虚拟线程执行完就被回收，它的 ThreadLocal 内容一起没了。

这条对缓存类用法是好事（不会泄漏），但对**「想复用」的用法是坏事**：虚拟线程之间没有复用，`ThreadLocal` 起不到缓存作用，每次都是新建。想在虚拟线程间共享状态，得用显式的缓存对象，不能靠 `ThreadLocal`。

## 8. 实验六：线程本身的开销

```text
virtual  alive=50000 heapUsed=89.1MB
platform alive=5000  heapUsed=5.3MB
platform alive=20000 heapUsed=9.6MB
```

50000 个存活虚拟线程占 89.1MB 堆，约 1.8KB/个。平台线程 20000 个时 `Thread.activeCount()` 是 20001，堆只多了 9.6MB，但**真正的成本在堆外**：每个线程 1MB 栈是虚拟内存，实际提交量取决于用多少，这也是为什么 20000 个平台线程能起来但很快就会 OOM 或者被 `pthread_create` 拒绝。

在 `-Xmx1g` 下 50000 个虚拟线程毫无压力，这是平台线程做不到的量级。

## 9. 什么时候该用，什么时候别用

**适合：**

- 每个请求大部分时间在等 IO（HTTP 调用、数据库、消息队列）；
- 并发度由下游决定，而不是由自己决定；
- 想用同步写法替代 `CompletableFuture` 或者响应式框架；
- 大量短生命周期的并发任务（每个任务一个虚拟线程，不需要池）。

**不适合：**

- CPU 密集型计算——实测 1.00×，没有任何收益；
- 有固定连接池的 IO——实测 1.00×，瓶颈在池不在线程；
- 依赖 `ThreadLocal` 做缓存的代码——虚拟线程不复用，缓存失效；
- JDK 21–23 上大量使用 `synchronized` 包裹阻塞调用——pinning，实测 57 倍退化。

**几条实践建议：**

1. **不要池化虚拟线程**。`Executors.newVirtualThreadPerTaskExecutor()` 就是正确用法，给它设上限等于放弃它的意义。
2. **并发上限交给信号量或连接池**，不要用线程数控制。
3. **JDK 21–23 上把 `synchronized` 换成 `ReentrantLock`**，尤其是包着 IO 的那些。排查用 `-Djdk.tracePinnedThreads=full`。
4. **别用 `ThreadLocal` 做缓存**，改成显式传参或者带 key 的缓存。
5. **压测时固定 JVM 参数并标注核数**，虚拟线程的收益和核数强相关，脱离环境的数字没有意义。

## 10. 常见坑

1. **把虚拟线程当性能开关**。CPU 密集场景实测 1.00×，只是多了一层间接。
2. **给虚拟线程执行器设上限**。`newFixedThreadPool` 换成虚拟线程版本再设 `maxThreads`，等于自己把优势掐掉。
3. **忽略连接池这个真瓶颈**。线程不排队了，请求全堆在连接池上，`permits=10` 时实测和线程池一样慢。
4. **JDK 21 上 `synchronized` 里阻塞**。1000 个任务从 71ms 变 4080ms，且不报错，只是慢。
5. **以为 `ThreadLocal` 还是缓存**。虚拟线程不复用，每次都是新建，实测 3.7MB 而不是预期的复用。
6. **用 `Thread.activeCount()` 数虚拟线程**。实测 50000 个虚拟线程时它返回 1——虚拟线程不在这个计数里。

## 11. 重点总结

**虚拟线程改变的是「线程成本」，不是「执行速度」：**

- 它让「等待」不再占用操作系统线程，所以 IO 等待型负载能提升一个数量级（实测 20.1×）；
- 它不改变计算的速度，CPU 密集型实测 1.00×；
- 它不改变有界资源的上限，连接池受限时实测 1.00×。

**实测出来的三条硬结论：**

1. **收益完全来自「有没有队列」**。池 100 时 20.1×，池 2000 时只有 2.9×——差距的本质是排队时间，不是虚拟线程更快。
2. **真正的并发旋钮从线程池移到了资源池**。`permits=10` 时虚拟线程和线程池一模一样慢（10894ms vs 10864ms），调线程数已经没用了。
3. **JDK 21 的 pinning 是硬伤，JDK 24 之后消失**。`synchronized` 内 sleep 实测 4080ms vs `ReentrantLock` 62ms，57 倍；JDK 26 上三者都是 63ms 左右。

用虚拟线程的正确姿势是：**放开线程数、锁住资源数、避开 `synchronized`（JDK 21）、别指望 `ThreadLocal`**。它是一把把「线程」这个成本项从账单上划掉的工具，不是让代码变快的工具。

## 12. 参考

- [JEP 444: Virtual Threads](https://openjdk.org/jeps/444)（JDK 21 正式版，虚拟线程的调度模型与 pinning 说明）
- [JEP 491: Synchronize Virtual Threads without Pinning](https://openjdk.org/jeps/491)（JDK 24，消除 `synchronized` 的 pinning）
- [`Thread.ofVirtual()` / `Executors.newVirtualThreadPerTaskExecutor()`](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/Executors.html#newVirtualThreadPerTaskExecutor())（JDK 21 API）
- [`-Djdk.tracePinnedThreads`](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/Thread.html)（pinning 现场抓取）
- 实测工程：JDK 21.0.12.1 / JDK 26.0.2.1，16 核，`-Xmx1g`，六组对照脚本，原始输出见正文
