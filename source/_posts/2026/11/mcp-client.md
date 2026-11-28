---
title: "MCP 客户端实测：超时之后服务端还在跑，取消是协作式的"
slug: mcp-client
date: 2026-11-28 11:21:40
description: "用官方 SDK 从客户端这半边把 MCP 跑了一遍：timeout 600ms 时服务端确实收到了取消，但如果工具不检查 signal，钱已经扣完、账本照写；progress 通知默认不重置超时，除非打开 resetTimeoutOnProgress；不传 progressToken 时 SDK 会自己造一个；同一个 Client 第二次 connect 直接报错，transport 反而可以复用。"
categories:
  - 技术
tags:
  - MCP
cover: /img/2026/11/mcp-client.jpg
---

> [服务端](/2026/11/mcp-server/)和[传输层](/2026/11/mcp-transports/)写过了，客户端这半边没人讲，但它才是踩坑的地方：**超时是客户端单方面放弃，不是服务端回滚**。SDK 会替你发 `notifications/cancelled`，可工具要是不看 `signal`，该写的账本一条不少。
>
> 这篇用 `@modelcontextprotocol/sdk` 1.32.2 把客户端的关键路径全跑了一遍：超时与取消、进度通知与超时重置、roots 和 sampling 两个反向请求、以及连接能不能重连。所有结论都对应正文里的实际错误码和耗时。
>
> 环境：Node.js 24.19.0，SDK 1.32.2，stdio 传输，server 是 `client-server.js`，带五个故意做坏的 tool。

## 1. 结论先行

| 行为 | 实测结果 |
| --- | --- |
| 请求超时 | 抛 `McpError`，`code = -32001`，消息 `Request timed out` |
| 超时后服务端会收到取消吗 | **会**，`notifications/cancelled` 发出，`extra.signal` 变成 aborted |
| 取消有效吗 | **只在工具检查 signal 时有效**；不检查就照跑完，副作用落地 |
| `progress` 能延长超时吗 | 默认**不能**；只有 `resetTimeoutOnProgress: true` 才能 |
| 不传 `progressToken` 会怎样 | 只要给了 `onprogress`，SDK 自动生成一个（实测是 `5`） |
| roots / sampling | 客户端必须声明能力并注册 handler，否则服务端拿到 `-32601 Method not found` |
| 同一个 Client 再 connect | 报错 `Already connected to a transport` |
| close 之后复用 | Client 不能复用（`Not connected`），transport 能重新 start |

## 2. 实验怎么搭的

服务端注册了四个工具，每个对应一种客户端行为：

| 工具 | 用途 |
| --- | --- |
| `slow` | 睡 N 秒，**检查** `extra.signal`，用来验证取消链路 |
| `stubborn` | 睡 N 秒，**故意不检查** signal，写一行账本后返回 |
| `progress_steps` | 分 steps 步，每步发一条 `notifications/progress` |
| `list_roots` / `ask_model` | 反向请求：向客户端要 roots、要一次采样 |

客户端统一用 `new Client({name, version}, {capabilities})`，`connect()` 里用 `StdioClientTransport` 起子进程。

## 3. 超时：客户端抛错，服务端收到取消

```js
await client.callTool({ name: "slow", arguments: { seconds: 3 } }, undefined, { timeout: 600 });
```

```text
[cli +1021ms] client 抛错 code=-32001 message=MCP error -32001: Request timed out
[srv +644ms] slow: 收到取消信号，已运行 618ms
[srv +686ms] slow(3) 结束 aborted=true 用时 660ms
```

客户端在 600ms 时放弃，服务端在 **644ms** 收到取消信号——`extra.signal` 被 abort，循环提前退出。这条链路是通的。

**但它是协作式的。** 换成那个不检查 signal 的工具：

```js
await client.callTool({ name: "stubborn", arguments: { seconds: 2 } }, undefined, { timeout: 600 });
```

```text
[srv +3841ms] stubborn(2) start（故意不检查 signal）
[cli +4671ms] client 抛错 code=-32001 message=MCP error -32001: Request timed out
[srv +5860ms] stubborn(2) 结束，已写账本，用时 2019ms
[cli +7174ms] 2.5s 后账本内容: charge 2026-11-28T02:47:27.906Z amount=99
```

客户端在 600ms 就认为「这次调用失败了」，服务端在 2019ms 完成扣款并记账。**从客户端视角看是一次失败，从账户视角看是一次扣款。**

这就是「超时 = 结果未知」，不是「超时 = 没发生」。任何带副作用的 tool，超时后都必须去查真实状态，而不是直接重试——重试就是重复扣款。

## 4. 进度：默认不重置超时

一个 5 步、每步 200ms 的任务（总共约 1 秒），超时设 600ms：

```text
[cli +4835ms] 超时：收到 2 条进度后抛错 code=-32001
```

进度通知照收，但超时计时器**不重置**——600ms 到点就断。要让它按「有进展就续命」工作，得显式打开：

```js
await client.callTool(
  { name: "progress_steps", arguments: { steps: 5, delayMs: 200 }, _meta: { progressToken: "p-2" } },
  undefined,
  { timeout: 600, resetTimeoutOnProgress: true, maxTotalTimeout: 5000, onprogress: () => got++ }
);
```

```text
[cli +5847ms] 完成：收到 5 条进度，结果=5 步完成
```

`maxTotalTimeout` 是硬上限，防止「一直有进度、永远不结束」的任务把客户端拖死。

还有一个反直觉的细节：**不传 `_meta.progressToken` 时，只要给了 `onprogress`，SDK 会自己造一个**。

```js
await client.callTool({ name: "progress_steps", arguments: { steps: 3, delayMs: 100 } }, undefined, {
  timeout: 2000,
  onprogress: () => got++,
});
```

```text
[srv +5470ms] progress_steps token=5 steps=3
[cli +6170ms] 完成：收到 3 条进度，结果=3 步完成
```

服务端看到的 `progressToken` 是 `5`——调用方根本没传。**如果你的服务端靠 token 有没有来区分「客户端要不要进度」，这个判断会失效。**

## 5. roots 和 sampling：反向请求

这两个能力的方向是反的：**服务端**发起请求，**客户端**负责应答。所以客户端必须做两件事——声明能力、注册 handler，缺一不可。

```js
const client = new Client({ name: "lab-client", version: "1.0.0" }, {
  capabilities: { roots: { listChanged: true }, sampling: {} },
});
client.setRequestHandler(ListRootsRequestSchema, async () => ({
  roots: [{ uri: "file:///D:/notes/blog-hexo", name: "blog" }],
}));
client.setRequestHandler(CreateMessageRequestSchema, async (req) => ({
  role: "assistant", content: { type: "text", text: "这是客户端返回的假回复" }, model: "stub-model",
}));
```

实测两端都对上了：

```text
[srv +23ms] listRoots -> {"roots":[{"uri":"file:///D:/notes/blog-hexo","name":"blog"},...]}
[srv +24ms] createMessage -> {"model":"stub-model","role":"assistant","content":{"type":"text","text":"这是客户端返回的假回复"}}
```

`createMessage` 就是「服务端让客户端跑一次模型」。这里返回的是假数据，但链路是真的：**客户端不声明 `sampling` 能力，服务端这一步就会失败**，而且失败发生在服务端内部，客户端只看到一个 `isError` 的工具结果。

## 6. 连接生命周期：Client 不能重连，transport 可以

```text
===== 6. 第二次 connect()
[cli +6689ms] 第二次 connect 失败：Error | Already connected to a transport. Call close() before connecting to a new transport, or use a separate Protocol instance per connection.
```

```text
===== 7. close 之后再用 / 复用同一个 transport
[cli +6935ms] close 后 callTool 失败：Error | Not connected
[cli +7175ms] 复用旧 transport 成功，tools=4
[cli +7421ms] 换一个全新 client + transport 重建成功，tools=4
```

结论很具体：

- **一个 `Client` 只能绑定一个 transport**，第二次 `connect()` 直接抛错，错误信息里给了两条路：先 `close()`，或者换一个 `Protocol` 实例。
- `close()` 之后这个 Client 就废了，任何请求都是 `Not connected`。
- **transport 反而可以复用**：`StdioClientTransport` 重新 `start()` 会再拉起一个子进程，新的 Client 能接上。
- 所以重连的正确姿势是「新 Client + 可复用的 transport」，不是「同一个 Client 再 connect 一次」。

## 7. 常见坑

- **把超时当失败处理。** 超时是 `-32001`，含义是「不知道结果」。带副作用的调用必须查状态，不能直接重试。
- **工具不检查 `extra.signal`。** SDK 会发取消通知，但没有任何机制能打断你的 `await`。长任务要自己监听 abort。
- **以为 progress 会自动续命。** 默认不续；要续必须 `resetTimeoutOnProgress: true`，并且配套设 `maxTotalTimeout`。
- **靠 `progressToken` 是否存在判断客户端意图。** SDK 在 `onprogress` 存在时会自动生成 token。
- **只声明能力不注册 handler。** 服务端的反向请求会变成 `-32601 Method not found`（实测：`listRoots 失败: MCP error -32601`），报错位置在服务端，排查时容易找错方向。
- **同一个 Client 重连。** 只会拿到 `Already connected`，正确做法是新 Client 复用 transport。

## 8. 重点总结

- **超时是客户端单方面放弃**：`-32001` 只说明客户端不再等，不说明服务端没执行。
- **取消是协作式的**：`slow` 在 644ms 收到信号并退出；`stubborn` 不理信号，2019ms 照样写完账本。
- **进度默认不延长超时**，要延长得显式开 `resetTimeoutOnProgress`，并用 `maxTotalTimeout` 兜底。
- **客户端能自动生成 `progressToken`**，不想被"自动"影响就别用 `onprogress`，或者服务端自己判定。
- **roots/sampling 需要能力 + handler 双份声明**；**Client 不能重连，transport 可以复用**。
- 由此推论：MCP 里凡是带副作用的 tool，**超时后必须靠业务幂等兜底**——这正好是下一篇要量化的东西。

## 9. 参考

- [Model Context Protocol — Client](https://modelcontextprotocol.io/docs/learn/client-concepts)
- [MCP specification — Cancellation](https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/cancellation)
- [MCP specification — Progress](https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/progress)
- [@modelcontextprotocol/sdk (npm)](https://www.npmjs.com/package/@modelcontextprotocol/sdk)
