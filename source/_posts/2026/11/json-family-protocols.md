---
title: JSON 的五种变体：JSONL、JSONC、JSON5、二进制编码与 json2
date: 2026-11-17 22:30:00
description: 严格 JSON 之外，工程里还会遇到五类变体：结构变体 JSONL、语法扩展 JSONC 与 JSON5、二进制编码 JSONB/BSON/CBOR、以及已淘汰的历史库 json2。按「它改了什么、为什么存在、今天还用不用」逐个讲清。
categories:
  - 概念
tags:
  - JSON
  - 技术辨析
cover: /img/2026/11/json-family-protocols.jpg
---

RFC 8259 定义的 JSON 只有一种：文本、双引号、无注释、无尾逗号。但工程里遇到的「JSON」远不止一个名字——JSONL、JSONC、JSON5、JSONB、BSON、CBOR、json2……它们不是同一个东西的不同叫法，而是围绕 JSON 的五类变体。这篇按「**它改了什么、为什么存在、今天还用不用**」逐个讲清楚。

## 1. 一、JSONL：结构变体

JSONL（JSON Lines）不改变 JSON 的语法，只改变**组织方式**：每一行是一个独立、合法的 JSON 对象，行之间用换行分隔。

```text
{"id":1,"event":"login","ts":"2026-11-18T10:00:00Z"}
{"id":2,"event":"query","ts":"2026-11-18T10:00:03Z"}
{"id":3,"event":"logout","ts":"2026-11-18T10:05:12Z"}
```

它和「一个 JSON 数组」的区别是结构性的：

- 数组必须整体解析，末尾多一个逗号就全废；
- JSONL 可以**逐行追加、逐行解析**，坏行只影响自己；
- 读取方不需要把整个文件载入内存。

所以它天然适合**日志、流式数据、大数据集**——应用日志、模型批量推理的输入输出、会话记录（Pi 的会话日志就是一行一条 entry）都是这个形态。读法就是按行 `JSON.parse`/`json.loads`，注意空行和末尾无换行两种情况。

## 2. 二、JSONC：语法扩展（注释）

JSONC 是 VS Code 的 JSON 方言：在严格 JSON 基础上允许**注释**（部分工具还允许尾逗号）。

```jsonc
{
  // 编译目标
  "target": "ES2022",
  "strict": true, /* 打开严格模式 */
}
```

它没有正式的 RFC，规范事实上由 VS Code 的 `jsonc-parser` 定义。用途很明确：**配置文件**——`tsconfig.json`、`.vscode/settings.json`、`devcontainer.json` 这些由人维护、需要写注释的文件。

边界也只有一条：**JSONC 是给人写的，不是给机器传的**。读进来之后要转成严格 JSON 再交给 `JSON.parse` 或任何外部系统——浏览器和 Node 的原生解析器都不认注释。

## 3. 三、JSON5：语法扩展（宽松语法）

JSON5 是更彻底的「人类友好版 JSON」，同样是严格 JSON 的超集：

- 允许注释和尾逗号；
- 键可以不加引号，字符串可以用单引号；
- 支持十六进制数字、`+` 号、省略整数位的 `.5`、多行字符串。

```json5
{
  // 手写配置
  name: 'demo',
  version: '1.0.0',
  retries: 3,
  timeout: 0x1F4,        // 500ms，十六进制
}
```

和 JSONC 的区别：**JSONC 是编辑器方言（只放开注释/尾逗号），JSON5 是一份完整规范**（json5.org），有独立的解析库。用途也类似——**手写配置**，比如 Babel、部分构建工具和测试夹具。

使用时同样要注意：JSON5 的宽松只在「人写」这一侧；跨系统交换仍然要用严格 JSON。

## 4. 四、二进制编码：JSONB / BSON / CBOR

前三类是文本变体，这一类的共同点是**二进制编码**：把 JSON 的树结构按二进制存，追求**高效、紧凑、支持二进制数据**，用在**底层传输/存储**。常见的三个代表：

- **JSONB**：PostgreSQL 的内部二进制 JSON 类型（无公开规范），写入时解析重组，可建 GIN 索引；SQLite 3.45+ 也有公开文档的 JSONB 格式。代价是键顺序丢失、重复键去重、不可直接读文本。
- **BSON**：MongoDB 的文档格式（bsonspec.org），长度前缀 + 扩展类型（日期、ObjectId、二进制），为数据库读写和遍历优化。
- **CBOR**：IETF 标准（RFC 8949），与 JSON 数据模型兼容的二进制表示，支持标签和确定性编码，常用于 IoT、CoAP 等受限环境。

```sql
-- PostgreSQL：jsonb 可索引、可查询
SELECT payload->>'event' FROM events WHERE payload @> '{"event":"login"}';
```

这一类换来的是性能与表达力（二进制数据、索引、类型），付出的是**可读性和工具成本**——调试时要先转回文本。

## 5. 五、json2：历史库

`json2.js` 是 Douglas Crockford 在 2009 年前后发布的兼容库，作用是**给老浏览器补上 `JSON.parse` / `JSON.stringify`**——在 IE7 及更早的浏览器里，`JSON` 对象根本不存在，只能靠这个库的 `JSON.parse`/`stringify` 实现。

它属于历史产物：IE8 起浏览器内置原生 `JSON`，现代浏览器和 Node 全部内置。今天**不应再引入 json2**，见到就删——它既慢，又可能在原生实现存在时造成行为差异。

它的历史意义大于技术价值：它见证了 JSON 从「JavaScript 的对象字面量」变成「标准交换格式」的过渡期。

## 6. 六、五种变体对照

| 名称 | 类别 | 形态 | 典型用途 | 状态 |
| --- | --- | --- | --- | --- |
| JSONL | 结构变体 | 文本，每行一个独立对象 | 日志、流式数据、大数据集 | 活跃 |
| JSONC | 语法扩展 | 文本，允许注释 | 配置文件（VS Code） | 活跃（编辑器生态） |
| JSON5 | 语法扩展 | 文本，宽松语法 | 手写配置 | 活跃（解析库） |
| JSONB / BSON / CBOR | 二进制编码 | 二进制 | 底层传输 / 存储 | 活跃 |
| json2 | 历史库 | JavaScript 库 | 老浏览器 JSON 垫片 | 已淘汰 |

## 7. 七、怎么选

- **日志、流式、大数据集** → JSONL；
- **要写注释的配置文件** → JSONC（VS Code 系）或 JSON5（需要更宽松语法时）；
- **高频读写、要索引、要传二进制** → JSONB / BSON / CBOR；
- **见到 json2** → 删掉，用原生 `JSON`。

一句话：**JSONL 改的是「怎么排列」，JSONC/JSON5 改的是「怎么写」，二进制编码改的是「怎么存」，json2 是「怎么在没有 JSON 的环境里假装有 JSON」。**

## 8. 重点总结

- JSONL 是结构变体：每行一个独立 JSON 对象，可追加、可逐行解析，适合日志与大数据集。
- JSONC 与 JSON5 是语法扩展：前者是 VS Code 的注释方言，后者是完整的宽松语法规范；都只用于人写的配置，传递前要转严格 JSON。
- JSONB / BSON / CBOR 是二进制编码：紧凑、可索引、支持二进制数据，用于底层存储与传输，代价是可读性与工具成本。
- json2 是历史库：为老浏览器补 `JSON`，原生普及后已淘汰。
- 变体再多，交换层的铁律不变：**跨系统传输用严格 JSON**。

## 9. 参考

- [RFC 8259：JSON 数据交换格式](https://www.rfc-editor.org/rfc/rfc8259)
- [JSON Lines](https://jsonlines.org/)
- [JSON5](https://json5.org/)
- [BSON 规范](https://bsonspec.org/)
- [RFC 8949：CBOR](https://www.rfc-editor.org/rfc/rfc8949)
- [PostgreSQL：JSON 类型](https://www.postgresql.org/docs/current/datatype-json.html)
- [json2（Douglas Crockford）](https://github.com/douglascrockford/JSON-js)
