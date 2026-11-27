---
title: "G1、ZGC、Serial 跑同一个分配型负载：0 次停顿的代价是什么"
slug: jvm-gc-g1-zgc
date: 2026-11-27 10:30:05
description: "用同一个分配型负载（200MB 存活集 + 每轮 200MB 短命对象，12 秒，-Xmx1g）在 JDK 21 上跑 G1、ZGC、Serial 三种收集器。G1 停顿 360 次共 378ms，ZGC 停顿 0 次但分配总量最低，Serial 吞吐最高却停顿 980 次。把三种日志摆在一起看，才看得清吞吐和延迟是怎么互相换的。"
categories:
  - 技术
tags:
  - 工程实践
  - JVM
cover: /img/2026/11/jvm-gc-g1-zgc.jpg
---

> 「ZGC 是零停顿」「G1 是默认所以最平衡」「Serial 已经过时了」——这三句话都对，也都没用。真要选，得知道它们各自把什么换走了。
>
> 这篇在 JDK 21.0.12.1、`-Xmx1g`、16 核的机器上，用一个刻意做成「分配密集型」的负载（200MB 存活集 + 每轮 200MB 短命对象，跑 12 秒）跑了三种收集器。结果是：G1 停顿 360 次共 378ms，ZGC 一次 GC 停顿都没有但分配总量最低（97.7 GB），Serial 分配总量最高（129.4 GB）却停顿了 980 次。三个数字放在一起，正好把「吞吐换延迟」这条曲线上的三个点标出来。

## 1. 先给结论

| 收集器 | 分配总量 | 停顿次数 | 总停顿 | 平均 | 最大 | p99 |
|---|---|---|---|---|---|---|
| G1（默认） | 114.7 GB | 360 | 378 ms | 1.05 ms | 17.7 ms | 11.5 ms |
| ZGC | 97.7 GB | **0** | **0 ms** | — | — | — |
| Serial | **129.4 GB** | 980 | 348 ms | 0.36 ms | 19.1 ms | 1.5 ms |

三条结论：

1. **ZGC 的 0 次停顿是真的**，日志里一个 `Pause` 行都没有；代价是分配总量只有 G1 的 85%、Serial 的 76%——并发标记/移动线程在跟你抢 CPU。
2. **Serial 的吞吐最高，但停顿次数是 G1 的 2.7 倍**。它的单次停顿很短（平均 0.36ms），因为堆小、回收动作简单；但一停就是一次全堆扫描，次数堆上去了。
3. **G1 落在中间**：总停顿时长最长（378ms），单次最长 17.7ms，是三者里唯一会让应用感知到「卡一下」的。

注意口径：三次运行都在**同一台机器、同一个 JVM 参数、同一个负载**下跑的，但**不是 JMH**，没有多轮预热与统计。12 秒的窗口里 G1 只有 360 个样本、Serial 980 个、ZGC 0 个，所以绝对数字只能横向比，不能当基准。

## 2. 负载怎么设的

关键是要有 GC 压力，但又不能把 JVM 直接 OOM。做法是「存活集 + 高频短命对象」：

```java
public class Alloc {
    // 黑盒：阻止逃逸分析把分配优化掉，否则循环会被整个消除
    static volatile Object sink;

    public static void main(String[] args) throws Exception {
        long deadline = System.currentTimeMillis() + 12_000;
        // 存活集约 200MB：这批对象全程活着，逼 GC 每轮都要标记/移动
        List<byte[]> live = new ArrayList<>();
        for (int i = 0; i < 2000; i++) live.add(new byte[100 * 1024]);

        long alloc = 0;
        while (System.currentTimeMillis() < deadline) {
            // 每轮约 200MB 短命对象：出生即死，专门制造回收压力
            for (int i = 0; i < 20000; i++) {
                byte[] b = new byte[10 * 1024];
                b[0] = (byte) i;
                sink = b;
                alloc += b.length;
            }
        }
        System.out.printf("分配总量 %.1f GB, 存活 %d MB%n", alloc / 1e9, live.size() * 100 / 1024);
    }
}
```

`static volatile Object sink` 这一行是整段代码里最重要的：第一次跑的时候忘了加，JIT 判定新数组没被用到，直接把整个分配循环优化掉了——GC 日志只有 1.7K，一次停顿都没有，看起来「ZGC 真香」，其实是根本没跑。

启动参数三组只差收集器那一个开关：

```bash
# G1：JDK 21 默认，不用显式指定
java -Xmx1g -Xlog:gc Alloc

# ZGC：JDK 21 上默认是单代实现，日志里会写 Using legacy single-generation mode
java -Xmx1g -XX:+UseZGC -Xlog:gc Alloc

# Serial
java -Xmx1g -XX:+UseSerialGC -Xlog:gc Alloc
```

ZGC 那行注释是实测出来的细节：JDK 21 的 ZGC 分代要额外加 `-XX:+ZGenerational`，不加就是单代。分代 ZGC 到 JDK 23 才成为默认。

## 3. 三种日志长什么样

G1 的典型行，带原因、带前后占用、带耗时：

```text
[info][gc] GC(37) Pause Young (Normal) (G1 Evacuation Pause) 23M->5M(244M) 5.103ms
```

`Normal` 是常规 Young GC（区别于 `Concurrent Start` 之后的混合回收），`23M->5M` 是回收前后的堆占用，`244M` 是当时的堆容量。

ZGC 压根不打印 `Pause`：

```text
[info][gc] GC(12) Garbage Collection (Warmup) 254M(25%)->288M(28%)
[info][gc] GC(13) Garbage Collection (Allocation Rate) 288M(28%)->301M(29%)
```

括号里是触发原因（`Warmup` 预热、`Allocation Rate` 分配太快），没有耗时字段，因为它没有「停下来干活」的阶段——标记、转移、重映射都是和业务线程一起跑的，靠读屏障做并发修正。

Serial 的典型行最短：

```text
[info][gc] GC(58) Pause Young (Allocation Failure) 65M->35M(235M) 19.066ms
```

`Allocation Failure` 就是「年轻代满了，只能停下来收」。这一行能看到它的性格：一次要扫整块年轻代，所以单次 19ms 并不短；但因为堆只有 1G、对象死得快，多数时候一次就能收出足够空间。

## 4. G1：360 次停顿，p99 11.5ms

360 次停顿、总共 378ms、平均 1.05ms。平均看着很漂亮，问题在尾部：最大 17.7ms，p99 11.5ms。

G1 的设计目标就是这个形状——它把堆切成 region，每次只挑「回收收益最高」的一批 region 来搬，靠 `-XX:MaxGCPauseMillis`（默认 200ms）做预测，让单次停顿尽量短。代价是**次数多**：12 秒里 360 次，差不多每 33ms 一次。

对绝大多数 Web 服务，这个形状是可以接受的：单次 10ms 级别的停顿，落在一次请求的处理时间里几乎看不出来。但如果你的应用对尾延迟敏感（比如 p99 要压在 5ms 以内），G1 的 11.5ms 就是硬伤。

## 5. ZGC：0 次停顿，但分配总量最低

`grep -c Pause` 的结果是 0。ZGC 把所有重活都挪到并发阶段：标记并发做，对象转移并发做，指针修正靠读屏障在访问时顺带完成。业务线程不会被整体停住。

代价写在分配总量那一列：97.7 GB，比 G1 少 17%、比 Serial 少 24%。原因不复杂——**并发 GC 线程和业务线程抢同一批 CPU**。这台机器 16 核，ZGC 默认会起一批并发线程（`ConcGCThreads`），它们干活的时候，业务线程能用的算力就少了。

这条结论有个直接推论，而且很多人踩：**容器里 CPU limit 很紧时，ZGC 可能比 G1 更慢**。容器只给 2 核、ZGC 起 2~3 个并发线程，等于业务线程被砍掉一半算力，吞吐掉得比停顿收益更多。JVM 能读到 cgroup 的限制（`-XX:+UseContainerSupport` 默认开），但它只会相应减少线程数，不会告诉你「其实这时候该用 G1」。

另外要澄清一个常见误读：**「0 次 Pause」不等于「0 延迟开销」**。读屏障是有成本的（每次引用访问多一次判断），转移对象时的并发拷贝也会占用带宽。ZGC 消掉的是 STW，不是全部开销。

## 6. Serial：吞吐最高，停顿次数最多

129.4 GB，三者最高。理由也简单：单线程回收，没有跨线程协调、没有写屏障、没有并发线程抢 CPU，所有算力都给了业务代码。单次停顿平均 0.36ms 也最短——堆就这么大，扫一遍很快。

但 980 次停顿，是 G1 的 2.7 倍。而且它的停顿是「全停」：年轻代一满就 STW，不管当时业务在干什么。总停顿时长 348ms 反而比 G1 的 378ms 少，纯粹是因为堆小、每次收得快。

所以「Serial 已经过时」这个判断，只在「堆大 + 多核 + 长生命周期对象多」这三个条件同时成立时才对。在一个 1G 堆、跑批处理、对尾延迟不敏感的场景里，Serial 依然可能是吞吐最高的选择——这也是为什么很多大数据组件（Spark executor 之类）默认还留着它。

## 7. 停顿次数和停顿时长是两个维度

把三组数据摆在一起，最容易犯的错是只比其中一列：

| 只看… | 结论会被带偏成 |
|---|---|
| 总停顿时长 | 378ms vs 348ms vs 0ms → 「ZGC 完胜」 |
| 停顿次数 | 360 vs 980 vs **0** → 「Serial 很糟」 |
| 分配总量（≈吞吐） | 129.4 vs 114.7 vs 97.7 GB → 「Serial 完胜」 |

这三个结论互相矛盾，因为它们在优化不同的东西：

- **总停顿时长**决定应用「整体被耽误了多久」，影响吞吐的绝对值；
- **单次停顿的最大值/p99** 决定尾延迟，影响用户能不能感觉到卡；
- **分配总量** 决定这段 CPU 时间里，业务实际干了多少活。

选收集器就是在这三项里选一个你最能接受的取舍点。没有「最好」的收集器，只有「你的 SLO 更在乎哪一列」。

## 8. 选型表

| 场景 | 建议 | 理由 |
|---|---|---|
| 通用 Web 服务，堆 2~32G，p99 可以容忍 10~20ms | G1（默认） | 停顿次数多但单次短，综合最省心 |
| 堆超大（32G 以上）、尾延迟要求极严 | ZGC | STW 归零，代价是吞吐与 CPU 占用 |
| 容器 CPU 配额很紧（≤2 核） | G1，别上 ZGC | 并发线程会直接抢业务算力 |
| 跑批/离线任务，只在乎总时长 | Serial 或 Parallel | 没有并发协调开销，单核吞吐最高 |
| 小堆（≤1G）、生命周期短的进程 | Serial | 回收动作简单，短进程里预热成本低 |

`Parallel` 没在这篇的实测里，但它在「吞吐优先 + 多核」这个格子里比 G1 更合适：它也是 STW，但用多线程并行扫描，单次停顿会比 Serial 短、吞吐比 G1 高。

## 9. 常见坑

1. **忘了阻止逃逸分析**。分配循环被 JIT 优化掉，GC 日志干干净净，你会得出完全相反的结论。加一个 `volatile` 字段写一次就够了。
2. **把 `-XX:MaxGCPauseMillis` 当硬保证**。G1 的 200ms 是**目标值**，靠 region 回收顺序去逼近，不保证。实测 17.7ms 的最大停顿是运气好，堆更大、存活集更多时会明显变差。
3. **以为 ZGC 的 0 次 Pause 代表没有任何开销**。读屏障、并发转移、CPU 抢占都在成本里，只是不体现在 Pause 行上。
4. **在 CPU 受限的容器里直接抄「大厂用 ZGC」**。他们的机器核多，你的容器可能只有 2 核。
5. **样本太小就下结论**。12 秒、360 个样本，p99 其实就是第 4 个最慢的值。换成 10 分钟、`-Xmx4g`，三种收集器的差距会变样。
6. **直接拿分配总量当吞吐指标**。分配总量只反映「这段 CPU 时间里分配了多少字节」，真实业务的吞吐还要看每单位工作的成本。
7. **JDK 21 上以为 ZGC 已经是分代的**。要看日志第一行：`Using legacy single-generation mode` 就是单代，分代得加 `-XX:+ZGenerational`。

## 10. 重点总结

三条实测结论：

1. **ZGC 的 STW 真的可以做到 0**，12 秒里零个 `Pause` 行；代价是分配总量最低（97.7 GB vs G1 114.7 GB），因为并发线程抢 CPU。
2. **Serial 吞吐最高（129.4 GB）但停顿次数最多（980 次）**，单次平均 0.36ms；G1 居中但尾部最差（最大 17.7ms、p99 11.5ms）。
3. **三个指标必须一起看**。只看停顿次数会误判 Serial，只看总停顿会误判 G1，只看吞吐会误判 ZGC。

做 GC 选型时最省时间的做法不是背结论，而是**把你自己的负载按这篇的 `Alloc` 改成两三种，各跑一遍 `-Xlog:gc`**，然后把「停顿次数 / 最大停顿 / 分配总量」三列填出来。二十行代码，比任何一篇 GC 调优文章都更接近你的真实情况。

## 11. 参考

- [HotSpot Virtual Machine Garbage Collection Tuning Guide (JDK 21)](https://docs.oracle.com/en/java/javase/21/gctuning/)
- [JEP 439: Generational ZGC](https://openjdk.org/jeps/439)
- [JEP 333: ZGC: A Scalable Low-Latency Garbage Collector](https://openjdk.org/jeps/333)
- [JEP 248: Make G1 the Default Garbage Collector](https://openjdk.org/jeps/248)
- [JEP 473 / Unified GC Logging 说明](https://docs.oracle.com/en/java/javase/21/troubleshoot/analyze-java-garbage-collection-logs.html)
