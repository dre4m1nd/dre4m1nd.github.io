---
title: "自己写一个 MCP server：tool、resource、prompt 三件套的边界在哪"
slug: mcp-server
date: 2026-11-26 11:18:42
description: "用 @modelcontextprotocol/sdk 1.32.2 从零写一个 MCP server，把 tool、resource、prompt 三类能力各注册一遍，用 stdio client 逐项调用，抓下 tools/list、resources/templates/list、prompts/list 的真实返回，验证三条边界：工具错误和协议错误的区别、参数校验失败走哪条通道、鉴权为什么只能在传输层做。"
categories:
  - 技术
tags:
  - MCP
cover: /img/2026/11/mcp-server.jpg
---

> 传输层只解决「消息怎么送」，真正决定一个 MCP server 好不好用的是它暴露了哪些能力、以及出错时怎么说话。这篇用官方 SDK 写一个最小 server，把 tool / resource / prompt 三类能力各注册一遍，逐项调用并记录真实返回，重点验证三个容易被想错的地方：参数校验失败**不会**抛异常而是走 `isError`、工具错误和协议错误是两条完全不同的通道、鉴权只能在传输层做而工具层拿到的只是已认证上下文。
>
> 环境：Node.js 24.19.0、`@modelcontextprotocol/sdk` 1.32.2、`zod` 4.6.7，传输层用 stdio 和 Streamable HTTP 两种。

## 1. 三类能力不是三种写法，是三个不同的东西

MCP 的服务端能力分成三类，很多人第一次看文档会以为它们只是「注册方式不同」，实际上它们的**调用主体**就不一样：

| | 谁发起调用 | 参数形态 | 返回形态 |
| --- | --- | --- | --- |
| tool | 模型（在对话里决定调用） | JSON Schema 校验的 `arguments` | `content` 块数组 + 可选 `structuredContent` |
| resource | 客户端（用户选中、或程序主动拉取） | URI 或 URI 模板变量 | `contents` 数组，带 `mimeType` |
| prompt | 用户（选中一个斜杠命令） | 一组简单命名参数 | `messages` 数组，直接是对话消息 |

这个区别决定了三件事：**tool 的 schema 要写给模型看**（描述要像给新同事解释），**resource 的 URI 要能寻址**（它是被引用的对象，不是被调用的函数），**prompt 的参数要少**（它面向人，不是面向模型推理）。

先看一个最小 server 的骨架：

```js
// 作用：一个 server 实例承载全部三类能力，注册完再接传输层
import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer({ name: "demo-notes", version: "1.0.0" });
```

## 2. tool：schema 是双向的

### 2.1. 注册一个带输入和输出 schema 的 tool

`registerTool` 的配置对象里，`inputSchema` 和 `outputSchema` 都用 zod 写，SDK 会转成 JSON Schema 下发。这里的关键是 **`outputSchema` 一旦声明，`structuredContent` 就必须匹配它**——这是 SDK 侧强制的，不是建议。

```js
// 作用：写入笔记；inputSchema 校验入参，outputSchema 约束结构化返回
server.registerTool(
  "add_note",
  {
    title: "新增笔记",
    description: "往内存笔记库里写一条，返回写入后的完整列表",
    inputSchema: {
      text: z.string().min(1).describe("笔记正文"),
      tag: z.enum(["work", "life"]).optional().describe("可选分类"),
    },
    outputSchema: {
      count: z.number(),
      notes: z.array(z.object({ text: z.string(), tag: z.string() })),
    },
  },
  async ({ text, tag }) => {
    notes.push({ text, tag: tag ?? "none" });
    const payload = { count: notes.length, notes };
    // content 给模型读的自然语言，structuredContent 给程序读的结构化数据
    return {
      content: [{ type: "text", text: `已写入，共 ${notes.length} 条` }],
      structuredContent: payload,
    };
  }
);
```

`description` 里的 `.describe()` 会变成 JSON Schema 的 `description` 字段，直接出现在 `tools/list` 的返回里——**模型看到的就是这个**，所以它是提示词的一部分，不是注释。

### 2.2. tools/list 实际返回了什么

跑一遍 `client.listTools()`，返回的 `add_note` 条目是这样：

```json
{
  "name": "add_note",
  "title": "新增笔记",
  "description": "往内存笔记库里写一条，返回写入后的完整列表",
  "inputSchema": {
    "type": "object",
    "properties": {
      "text": { "type": "string", "minLength": 1, "description": "笔记正文" },
      "tag": { "type": "string", "enum": ["work", "life"], "description": "可选分类" }
    },
    "required": ["text"],
    "$schema": "http://json-schema.org/draft-07/schema#"
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "count": { "type": "number" },
      "notes": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": { "text": { "type": "string" }, "tag": { "type": "string" } },
          "required": ["text", "tag"],
          "additionalProperties": false
        }
      }
    },
    "required": ["count", "notes"],
    "$schema": "http://json-schema.org/draft-07/schema#",
    "additionalProperties": false
  },
  "execution": { "taskSupport": "forbidden" }
}
```

几个值得注意的细节：

- `$schema` 是 **draft-07**，不是最新版；
- `outputSchema` 自动加了 `additionalProperties: false`，而 `inputSchema` 没有——输出是严格的，输入是宽松的；
- 多出一个 `execution.taskSupport: "forbidden"`，这是 SDK 1.32 引入的异步任务能力标记，普通 tool 默认不支持长任务。

### 2.3. 调用成功时返回什么

```json
{
  "content": [{ "type": "text", "text": "已写入，共 2 条" }],
  "structuredContent": {
    "count": 2,
    "notes": [
      { "text": "先跑通 stdio", "tag": "work" },
      { "text": "写一篇 MCP server", "tag": "work" }
    ]
  }
}
```

`content` 和 `structuredContent` 是**两套并行**的表示，不是二选一。老客户端只读 `content`，新客户端可以只读 `structuredContent`，两者必须说同一件事。

## 3. 错误边界：三种「错」，两条通道

这是实测里最反直觉的部分。我原以为三种错误会走三条路，实际上只有两条。

### 3.1. 工具内部错误：`isError: true`

业务上失败（比如下标越界），**不要抛异常**，而是返回带 `isError` 的结果：

```js
// 作用：越界时返回工具错误，让模型看见原因并自行纠正
if (index >= notes.length) {
  return {
    isError: true,
    content: [{ type: "text", text: `下标越界：当前只有 ${notes.length} 条` }],
  };
}
```

实测返回：

```json
{
  "content": [{ "type": "text", "text": "下标越界：当前只有 2 条" }],
  "isError": true
}
```

关键在于**这是「成功」的 JSON-RPC 响应**。协议层没出错，模型能完整读到错误文本，然后自己换个参数重试。这是设计意图：工具失败是正常业务流的一部分。

### 3.2. 参数校验失败：也是 `isError`，不是异常

我以为传一个违反 `z.number().int().min(0)` 的 `-1` 会抛异常，或者至少返回一个 JSON-RPC `error`。实测结果：

```text
没抛异常，返回： {"content":[{"type":"text","text":"MCP error -32602: Input validation error: Invalid arguments for tool get_note: Too small: expected number to be >=0 at index"}],"isError":true}
```

缺必填参数也一样：

```text
缺参没抛，返回： {"content":[{"type":"text","text":"MCP error -32602: Input validation error: Invalid arguments for tool add_note: Invalid input: expected string, received undefined at text"}],"isError":true}
```

**schema 校验失败被 SDK 包装成了工具错误**，文本里嵌了 `-32602`（标准的 Invalid params 错误码），但外层仍然是 `isError: true` 的结果对象。

这个设计的实际影响是：客户端不能靠「有没有异常」来判断参数错，必须读 `isError`；而且 `-32602` 这个码只在文本里，程序化判断得去正则匹配。如果你的 agent 框架依赖抛异常来做重试，这里会静默失败。

### 3.3. 真正的协议错误：JSON-RPC `error`

只有当请求本身不合法（方法不存在、JSON 解析失败、会话头缺失）时，才会走到 JSON-RPC 的 `error` 通道。比如 HTTP 版本里不带会话头：

```json
{"jsonrpc":"2.0","error":{"code":-32000,"message":"Bad Request: Mcp-Session-Id header is required"},"id":null}
```

所以错误处理只有两条通道：

```text
业务失败 + 参数非法  →  结果对象 isError: true（协议层成功）
请求本身非法        →  JSON-RPC error（协议层失败）
```

## 4. resource：静态 URI 和模板 URI

### 4.1. 静态资源

```js
// 作用：一个固定 URI 的资源，客户端主动读，模型不参与
server.registerResource(
  "notes-index",
  "notes://index",
  { title: "笔记索引", description: "当前笔记库的元信息", mimeType: "application/json" },
  async (uri) => ({
    contents: [
      {
        uri: uri.href,
        mimeType: "application/json",
        text: JSON.stringify({ count: notes.length, tags: ["work", "life"] }),
      },
    ],
  })
);
```

`resources/list` 返回：

```json
{
  "resources": [
    {
      "name": "notes-index",
      "title": "笔记索引",
      "uri": "notes://index",
      "description": "当前笔记库的元信息",
      "mimeType": "application/json"
    }
  ]
}
```

注意：**`resources/list` 里没有内容**，只有元信息。内容要单独 `readResource` 才拿得到。这和 tool 不同——tool 的 schema 在 list 阶段就全给了。

### 4.2. 模板资源

带变量的 URI 用 `ResourceTemplate`，它会出现在另一个列表接口里：

```js
// 作用：URI 模板，客户端用具体下标替换 {index}
server.registerResource(
  "note-by-index",
  new ResourceTemplate("notes://note/{index}", { list: undefined }),
  { title: "按标读取笔记", mimeType: "application/json" },
  async (uri, { index }) => ({
    contents: [
      {
        uri: uri.href,
        mimeType: "application/json",
        text: JSON.stringify(notes[Number(index)] ?? null),
      },
    ],
  })
);
```

`resources/templates/list` 返回：

```json
{
  "resourceTemplates": [
    {
      "name": "note-by-index",
      "title": "按标读取笔记",
      "uriTemplate": "notes://note/{index}",
      "mimeType": "application/json"
    }
  ]
}
```

**两个列表是两个接口**：静态资源在 `resources/list`，模板在 `resources/templates/list`。客户端要支持模板，两个都得调。`{ list: undefined }` 的意思是「这个模板不提供可枚举的实例列表」——如果给了 `list` 回调，客户端就能列出所有具体实例。

读取时 `index` 是字符串，`notes[Number(index)]` 这个转换必须自己写，SDK 不做类型推断。

## 5. prompt：给用户的，不是给模型的

```js
// 作用：带一个可选参数的提示模板，客户端取走后直接塞进对话
server.registerPrompt(
  "summarize_notes",
  {
    title: "总结笔记",
    description: "把当前笔记喂给模型做总结",
    argsSchema: { style: z.enum(["brief", "detailed"]).optional() },
  },
  ({ style }) => ({
    messages: [
      {
        role: "user",
        content: {
          type: "text",
          text: `请用${style === "detailed" ? "详细" : "简洁"}的方式总结以下笔记：\n` +
            notes.map((n, i) => `${i}. [${n.tag}] ${n.text}`).join("\n"),
        },
      },
    ],
  })
);
```

`prompts/list` 返回的参数声明**比 tool 简得多**，只有名字和是否必填：

```json
{
  "prompts": [
    {
      "name": "summarize_notes",
      "title": "总结笔记",
      "description": "把当前笔记喂给模型做总结",
      "arguments": [{ "name": "style", "required": false }]
    }
  ]
}
```

注意这里**没有 enum**。`argsSchema` 里的 `z.enum(["brief","detailed"])` 在 `prompts/list` 里被压成了 `{name, required}`，客户端拿不到取值范围。所以 prompt 参数的约束只能靠 server 端校验 + description 里写清楚。

取回来的结果就是标准消息数组：

```json
{
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "请用简洁的方式总结以下笔记：\n0. [work] 先跑通 stdio\n1. [work] 写一篇 MCP server"
      }
    }
  ]
}
```

这就是 prompt 的本质：**它是一个服务端的字符串模板函数**，返回值直接进对话上下文。模型不「调用」它，是用户在客户端里选它。

## 6. 鉴权只能在传输层做

这是三类能力之外的第四个边界，也是最容易做错的一个。

### 6.1. HTTP 版本：401 挡在协议层之外

```js
// 作用：鉴权放在传输层，非法请求进不到 MCP 协议层
const http = createServer(async (req, res) => {
  if (req.headers.authorization !== `Bearer ${TOKEN}`) {
    res.writeHead(401, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "unauthorized" }));
    return;
  }
  // 合法请求补上 authInfo 给工具层
  req.auth = { token: TOKEN, clientId: "demo", scopes: ["read"] };
  await transport.handleRequest(req, res);
});
```

实测：不带 token 的 `initialize` 直接 `401`，连 JSON-RPC 都没进去。

### 6.2. 工具层拿到的是什么

工具回调的第二个参数 `extra` 里只有 `authInfo`：

```js
// 作用：工具层只能看到已认证的上下文，看不到原始 HTTP 头
mcp.registerTool("whoami", { description: "返回鉴权上下文里的用户", inputSchema: {} },
  async (_args, extra) => ({
    content: [{ type: "text", text: JSON.stringify({ authInfo: extra.authInfo ?? null }) }],
  })
);
```

实测调用返回：

```json
{"authInfo":{"token":"demo-token","clientId":"demo","scopes":["read"]}}
```

**工具层拿不到 `Authorization` 头，也拿不到原始请求。** 它只能看到传输层愿意透传的 `authInfo`。这是刻意的边界：MCP 把「你是谁」的判定完全交给传输层，工具层只负责「你被允许做什么」。

SDK 源码里这个透传点很明确，`webStandardStreamableHttp.js` 里三次 `onmessage` 调用都带 `authInfo: options?.authInfo`。也就是说，**如果传输层没设 `authInfo`，工具层永远是 `undefined`**——不会报错，只会静默地认为你没身份。

## 7. 一个 server 实例只能 initialize 一次

实测中我起了 HTTP 服务后，用第二个 curl 再发一次 `initialize`，得到：

```json
{"jsonrpc":"2.0","error":{"code":-32600,"message":"Invalid Request: Server already initialized"},"id":null}
```

对应 SDK 源码 `webStandardStreamableHttp.js` 里这段：

```js
// 作用：已初始化且有会话 ID 时，拒绝重复初始化
if (this._initialized && this.sessionId !== undefined) {
    this.onerror?.(new Error('Invalid Request: Server already initialized'));
    return this.createJsonErrorResponse(400, -32600, 'Invalid Request: Server already initialized');
}
```

**一个 transport 实例 = 一个会话。** 要支持多客户端，必须每个会话新建一对 `McpServer` + `StreamableHTTPServerTransport`，靠 `onsessioninitialized` 回调把它们存进 map。我上面那个 demo 只建了一个全局 transport，所以第二个客户端进不来——这不是 bug，是用法错了。

正确的多会话骨架：

```js
// 作用：每个会话一对 server + transport，按 sessionId 存起来
const sessions = new Map();

function createSession() {
  const mcp = new McpServer({ name: "demo", version: "1.0.0" });
  registerAll(mcp);   // 注册同一套能力
  const t = new StreamableHTTPServerTransport({
    sessionIdGenerator: () => randomUUID(),
    onsessioninitialized: (sid) => sessions.set(sid, { mcp, t }),
  });
  mcp.connect(t);
  return t;
}
```

## 8. 常见坑

1. **参数校验失败不抛异常**。`z.number().min(0)` 收到 `-1` 时返回的是 `isError: true` 的结果，`-32602` 只在文本里。靠 try/catch 判断参数错的代码会静默失效。
2. **`outputSchema` 声明了就强制校验**。`structuredContent` 不匹配会直接失败，而 `content` 不会被校验——两套表示必须自己保证一致。
3. **`resources/list` 和 `resources/templates/list` 是两个接口**。只调第一个，模板资源就永远发现不了。
4. **`prompts/list` 丢失参数约束**。`z.enum` 在列表里退化成 `{name, required}`，取值范围得靠 description 或服务端校验。
5. **鉴权不透传就永远没有身份**。传输层不设 `authInfo`，工具层的 `extra.authInfo` 就是 `undefined`，且不会报错。
6. **一个 transport 只能 initialize 一次**。多客户端要每会话新建一对 server + transport，别复用全局实例。
7. **`mimeType` 是给客户端的提示，不是强制**。服务端返回什么由你自己决定，SDK 不校验。

## 9. 重点总结

**三类能力的本质区别在调用主体，不在写法：**

- **tool** 由模型决定调用，schema 是提示词的一部分，`inputSchema` 宽松、`outputSchema` 严格；
- **resource** 由客户端按 URI 拉取，元信息和内容分两个接口，静态与模板分两个列表；
- **prompt** 由用户选择，本质是服务端的字符串模板函数，参数约束在列表阶段就丢了。

**实测出来的三条硬结论：**

1. **错误只有两条通道**：业务失败和参数非法都走 `isError: true` 的「成功响应」，只有请求本身非法才走 JSON-RPC `error`。`-32602` 被包在文本里，程序化判断得靠解析。
2. **鉴权边界在传输层**，工具层只拿得到 `authInfo`，拿不到原始请求头；传输层不透传就是 `undefined`，静默无身份。
3. **一个 transport 实例只能承载一个会话**，重复 `initialize` 返回 `400 / -32600`；多客户端必须每会话一对实例。

写 MCP server 时最省事的习惯是：**先把 tool 的 description 当产品文案写**（模型只看这个），**把 `isError` 当正常返回值用**（不要抛异常），**把鉴权挡在 `handleRequest` 之前**（不要指望工具层校验）。

## 10. 参考

- [MCP 2025-11-25 规范 · Server Features](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)（tools / resources / prompts 三类能力的协议定义）
- [`@modelcontextprotocol/sdk` 1.32.2](https://www.npmjs.com/package/@modelcontextprotocol/sdk)（`McpServer.registerTool` / `registerResource` / `registerPrompt`、`StreamableHTTPServerTransport`）
- SDK 源码 `dist/esm/server/webStandardStreamableHttp.js`（重复初始化的 `-32600` 判定、`authInfo` 透传点）
- 实测工程：Node.js 24 + SDK 1.32.2 + zod 4.6.7，stdio server/client 与 Streamable HTTP 版本，原始输出见正文
