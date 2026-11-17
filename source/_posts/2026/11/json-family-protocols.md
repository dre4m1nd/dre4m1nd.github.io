---
title: JSON 家族辨析：JSON、JSONL、JSON-RPC、JSON Schema、JSON Patch 到底差在哪
date: 2026-11-17 22:30:00
slug: json-family-protocols
description: 一份把 JSON 家族讲清楚的对照笔记：JSON 是格式，JSONL 是流，JSON-RPC 才是协议，JSON Schema 是词汇表，JSON Pointer 是地址，JSON Patch 与 Merge Patch 是两种修改单。附选择决策表与七个常见误区。
categories:
  - 概念
tags:
  - JSON
  - 技术辨析
cover: /img/2026/11/json-family-protocols.jpg
---

「JSON 协议」这个词，几乎每天都会在项目里被用到，但十有八九指的不是同一件东西：有人指的是数据格式，有人指的是按行切分的日志，有人指的是 JSON-RPC 调用，有人指的是参数校验。这篇文章把这一家族摆在一起，按「本质」分成六类：**格式、超集、流、协议、词汇表、地址与补丁**。分清之后，选型、排错和面试都会轻松很多。

## 一、先给全家拍张合影

| 名字 | 规范 | 本质 | 解决什么问题 | 典型场景 |
| --- | --- | --- | --- | --- |
| JSON | RFC 8259 | 数据交换格式 | 表达结构化数据 | API 响应、配置文件 |
| JSON5 / JSONC | json5.org / VS Code | 人类可写的 JSON 超集 | 让配置能写注释 | `tsconfig.json`、编辑器设置 |
| JSONL / NDJSON | jsonlines.org / ndjson.org | 行分隔的 JSON 流 | 追加写、逐行处理 | 日志、批量数据、会话记录 |
| JSON-RPC 2.0 | jsonrpc.org | 远程调用协议 | 调方法并拿结果 | MCP、LSP、以太坊节点 |
| JSON Schema | draft 2020-12 | 结构校验词汇表 | 描述并校验 JSON 形状 | 工具参数、表单校验 |
| JSON Pointer | RFC 6901 | 寻址语法 | 指向文档中的某个节点 | Patch 的 `path` 字段 |
| JSON Patch | RFC 6902 | 修改格式 | 精确增量更新 | `PATCH` 请求 |
| JSON Merge Patch | RFC 7386 | 修改格式 | 简单合并覆盖 | `PATCH` 请求 |
| JSON:API | jsonapi.org | REST 资源约定 | 标准化资源接口 | 内容型 API |

一句话记忆：**JSON 是「名词」，JSONL 是「排版」，JSON-RPC 是「电话」，JSON Schema 是「合同模板」，JSON Pointer 是「地址」，Patch 是「修改单」。** 它们共享同一套基础语法，但职责完全不同——只有 JSON-RPC 和 JSON:API 能叫「协议」。

## 二、逐个看边界

### 1. JSON：只是数据格式，不是协议

RFC 8259 定义的 JSON 是一种**数据交换格式**。它规定值怎么拼：对象、数组、字符串、数字、布尔和 `null`。严格规则值得背下来：

- 字符串必须用双引号，键也必须是字符串；
- 没有注释，没有尾逗号；
- 数字不规定精度（这是后面「大整数要用字符串」的根源）；
- 文档编码是 UTF-8，规范建议实现忽略 BOM。

它和 HTTP、WebSocket 是两层东西：协议负责「怎么传」，JSON 负责「传的内容长什么样」。所以「设计一个 JSON 协议」这个说法通常不准确——你设计的是**基于 JSON 载荷的应用协议**。

```json
{
  "id": 42,
  "name": "示例",
  "tags": ["a", "b"],
  "nested": { "ok": true }
}
```

### 2. JSON5 / JSONC：写的时候宽松，传的时候严格

JSON5 是 JSON 的超集：支持注释、尾逗号、单引号、不带引号的键、十六进制数字、多行字符串。JSONC 是 VS Code 的方言，只放了注释和尾逗号，常见于编辑器配置。两者的边界只有一条：**它们是给人写的，不是给机器传的。** 任何要发给外部系统的载荷，都应先转回严格 JSON；`JSON.parse` 不认注释，别把配置文件的写法带进 API 请求。

### 3. JSONL / NDJSON：一行一个值

JSON Lines（jsonlines.org）与 NDJSON（ndjson.org）本质是同一件事：**每一行是一个独立的、合法的 JSON 值，行之间用 `\n` 分隔。**

```text
{"type":"session","id":"abc"}
{"type":"message","id":"a1","parentId":null}
{"type":"message","id":"b2","parentId":"a1"}
```

它和「一个 JSON 数组」的区别是结构性的：

- 数组必须整体解析，末尾多一个逗号就全废；
- JSONL 可以**逐行追加、逐行解析**，坏行只影响自己，天然适合日志与流式处理；
- 读取方不需要把整个文件载入内存。

会话日志、模型批量推理输入、埋点数据都是这个格式。判断标准很简单：数据会不会**持续追加**、会不会**很大**——会，就用 JSONL。

### 4. JSON-RPC 2.0：真正意义上的协议

JSON-RPC 2.0 是这一家里唯一「正统」的 RPC 协议。它规定三种消息形态：

- **请求**：必须带 `id`、`method`、可选 `params`；
- **响应**：必须带与请求相同的 `id`，并且 `result` 与 `error` 二选一；
- **通知**：**不带 `id`**，对端不回复。

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
{"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
```

标准错误码要认得：`-32700` 解析错误、`-32600` 请求无效、`-32601` 方法不存在、`-32602` 参数无效、`-32603` 内部错误。几个容易被忽略的细节：

- `id` 由客户端生成，服务端必须原样带回；通知**不能**有 `id`，否则会被当成请求并期待响应；
- 批量请求是「请求数组」，但通知混在批量里时同样不回复；
- 协议本身与传输层解耦：stdio、HTTP、WebSocket 都能承载。

MCP（Model Context Protocol）就是典型例子：stdio 模式下**每行一个 JSON-RPC 消息**，`initialize`、`tools/list`、`tools/call` 全是标准 JSON-RPC 方法。LSP 同理。了解这条，调试 MCP 服务器时直接抓标准输入输出即可。

### 5. JSON Schema：描述「长什么样」，不承载数据

JSON Schema 是一套**校验词汇表**，本身也是一个 JSON 文档。它回答的问题是「这份数据合法吗」，而不是「这份数据是什么」。

```json
{
  "type": "object",
  "properties": {
    "path": { "type": "string" },
    "content": { "type": "string" }
  },
  "required": ["path"],
  "additionalProperties": false
}
```

它广泛用在工具参数定义（OpenAI function calling 用的是它的子集，MCP 的 `inputSchema` 也是它）、配置校验和表单生成。**它不是协议，也不负责传输**——把它当成「合同模板」最贴切：模板本身不是货物。

### 6. JSON Pointer：一个字符串地址

RFC 6901 定义了一种指向 JSON 文档内部节点的**字符串语法**：空串表示整个文档，`/foo/0/bar` 表示「键 `foo` 的数组第 0 项里的键 `bar`」。两个转义规则必须记住：`~1` 表示 `/`，`~0` 表示 `~`（顺序不能反）。

```text
/users/0/name          → 第一个用户的 name
/a~1b                  → 键名为 "a/b" 的字段
```

JSON Patch 的 `path`、`from`，JSON:API 的关系路径，以及各类「用路径定位错误字段」的错误响应，用的都是这套语法。它只是地址，不带任何操作语义。

### 7. JSON Patch / JSON Merge Patch：两种「修改单」

两者都用于增量更新，但语义完全不同。

**JSON Patch（RFC 6902）** 是一个操作数组，支持 `add`、`remove`、`replace`、`move`、`copy`、`test` 六种操作：

```json
[
  { "op": "replace", "path": "/name", "value": "新名字" },
  { "op": "test", "path": "/version", "value": 3 },
  { "op": "add", "path": "/tags/-", "value": "c" }
]
```

它的隐含要求是**原子性**：任一操作失败（尤其是 `test` 不通过），整个补丁都不生效。`test` 操作因此可以当作乐观锁使用。

**JSON Merge Patch（RFC 7386）** 则简单得多：补丁的形状与目标一致，逐键合并；**值为 `null` 表示删除该键**。

```json
{ "name": "新名字", "tags": null }
```

代价是它无法表达「把某个键设成 `null`」与「删除这个键」的区别——这两件事在 Merge Patch 里是同一个意思。需要精确控制就用 JSON Patch，只需要「改几个字段」就用 Merge Patch。

### 8. JSON:API：顺带一提的 REST 约定

JSON:API 是 HTTP API 的**设计规范**（资源、关系、分页、错误格式都做了约定），不是传输协议，也不定义新语法。它和 JSON-RPC 的区别是风格：一个面向资源，一个面向方法调用。

## 三、怎么选：决策表与七个常见误区

按需求直接对号入座：

| 你要做的事 | 用什么 |
| --- | --- |
| 传一份结构化数据 | JSON（严格） |
| 写配置文件 | JSONC / JSON5，读入后转严格 JSON |
| 记日志、做流式追加 | JSONL / NDJSON |
| 调远端方法、要请求响应 | JSON-RPC 2.0 |
| 描述参数、做校验 | JSON Schema |
| 定位文档里的某个字段 | JSON Pointer |
| 精确增量修改 | JSON Patch |
| 简单合并几个字段 | JSON Merge Patch |

七个高频误区：

1. **把 JSON Schema 当协议。** 它只描述形状，不传输、不调用。
2. **把 JSONL 交给 `JSON.parse` 整体解析。** 它必须逐行解析；空行与末尾换行都要单独处理。
3. **给通知加了 `id`。** 加了就变成请求，对端会等你的响应，或者回一个你不需要的响应。
4. **JSON Patch 的索引漂移。** 先 `remove` 数组元素再按旧索引操作会错位；`add` 到数组末尾要用 `/-`。
5. **Merge Patch 的 `null` 歧义。** 想「设空」却变成了「删除」。需要区分就换 JSON Patch。
6. **数字精度。** JSON 不规定数字精度，JavaScript 只有 double，`9007199254740993` 这类整数会失真；跨语言传输大整数请用字符串。
7. **转义顺序。** JSON Pointer 里先 `~` 后 `/`（即 `~0`、`~1`），反了就解析不回来。

## 重点总结

- JSON 是**数据格式**；JSON5 / JSONC 是它的宽松书写超集；JSONL / NDJSON 是行分隔的流。
- JSON-RPC 2.0 是**协议**：请求带 `id`、响应回同 `id`、通知不带 `id`，标准错误码 5 个，传输层无关（MCP、LSP 都在用）。
- JSON Schema 是**校验词汇表**，描述形状不承载数据；JSON Pointer 是**地址语法**；JSON Patch / Merge Patch 是两种**修改单**（精确 vs 简单）。
- 选型口诀：传数据用 JSON，记日志用 JSONL，调方法用 JSON-RPC，描述参数用 Schema，定位用 Pointer，改文档用 Patch。
- 最容易踩的坑集中在三处：JSONL 当数组解析、通知带 `id`、大整数精度。

## 参考

- [RFC 8259：JSON 数据交换格式](https://www.rfc-editor.org/rfc/rfc8259)
- [RFC 6901：JSON Pointer](https://www.rfc-editor.org/rfc/rfc6901)
- [RFC 6902：JSON Patch](https://www.rfc-editor.org/rfc/rfc6902)
- [RFC 7386：JSON Merge Patch](https://www.rfc-editor.org/rfc/rfc7386)
- [JSON-RPC 2.0 规范](https://www.jsonrpc.org/specification)
- [JSON Lines](https://jsonlines.org/)
- [NDJSON](https://github.com/ndjson/ndjson-spec)
- [JSON5](https://json5.org/)
- [JSON Schema](https://json-schema.org/)
- [JSON:API](https://jsonapi.org/)
