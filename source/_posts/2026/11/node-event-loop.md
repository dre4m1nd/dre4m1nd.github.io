---
title: "Node 事件循环实测：nextTick 在 ESM 里居然晚于 Promise"
slug: node-event-loop
date: 2026-11-27 11:05:47
description: "在 Node v24.19.0 上实测事件循环：ESM 顶层里 process.nextTick 排在 Promise.then 之后，CommonJS 里却排在前面；主模块中 setImmediate 与 setTimeout(0) 的先后 20 次里翻了 1 次；一段 200ms 的微任务自旋能把 I/O 回调整体推迟到 201ms。"
categories:
  - 技术
tags:
  - 工程实践
  - Node.js
cover: /img/2026/11/node-event-loop.jpg
---

> 「nextTick 队列优先于 Promise 微任务队列」这句话在文档里是对的，但它有一个前提没人写清楚：你在**哪个位置**注册回调。同一个文件里把三段代码换个后缀名，从 `.cjs` 改成 `.mjs`，执行顺序就反了——`nextTick` 从第一位掉到最后一位。
>
> 这篇在 Node v24.19.0 上把四个位置都测了一遍：ESM 顶层、CJS 顶层、I/O 回调内部、以及 setImmediate 与 setTimeout(0) 的竞速。顺带用两个自旋实验量出「饿死」的实际代价：递归 nextTick 跑 200ms，一个已经就绪的 `fs.readFile` 回调被推迟到 201ms 才执行。
>
> 所有数字都是这台机器上单进程跑出来的，每项结论至少重复 20 次。

## 1. 先给结论

同样的四类回调（同步代码、`process.nextTick`、`Promise.then`、`setImmediate`、`setTimeout(0)`），在不同位置注册，顺序不一样：

| 注册位置 | 实际执行顺序 | 符合「nextTick 最优先」吗 |
| --- | --- | --- |
| ESM 顶层（`.mjs`） | sync → `promise.then` → `nextTick` → `setImmediate` → `setTimeout(0)` | **不符合** |
| CJS 顶层（`.cjs`） | sync → `nextTick` → `promise.then` → `setImmediate` → `setTimeout(0)` | 符合 |
| `fs.readFile` 回调内部 | sync body → `nextTick` → `promise.then` → `setImmediate` → `setTimeout(0)` | 符合 |

完整输出（ESM 主模块）：

```text
1 sync start
2 sync end
promise.then
nextTick
setImmediate
setTimeout 0
```

再补一组竞速和一组饥饿实验：

| 实验 | 结果 |
| --- | --- |
| 主模块跑 20 次 setImmediate vs setTimeout(0) | 19 次 immediate 先，**1 次 timeout 先**（非确定） |
| I/O 回调里跑 20 次 | 20 次 immediate 先（确定） |
| 递归 nextTick 自旋 200ms | `fs.readFile` 回调推迟到 **201ms**，期间 nextTick 执行 **1,497,483** 次 |
| 递归 queueMicrotask 自旋 200ms | `setTimeout(0)` 推迟到 **200ms**，期间微任务执行 **1,894,312** 次 |

一句话：**事件循环的模型没变，变的是「回调从哪个位置被注册」——顶层同步脚本、ESM 模块体、I/O 回调，三者处在不同的队列状态里，所以同一份代码的微任务顺序会不一样。**

## 2. 六个阶段

Node 的事件循环是 libuv 里一个六阶段循环，每轮按固定顺序走一遍：

```text
   ┌────────────────────────────┐
┌─>│          timers            │  setTimeout / setInterval 到期回调
│  └────────────┬───────────────┘
│  ┌────────────┴───────────────┐
│  │     pending callbacks      │  上一轮被推迟的 I/O 回调
│  └────────────┬───────────────┘
│  ┌────────────┴───────────────┐
│  │      idle, prepare         │  libuv 内部用
│  └────────────┬───────────────┘
│  ┌────────────┴───────────────┐
│  │           poll             │  取 I/O 事件、执行 I/O 回调；闲时在此阻塞
│  └────────────┬───────────────┘
│  ┌────────────┴───────────────┐
│  │           check            │  setImmediate
│  └────────────┬───────────────┘
│  ┌────────────┴───────────────┐
└──┤      close callbacks       │  socket.on('close') 之类
   └────────────────────────────┘
```

几个容易记混的点：

- **poll 是唯一会阻塞的阶段**。队列空了、又没有任何 timer 和 immediate 待处理时，它就在这里等下一个 I/O 事件，这一等可能几十毫秒。
- **check 紧跟在 poll 后面**。所以在 I/O 回调里注册的 `setImmediate`，会在同一次循环里立刻执行，而 `setTimeout(0)` 得等下一轮 timers。这是后面第 4 组实测的全部原因。
- **`process.nextTick` 和 Promise 不属于任何阶段**。它们不在这个图里，是每个阶段之间被插入执行的。

## 3. 两套队列

Node 有两套独立的队列，都在阶段切换的空隙里被清空：

1. **nextTick 队列** — `process.nextTick(cb)` 进去；
2. **微任务队列** — `Promise.then`、`queueMicrotask`、`await` 的续体进去。

清空规则是：**先清 nextTick 队列，再清微任务队列**。而且第一套要清到底——清的过程中新插入的 nextTick 会被本轮继续执行完，不会留到下一轮。微任务清空之后如果又冒出新 nextTick，还会再回去清一次。

这套「优先」的代价是：nextTick 队列没有上限，也不做让出。只要有人不停往里塞，它就被一直清下去，下面的阶段永远轮不到。

还有一条 Node 11 之后的改动值得记住：**定时器回调之间也会清空微任务队列**。Node 11 之前，多个到期的 timer 回调是连着跑完再清微任务的，所以那时候一个 `Promise.then` 可能排在好几个 timer 后面。现在是每个回调之后都清一次，实测里 timer 和 promise 交替出现，就是这个原因。

## 4. ESM 里 nextTick 为什么反而晚

先看最小复现，三段代码，两种后缀：

```js
// min-repro.mjs — ESM 顶层
// 作用：只留三类微任务，验证 ESM 顶层里 nextTick 排在最后
process.nextTick(() => console.log('A nextTick'));
Promise.resolve().then(() => console.log('B promise'));
queueMicrotask(() => console.log('C queueMicrotask'));
```

```text
B promise
C queueMicrotask
A nextTick
```

换成 `.cjs`，只留两行：

```js
// order.cjs — CommonJS 顶层
// 作用：同样两段代码，CommonJS 顶层同步执行
process.nextTick(() => console.log('A nextTick'));
Promise.resolve().then(() => console.log('B promise'));
```

```text
A nextTick
B promise
```

同一个引擎，同样的两行代码，顺序反了。原因不在 API，在**模块体本身的执行位置**：

**ESM 的顶层模块体是在一个 Promise job（微任务）里跑的。** Node 的 ESM loader 把「求值这个模块」包装成一个 module job，这个 job 挂在微任务队列上。所以模块体里的代码执行时，进程正处在一次微任务检查点当中。模块体结束时，`promise.then` 排进去的回调还在同一个微任务队列里，队列必须先被清空——于是 `B promise`、`C queueMicrotask` 先跑完，控制权才回到 tick 处理逻辑，这时才轮到 nextTick 队列里的 `A`。

**CJS 的顶层模块体是同步执行的**，它本身就是「当前操作」。脚本跑完，当前操作结束，tick 处理逻辑被调用：先清 nextTick 队列（`A`），再进微任务检查点（`B`）。所以 nextTick 在前。

把四类回调放在一起，就是一开始那张表的第一行：

```js
// esm-order.mjs
// 作用：同一 tick 内按固定顺序注册四类回调，看实际执行顺序
console.log('1 sync start');
process.nextTick(() => console.log('nextTick'));
Promise.resolve().then(() => console.log('promise.then'));
setImmediate(() => console.log('setImmediate'));
setTimeout(() => console.log('setTimeout 0'), 0);
console.log('2 sync end');
```

```text
1 sync start
2 sync end
promise.then
nextTick
setImmediate
setTimeout 0
```

注意这个差异**只发生在顶层**。把同样的注册代码挪进 I/O 回调，顺序立刻恢复正常：

```js
// io-order.mjs
// 作用：把四类回调全部注册在 I/O 回调里，对比 poll 阶段之后的顺序
import { readFile } from 'node:fs';
import { fileURLToPath } from 'node:url';

readFile(fileURLToPath(import.meta.url), () => {
  console.log('sync body');
  process.nextTick(() => console.log('nextTick'));
  Promise.resolve().then(() => console.log('promise.then'));
  setImmediate(() => console.log('setImmediate'));
  setTimeout(() => console.log('setTimeout 0'), 0);
});
```

```text
sync body
nextTick
promise.then
setImmediate
setTimeout 0
```

因为 I/O 回调是 libuv 在 poll 阶段调起来的普通任务，不是微任务。回调返回后，tick 处理逻辑照常先清 nextTick 队列。**「ESM 里 nextTick 晚」是一句被截断的结论，完整版是「ESM 顶层里 nextTick 晚」。**

## 5. setImmediate 与 setTimeout(0)

这个竞速有两个版本，结果完全不同。

主模块里跑 20 轮：

```js
// race-main.mjs
// 作用：主模块里 20 轮竞速，每轮记第一个到达的回调
const results = [];

for (let i = 0; i < 20; i++) {
  // 每轮一个占位对象，先到的回调写结果，后到的不再计数
  const slot = { first: null };
  const record = (name) => {
    if (slot.first) return;
    slot.first = name;
    results.push(name);
    if (results.length === 20) {
      const imm = results.filter((n) => n === 'immediate').length;
      console.log(`setImmediate first ${imm}/20, setTimeout first ${20 - imm}/20`);
    }
  };
  setImmediate(() => record('immediate'));
  setTimeout(() => record('timeout'), 0);
}
```

```text
setImmediate first 19/20, setTimeout first 1/20
```

I/O 回调里跑同样 20 轮：

```js
// race-io.mjs
// 作用：在 I/O 回调里跑 20 轮竞速，此时两个回调都已就绪
import { readFile } from 'node:fs';
import { fileURLToPath } from 'node:url';

readFile(fileURLToPath(import.meta.url), () => {
  const results = [];
  for (let i = 0; i < 20; i++) {
    // 同样用占位对象，保证每轮只记一次
    const slot = { first: null };
    const record = (name) => {
      if (slot.first) return;
      slot.first = name;
      results.push(name);
      if (results.length === 20) {
        const imm = results.filter((n) => n === 'immediate').length;
        console.log(`setImmediate first ${imm}/20, setTimeout first ${20 - imm}/20`);
      }
    };
    setImmediate(() => record('immediate'));
    setTimeout(() => record('timeout'), 0);
  }
});
```

```text
setImmediate first 20/20, setTimeout first 0/20
```

**主模块的 19:1 不是随机抖动，是 1ms 边界。** `setTimeout(fn, 0)` 在 Node 里会被抬到 1ms——小于 1 的值按 1 处理。主模块启动时，从「注册 timer」到「进入 timers 阶段」这段耗时如果不到 1ms，timer 还没到期，timers 阶段空转，循环往下走到 check 阶段执行 immediate；如果这段耗时恰好跨过了 1ms（进程刚启动、JIT 还在编译、或者被调度抢占），timer 就已经到期，timers 阶段先执行它。20 次里翻了 1 次，就是这一毫秒的边界被踩到了。

**I/O 回调里是 20:0，因为那里没有 1ms 的悬念。** 回调在 poll 阶段执行，注册的 immediate 排进 check 队列，而 check 就是下一个阶段，紧接着跑；timer 则要等循环绕回 timers，那至少是一整轮之后的事，1ms 早就过了也没有意义——顺序由阶段顺序决定，不由时间决定。

推论：**不要用「setImmediate 一定比 setTimeout(0) 快」来做逻辑判断。** 那个结论只在 poll 之后成立。在主模块里写这种「谁先到就用谁」的代码，你的分支会每二十次错一次。

## 6. 饥饿：微任务能把整个循环饿死

nextTick 和微任务的清空是「清到队列为空为止」。递归自旋时，每次执行都往队列里塞一个新的，队列永远不为空，于是这个清空动作永远不结束。

**实验一：nextTick 自旋 200ms，看一个已经就绪的 I/O 回调被推迟多久。**

```js
// spin-nexttick.mjs
// 作用：先发起 I/O，再用递归 nextTick 自旋 200ms，量回调被推迟的时间
import { readFile } from 'node:fs';
import { performance } from 'node:perf_hooks';
import { fileURLToPath } from 'node:url';

const start = performance.now();
let spins = 0;

// 先发起读文件：请求已经交给线程池，回调在等 poll 阶段
readFile(fileURLToPath(import.meta.url), () => {
  console.log(`readFile callback at ${(performance.now() - start).toFixed(0)}ms, nextTick spins=${spins.toLocaleString('en-US')}`);
});

// 再启动自旋：队列在同一轮里不停被填满，事件循环进不了 poll
(function spin() {
  spins++;
  if (performance.now() - start < 200) process.nextTick(spin);
})();
```

```text
readFile callback at 201ms, nextTick spins=1,497,483
```

文件早在几毫秒内就读完了，数据躺在就绪队列里，但 poll 阶段进不去。200ms 的自旋一停，队列清空，循环往下走到 poll，回调在 201ms 执行。**这 200ms 里，整个进程的 I/O、定时器、网络全部停摆。**

**实验二：同样的自旋换成 queueMicrotask，卡的是定时器。**

```js
// spin-micro.mjs
// 作用：一个宏任务里灌满 200ms 微任务，观察下一个 0ms 定时器被推迟多久
import { performance } from 'node:perf_hooks';

const start = performance.now();
let runs = 0;

setTimeout(() => {
  // 自旋开始前注册第二个 0ms 定时器，它此刻已到期，但没有机会执行
  setTimeout(() => {
    console.log(`timer 2 at ${(performance.now() - start).toFixed(0)}ms, microtasks=${runs.toLocaleString('en-US')}`);
  }, 0);

  // 200ms 内不停往微任务队列塞新任务，同一轮里队列永远清不空
  (function spin() {
    runs++;
    if (performance.now() - start < 200) queueMicrotask(spin);
  })();
}, 0);
```

```text
timer 2 at 200ms, microtasks=1,894,312
```

第二个定时器的到期时间是 2ms 左右，实际执行在 200ms。原因和上面一样：微任务队列没清空，循环不会进入下一个阶段，timers 阶段根本轮不到。

两次的计数差得不多：1,497,483 vs 1,894,312。同样 200ms 里，微任务版本多跑约 26%，这个差异来自入队实现的常数开销，不影响结论——**两套队列都能把事件循环无限期占住，谁也没有「让出」的机制。**

真实系统里这个模式经常以更隐蔽的形式出现：一次请求进来，`await` 链上有几十层，每层 `then` 里又发起新的异步调用，看起来是「异步的」，实际上微任务一直在同一轮里滚动，事件循环照样卡住。区别只是卡 5ms 还是 500ms。

## 7. 正确写法

**一、递归和轮询用具名阶段，不要用微任务。**

```js
// 反例：递归 nextTick，队列在本轮永远清不空，I/O 全部停摆
function pollBad() {
  check();
  process.nextTick(pollBad);
}

// 正解：setImmediate 排到 check 阶段，每轮只跑一次，poll 有机会处理 I/O
function pollGood() {
  check();
  setImmediate(pollGood);
}
```

`setImmediate` 和 `setTimeout` 都是「排到下一轮某个阶段」的语义，天然带让出。递归它们只会让循环空转，不会把循环锁死。真要控频，`setTimeout(fn, ms)` 比自旋精确得多。

**二、大批量微任务要分批让出。**

```js
// 作用：把十万条记录分批处理，每批结束让出一次事件循环
async function processInBatches(items, batchSize) {
  for (let i = 0; i < items.length; i += batchSize) {
    // 批内同步处理，不 await，避免把 for 循环变成微任务链
    for (const item of items.slice(i, i + batchSize)) handle(item);
    // 每批结束让出：setImmediate 进 check 阶段，poll 能在这中间跑 I/O
    await new Promise((resolve) => setImmediate(resolve));
  }
}
```

关键是让出的那一行要落在**宏任务**上。写成 `await Promise.resolve()` 没有用，那只是插进微任务队列，队列照样不清空。

**三、用户态的「延后一下」用 `queueMicrotask`，不用 `process.nextTick`。**

两者语义几乎一样，但 `queueMicrotask` 是标准 API，浏览器里也有，顺序可预期；`process.nextTick` 是 Node 私有，而且名字本身就是误导——它跟 tick 无关，也不在事件循环的任何一个阶段里。

**四、真正需要 nextTick 的场景留着它。**

有一种情况 nextTick 是对的：你必须在**当前操作彻底结束之后、任何 I/O 之前**执行某个动作。典型的是清理句柄、在抛出错误前保证对象状态一致、或者在构造完成前禁止外部观察到半成品。这类需求要的是「比任何 I/O 都早」，而不是「异步一下」，nextTick 是唯一能满足的。除此之外，都不该用它。

## 8. 常见坑

1. **以为 nextTick 永远最先**。在 ESM 顶层不成立，实测 `promise.then` 和 `queueMicrotask` 都排在它前面。把 `.cjs` 改成 `.mjs` 就可能改掉你依赖的顺序。
2. **用 nextTick 做递归轮询**。实测一个已就绪的 `fs.readFile` 回调被推迟 200ms，期间 nextTick 空转 149 万次。这是纯浪费，还会让健康检查、超时定时器一起失准。
3. **以为 `setTimeout(fn, 0)` 是「立刻」**。0 会被抬到 1ms，而且主模块里它和 `setImmediate` 的顺序 20 次翻 1 次，不能当确定行为依赖。
4. **在 nextTick 里做重活**。它阻塞的不是「一个回调」，而是整个循环；放进去的同步计算越多，poll 越晚，I/O 延迟越明显。
5. **以为 `setImmediate` 一定比 `setTimeout(0)` 早**。只在 poll 之后成立（实测 I/O 回调里 20:0），主模块里是 19:1。
6. **用 `queueMicrotask` 递归做「异步化」**。它没有 1ms 下限，比 setTimeout 更容易把循环锁死，实测 200ms 里塞进 189 万次，定时器全部延后。
7. **以为 `await` 之后就到了「下一个 tick」**。`await` 后面的代码是微任务续体，还在同一轮里，和 `Promise.then` 同级。想让出到下一轮，得显式 `await` 一个宏任务。

## 9. 重点总结

**模型本身很简单，坑全在「你在哪儿注册」：**

- 六个阶段循环：timers → pending callbacks → idle/prepare → poll → check → close，poll 是唯一会阻塞的阶段；
- 两套队列在每个阶段之间、每个回调之后被清空，**nextTick 队列先于微任务队列**，且都要清到空为止；
- 微任务不在任何阶段里，它是插在阶段缝隙里的。

**三条实测出来的硬结论：**

1. **ESM 顶层里 nextTick 排在 Promise 之后**（`B promise → C queueMicrotask → A nextTick`），CJS 顶层则相反（`A nextTick → B promise`）。因为 ESM 模块体本身是一个 Promise job，模块体结束时还在微任务队列里；CJS 顶层是同步执行，结束后直接进 nextTick 队列。这个差异只在顶层，I/O 回调里不成立。
2. **setImmediate 与 setTimeout(0) 的顺序由「注册位置」决定**，不由时间决定。主模块 20 次里 19 次 immediate 先、1 次 timeout 先，因为 0 被抬到 1ms，谁先取决于启动耗时有没有跨过这条线；I/O 回调里 20 次全部 immediate 先，因为 poll 的下一个阶段就是 check。
3. **饥饿的代价是可量化的**。递归 nextTick 自旋 200ms，就绪的 I/O 回调推迟到 201ms 才执行，期间空转 1,497,483 次；递归微任务自旋 200ms，0ms 定时器推迟到 200ms，期间执行 1,894,312 次。

**写法上记住四条就够了：** 递归用 `setImmediate`/`setTimeout`，不要用微任务；大批量微任务分批让出；用户态的延后用 `queueMicrotask`；只有「必须比任何 I/O 都早」时才用 `process.nextTick`。

## 10. 参考

- [The Node.js Event Loop, Timers, and `process.nextTick()`](https://nodejs.org/en/learn/asynchronous-work/event-loop-timers-and-nexttick)（六阶段模型与两套队列的官方说明）
- [`process.nextTick()` 文档](https://nodejs.org/api/process.html#processnexttickcallback-args)（明确写了「nextTick 队列优先于微任务队列」，但没写 ESM 顶层的例外）
- [`setImmediate()` 文档](https://nodejs.org/api/timers.html#setimmediatecallback-args)（含「immediate 与 timeout 顺序不确定」的官方示例）
- [`queueMicrotask()`](https://nodejs.org/api/globals.html#queuemicrotaskcallback)（标准微任务 API，跨环境一致）
- [libuv 设计文档](https://docs.libuv.org/en/v1.x/design.html)（事件循环各阶段的底层实现，poll 的阻塞行为在此）
- 实测环境：Node v24.19.0，单进程，每项结论至少重复 20 次，原始输出见正文
