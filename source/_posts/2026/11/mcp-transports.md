---
title: "MCP 的三种传输层：stdio、HTTP+SSE 与 Streamable HTTP"
slug: mcp-transports
date: 2026-11-25 14:00:00
description: "MCP 把传输层做成可插拔的：stdio 用于本机子进程，HTTP+SSE 是已被取代的旧方案，Streamable HTTP 是现在的主力。用官方 SDK 跑起三种传输，抓到真实的握手帧、请求头、会话管理与错误码，讲清各自适合什么场景。"
categories:
  - 技术
tags:
  - MCP
cover: /img/2026/11/mcp-transports.jpg
---

> MCP 的传输层决定「客户端和服务器怎么把 JSON-RPC 消息搬过去」，而不是协议本身。三种方案——stdio、已废弃的 HTTP+SSE、现在的主力 Streamable HTTP——在启动方式、消息格式、会话管理和部署模型上完全不同。这篇用官方 SDK 各跑一遍，把实际抓到的帧、请求头和错误码写下来，而不是抄规范条文。

## 1. 为什么需要专门讨论传输层

MCP 的消息层只有一种格式：JSON-RPC 2.0，UTF-8 编码，生命周期固定为「initialize → initialized → 正常调用 → 关闭」。但「这条消息怎么送到服务器」，规范只规定了几种标准方式，其余交给实现。

传输层决定的是三个实际问题：

1. **服务器跑在哪**——本机子进程，还是远端进程；
2. **怎么启动**——由客户端拉起，还是客户端连上去；
3. **要不要会话**——消息是否必须绑定一个 session。

{% mermaid %}
%%{init: {'theme':'base', 'themeVariables': {'fontFamily':'inherit','fontSize':'14px','minNodeSpacing':20}}}%%
flowchart LR
    A["客户端"] -->|"stdio：拉起子进程，<br/>stdin/stdout 按行传帧"| B["本机服务器进程"]
    A -->|"HTTP+SSE：GET 建流，<br/>POST 发消息"| C["远端服务器"]
    A -->|"Streamable HTTP：POST 发消息，<br/>单端点 + 会话头"| D["远端服务器"]
{% endmermaid %}

## 2. 三种传输一览

| | stdio | HTTP+SSE（旧） | Streamable HTTP |
| --- | --- | --- | --- |
| 规范版本 | 各版本均有 | 2024-11-05 引入 | 2025-06-18 取代前者 |
| 服务器形态 | 客户端拉起的子进程 | 独立进程，支持多客户端 | 独立进程，支持多客户端 |
| 消息方向 | stdin 写、stdout 读 | POST 上行、SSE 下行 | POST 上行、可选 SSE 下行 |
| 会话 | 无，进程即会话 | 有，`sessionId` 在 URL | 有，`Mcp-Session-Id` 头 |
| 多客户端 | 不支持（每客户端一个进程） | 支持 | 支持 |
| 适用 | 本机工具、CLI | 历史兼容 | 远端部署、多客户端 |
| SDK 状态 | 正常 | `SSEServerTransport` 已 `@deprecated` | 推荐 |

下面逐个实测。环境：Node.js 24 + `@modelcontextprotocol/sdk` 1.32.2，一个 `echo` 和 `add` 两个工具的 demo server。

## 3. stdio：按行分帧的本机管道

### 3.1. 线格式

stdio 的规范只有三条硬约束：

- 每行一条 JSON-RPC 消息，**消息内不得含换行**；
- 服务器**不得**往 stdout 写任何非 MCP 消息的内容；
- 日志只能写 stderr，客户端可以忽略。

这意味着调试 stdio 时，日志必须走 stderr，否则会污染协议通道。实测里我加了一个 tee 包装，把每一帧原样打到 stderr：

```js
// tee-stdio.js
// 作用：转发子进程的 stdin/stdout，同时把每一帧 JSON-RPC 打到 stderr
process.stdin.on("data", (chunk) => {
  process.stderr.write(`[C→S] ${chunk.toString().trim()}\n`);
  child.stdin.write(chunk);
});

// 作用：把子进程的 stdout 原样转发，并记录服务端发来的帧
child.stdout.on("data", (chunk) => {
  process.stderr.write(`[S→C] ${chunk.toString().trim()}\n`);
  process.stdout.write(chunk);
});
```

### 3.2. 实测到的握手帧

```text
[C→S] {"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"demo-client","version":"0.1.0"}},"jsonrpc":"2.0","id":0}
[S→C] {"result":{"protocolVersion":"2025-11-25","capabilities":{"tools":{"listChanged":true}},"serverInfo":{"name":"demo-stdio","version":"0.1.0"}},"jsonrpc":"2.0","id":0}
[C→S] {"method":"notifications/initialized","jsonrpc":"2.0"}
[C→S] {"method":"tools/list","jsonrpc":"2.0","id":1}
[S→C] {"result":{"tools":[...]},"jsonrpc":"2.0","id":1}
[C→S] {"method":"tools/call","params":{"name":"echo","arguments":{"text":"hello"}},"jsonrpc":"2.0","id":2}
[S→C] {"result":{"content":[{"type":"text","text":"echo:hello"}]},"jsonrpc":"2.0","id":2}
```

三个直接结论：

1. **没有 HTTP，没有请求头，没有状态码**，每帧就是一个 JSON 对象；
2. **协议版本在 `initialize` 里协商**，这里协商结果是 `2025-11-25`（SDK 支持 `2025-11-25`、`2025-06-18`、`2025-03-26`、`2024-11-05`、`2024-10-07` 五个版本）；
3. **通知没有 `id`**，请求和响应都有。

### 3.3. 生命周期由进程控制

客户端连接时拉起服务器，关闭时关闭 stdin 并终止子进程。这意味着：

- **每个客户端一个进程**，天然隔离，状态不会串；
- **不支持多客户端共享一个服务器**，进程内存就是会话；
- 服务器进程常驻成本取决于谁持有它，客户端退出后进程必须被回收。

## 4. 旧版 HTTP+SSE：两个端点，已废弃

HTTP+SSE 是 2024-11-05 版本定义的方案，用两个端点：`GET /sse` 建立 SSE 下行流，`POST /messages` 上行 JSON-RPC。2025-06-18 规范里它已经被 Streamable HTTP 取代，SDK 里的 `SSEServerTransport` 也明确标了 `@deprecated`。

### 4.1. 实测到的握手

用 curl 直接连 `GET /sse`，收到的第一个事件就是服务器告诉客户端「上行该发到哪」：

```text
event: endpoint
data: /messages?sessionId=ff3026b1-9701-4d6b-a267-2c02daae09b8
```

服务端日志里，会话在 GET 时就建立了：

```text
[HTTP] GET /sse accept=text/event-stream session=-
[SSE] stream opened sessionId=ff3026b1-9701-4d6b-a267-2c02daae09b8
```

### 4.2. 上行和下行的分工

- **下行**：`GET /sse` 保持一条长连接，服务器把消息（响应、通知、请求）从这条流推给客户端；
- **上行**：客户端把 JSON-RPC 消息 POST 到 `/messages?sessionId=...`，服务器处理完，结果经那条 SSE 流推回。

实测客户端连接时的四个 POST：

```text
[HTTP] POST /messages accept=*/* session=a44853e2-0d4c-43a6-9e1e-6d1e274f9c2c
```

对应 `initialize`、`initialized`、`tools/list`、`tools/call` 四步。

### 4.3. 它的两个结构性问题

**一是两个端点互相依赖**：POST 的响应不通过 HTTP 直接返回，而是必须等对应的 SSE 连接在，结果才能推过去。任何网络抖动、代理、负载均衡把长连接断开，消息就断了，且没有重连语义。

**二是没有统一的会话头**：session 靠 URL 参数传递，服务器实现只要把 sessionId 放的位置不同，客户端就得跟着改。

这也是它被取代的原因。

## 5. Streamable HTTP：单端点 + 会话头

现在的主力。一个端点同时支持 `POST` 和 `GET`，会话通过 `Mcp-Session-Id` 请求头传递。

### 5.1. 实测到的初始化

服务端先收到不带 session 的 `initialize`，响应头里给出会话 ID：

```text
[HTTP] POST /mcp accept=application/json, text/event-stream content-type=application/json session=- protocol=-
[HTTP] session initialized 4c1934ba-a669-4e6c-9a47-7bea1ed5587b
[HTTP] response 200 mcp-session-id=4c1934ba-a669-4e6c-9a47-7bea1ed5587b
```

后续请求必须带这个头，并且带上协议版本：

```text
[HTTP] POST /mcp accept=application/json, text/event-stream content-type=application/json session=4c1934ba-... protocol=2025-11-25
```

curl 抓响应头可以看到完整格式：

```text
HTTP/1.1 200 OK
content-type: text/event-stream
mcp-session-id: 6ddf5e18-b5c9-4f50-9ba0-05a9fa63f139
x-accel-buffering: no

event: message
data: {"result":{"protocolVersion":"2025-11-25",...},"jsonrpc":"2.0","id":1}
```

注意：**即使只有一个响应，服务器也用 SSE 帧装回来**，因为客户端的 `Accept` 同时声明了 `application/json` 和 `text/event-stream`。

### 5.2. 三个错误码实测

| 场景 | 实测结果 |
| --- | --- |
| `Accept` 只写 `application/json` | **406** `Client must accept both application/json and text/event-stream` |
| 非初始化请求不带 session | **400** `Bad Request: Server not initialized` |
| 带了一个不存在的 session | **404** `Session not found` |

406 这条最容易踩：客户端只声明 `application/json`，服务器直接拒绝。规范要求客户端**必须同时声明**两种类型，因为服务器可能选任意一种方式回应。

### 5.3. GET 与 DELETE

- `GET /mcp`：客户端主动开一条 SSE 流，接收服务器主动推来的请求和通知（不等待 POST）。实测请求带 `Accept: text/event-stream` + session 头；
- `DELETE /mcp`：显式终止会话，实测返回 `200`；终止后再发请求，得到 400（会话已不存在）。

### 5.4. 会话生命周期

会话从 `initialize` 开始，客户端必须复用服务器返回的 `Mcp-Session-Id`；服务器可以随时终止会话，之后带该 ID 的请求应返回 404；客户端收到 404 后**必须重新发起 `initialize`**。规范里也建议客户端在退出时主动发 `DELETE`。

## 6. 横评：什么时候用哪种

| 需求 | 选择 | 理由 |
| --- | --- | --- |
| 本机命令行工具、CLI 集成 | stdio | 零网络开销，进程隔离，日志走 stderr 即可 |
| 远端部署、多客户端共享 | Streamable HTTP | 单端点、会话可复用，支持流式推送 |
| 需要服务器主动调用客户端（如资源订阅） | Streamable HTTP | GET 建立的 SSE 流是服务器主动通道 |
| 兼容老客户端 | 兼挂 HTTP+SSE 端点 | 旧端点已废弃，只用于历史兼容 |
| 需要进程级隔离、互不影响 | stdio | 每个客户端一个进程，没有共享会话状态 |

一句话：**本机用 stdio，远端用 Streamable HTTP，HTTP+SSE 只在兼容老客户端时保留。**

## 7. 常见坑

1. **stdio 的日志不能走 stdout**。任何非 JSON-RPC 的输出都会破坏协议，日志必须写 stderr，客户端可以忽略。
2. **Streamable HTTP 的 `Accept` 必须同时包含两种类型**。只写 `application/json` 会被 406 拒绝。
3. **会话头不能丢**。初始化拿到 `Mcp-Session-Id` 后，后续每个请求都要带；丢失后非初始化请求会得到 400，过期会话得到 404，客户端需要重新 initialize。
4. **协议版本头**。HTTP 传输在初始化之后必须带 `MCP-Protocol-Version`，否则服务器会按旧版本 `2025-03-26` 处理，行为可能不一致。
5. **状态模式和无状态模式不同**。服务端不设置 `sessionIdGenerator` 时不下发会话 ID，请求无状态，适合负载均衡和水平扩展，但服务器无法向客户端主动推消息。
6. **旧端点别当新协议用**。`SSEServerTransport` 已废弃，新项目不要选它；只在需要兼容老客户端时才保留 `/sse` + `/messages` 两个端点。
7. **本地安全**。规范要求服务器校验 `Origin` 头并绑定 `127.0.0.1`，否则可能被 DNS 重绑定绕过。

## 8. 重点总结

**三种传输的本质区别，是「消息怎么送」和「会话怎么标识」：**

- **stdio**：进程即会话，按行分帧，无请求头，适合本机单客户端；
- **HTTP+SSE**：两个端点、URL 传 session，已废弃，只在兼容老客户端时保留；
- **Streamable HTTP**：单端点 + `Mcp-Session-Id` 头，POST 上行、GET 建流，是现在的主力。

**实测出来的三条硬结论：**

1. **stdio 的分帧是规范级的**：一行一条 JSON-RPC，消息内不能含换行，日志只能走 stderr。
2. **Streamable HTTP 对客户端有硬约束**：`Accept` 必须同时声明 `application/json` 和 `text/event-stream`，否则 406；会话头丢了就是 400，过期就是 404。
3. **协议版本在 `initialize` 里协商**，HTTP 传输之后还要在请求头里带上；SDK 当前最高支持 `2025-11-25`。

选型上没有悬念：**本机工具用 stdio，远端部署用 Streamable HTTP**。真正需要注意的，是把「日志走哪条通道」「会话头别丢」「Accept 写全」这三件事在实现前就定好。

## 9. 参考

- [MCP 2025-06-18 规范 · Transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)（stdio 线格式、Streamable HTTP 的 Accept/会话/版本头要求、向后兼容说明）
- [MCP 2024-11-05 规范 · HTTP with SSE](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports)（被取代的旧方案）
- [`@modelcontextprotocol/sdk` 1.32.2](https://www.npmjs.com/package/@modelcontextprotocol/sdk)（`StdioServerTransport`、`SSEServerTransport`、`StreamableHTTPServerTransport`）
- 实测工程：Node.js 24 + Express，三个 server（stdio / SSE / Streamable HTTP）与对应 client，原始输出见正文
