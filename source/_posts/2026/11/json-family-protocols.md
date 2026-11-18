---
title: JSONL 与 JSONB：同一个 JSON，文本流和二进制存储的差别
date: 2026-11-17 22:30:00
description: 同一条会话记录，写进日志文件（JSONL）和写进数据库（PostgreSQL/SQLite 的 JSONB）之后有什么不同？从逐行追加、坏行隔离，到二进制存储、键去重与 GIN 索引，讲清两种 JSON 存储形态的分工与取舍。
categories:
  - 概念
tags:
  - JSON
  - JSONB
cover: /img/2026/11/json-family-protocols.jpg
---

同一条会话记录，写到不同的地方，命运完全不同：写进日志文件，它是一行文本，`grep` 就能翻；写进数据库的 `jsonb` 列，它变成了一段二进制，能建索引、能按字段查询，但你再也读不到原来的键顺序。这篇文章就讲这两条路——**JSONL 和 JSONB**，以及它们各自适合的场景。

## 1. 一、引子：同一条记录，两种存法

一条会话记录，先看它在日志文件里的样子：

```json
{"id":"b2","parentId":"a1","role":"assistant","content":"好的","ts":"2026-11-17T10:02:00Z"}
```

它单独占一行，前后还排着别的记录。再看它进了 PostgreSQL 的表：

```sql
CREATE TABLE messages (
  id   bigserial PRIMARY KEY,
  data jsonb                   -- 二进制存储，可查询、可索引
);
INSERT INTO messages (data)
VALUES ('{"id":"b2","parentId":"a1","role":"assistant","content":"好的","ts":"2026-11-17T10:02:00Z"}');
```

同样的内容，一个还能拿 `grep`/`tail` 直接看，一个已经变成二进制、只能通过 SQL 访问。这不是实现细节的差别，而是**两种存储形态的分工**。

## 2. 二、JSONL：一行一个值的流

JSONL（JSON Lines，jsonlines.org）和 NDJSON（ndjson.org）本质是同一件事：**每一行是一个独立、合法的 JSON 值，行之间用换行分隔。**

```text
{"type":"message","id":"a1","parentId":null,"role":"user","content":"..."}
{"type":"message","id":"b2","parentId":"a1","role":"assistant","content":"..."}
{"type":"tool_result","id":"c3","parentId":"b2","content":"..."}
```

它和「一个 JSON 数组」的区别是结构性的：

- 数组必须整体解析，末尾多一个逗号就全废；
- JSONL 可以**逐行追加、逐行解析**，坏行只影响自己，天然适合日志与流式处理；
- 读取方不需要把整个文件载入内存。

所以它常出现在三类地方：应用日志、模型批量推理的输入输出、会话记录（比如 Pi 的会话日志就是一行一条 entry）。

逐行读的写法也很直白：

```python
import json

with open("session.jsonl", encoding="utf-8") as f:
    for line in f:                      # 逐行读取，内存里只保留当前行
        line = line.strip()
        if not line:                    # 跳过空行
            continue
        rec = json.loads(line)          # 每行独立解析，坏行只影响这一条
        print(rec["type"])
```

这里有两个容易踩的坑：**不要用 `JSON.parse` 读整个文件**（它不是合法 JSON），以及**最后一行可能没有换行符**——按行读时通常没问题，但自己切分时要注意补上判断。

## 3. 三、JSONB（PostgreSQL）：可查询的二进制

PostgreSQL 有两个 JSON 类型：`json` 和 `jsonb`。名字只差一个字母，行为差很多。

- **`json`**：原样保存文本，保留空格、键顺序、重复键；写入快，但**不能建 GIN 索引**，查询每次都要重新解析。
- **`jsonb`**：写入时解析成二进制、按键重组；**键顺序丢失、重复键只保留最后一个**；支持 GIN 索引和全套查询运算符，读写性能更均衡。

```sql
-- 重复键：jsonb 只保留最后一个
SELECT '{"a":1,"a":2}'::jsonb;        -- {"a": 2}

-- 键顺序：jsonb 不保证原样
SELECT '{"b":1,"a":2}'::jsonb::text;  -- {"a": 2, "b": 1}

-- 取字段：-> 返回 json，->> 返回文本
SELECT data->'role', data->>'content' FROM messages;

-- 包含查询（走 GIN 索引）
SELECT * FROM messages WHERE data @> '{"role":"assistant"}';

CREATE INDEX idx_messages_data ON messages USING gin (data);
```

什么时候用 `jsonb`？**字段不固定、但又需要按字段查询**的数据——事件、配置快照、第三方回调。什么时候不该用？当这些字段其实很稳定、而且经常参与连接和聚合时，拆成真正的列（或子表）性能更好、约束也更清楚——`jsonb` 更像是「有查询能力的文本」，不是「不用设计表结构的借口」。

## 4. 四、JSONB（SQLite）：3.45+ 的二进制格式

SQLite 从 3.45.0 开始也引入了 JSONB——一个**有公开文档的二进制 JSON 格式**。它和 PostgreSQL 的 jsonb 思路一致：内部用二进制存储，解析更快、可按路径遍历；区别是 SQLite 的格式是公开的，而且提供了两个显式转换函数：

```sql
-- 文本 JSON → JSONB 二进制
SELECT jsonb('{"a":1,"b":[2,3]}');

-- JSONB → 文本（用于展示或导出）
SELECT json('{"a":1}'::blob);

CREATE TABLE kv (k TEXT PRIMARY KEY, v BLOB);          -- 存 JSONB
INSERT INTO kv VALUES ('x', jsonb('{"a":1}'));

SELECT json_extract(v, '$.a') FROM kv;                 -- 函数可直接读 JSONB
SELECT v ->> '$.b[0]' FROM kv;
```

要点：SQLite 的 JSON 函数（`json_extract`、`->`、`->>` 等）**同时接受文本 JSON 和 JSONB**；`jsonb()` 负责转进去，`json()` 负责转出来。这样做的收益是解析速度和存储紧凑，代价是——和 PG 的 jsonb 一样，**你不能再直接读文本**，调试时要先转回来。

## 5. 五、对照：JSONL vs JSONB

| 维度 | JSONL | JSONB（PG / SQLite） |
| --- | --- | --- |
| 形态 | 文本，一行一个值 | 二进制 |
| 写入 | 追加一行，O(1) | 解析后入库，成本更高 |
| 读取 | 逐行、可流式 | 按字段/路径查询，可建索引 |
| 可读性 | 直接看、grep、diff | 需函数转文本 |
| 键顺序 | 原样保留 | 丢失（PG 重组；SQLite 同理） |
| 重复键 | 各自保留（不同行） | 同一对象内只留最后一个 |
| 索引 | 无（就是文件） | GIN / 表达式索引 |
| 典型用途 | 日志、流、批量数据 | 可查询的半结构化数据 |

## 6. 六、怎么选

- **持续追加、按时间看、需要直接读** → JSONL。日志、会话记录、模型批量输入输出都属于这里。
- **要按字段查、要建索引、要和别的表关联** → JSONB。事件表、配置快照、第三方回调。
- **两者组合**最常见的形态是：写入侧先落 JSONL（便宜、可回放），再批量导入 `jsonb` 表供查询——采集与查询分开，各取所长。

## 7. 七、四个常见坑

1. **把 JSONL 当 JSON 整体解析**：必须逐行 `loads`；空行、末尾无换行都要单独处理。
2. **以为 jsonb 保留了键顺序**：PG 的 jsonb 会按键重组，SQLite 的 JSONB 也不保证——依赖顺序的代码要自己加序号字段。
3. **重复键静默覆盖**：`'{"a":1,"a":2}'::jsonb` 结果是 `{"a":2}`，不会报错。
4. **大整数精度**：JSON 数字没有精度规定，JavaScript 只有 double，`9007199254740993` 这类值会失真；跨语言存大整数请用字符串。

## 8. 重点总结

- **JSONL** 是文本流：一行一个 JSON 值，可追加、可逐行解析、坏行隔离，适合日志、会话记录和批量数据。
- **JSONB** 是二进制存储：写入时解析重组，换来可索引、可查询，代价是键顺序丢失、重复键去重、不可直接读文本。
- PostgreSQL 的 `json` 保留原文但不可索引，`jsonb` 可索引但会重组；SQLite 3.45+ 的 `jsonb()`/`json()` 在文本与二进制之间显式转换，函数同时兼容两者。
- 选型口诀：**持续追加看日志用 JSONL，按字段查用 JSONB，采集与查询分开用组合**。
- 最容易踩的坑：JSONL 整体解析、依赖 jsonb 的键顺序、重复键静默覆盖、大整数精度。

## 9. 参考

- [RFC 8259：JSON 数据交换格式](https://www.rfc-editor.org/rfc/rfc8259)
- [JSON Lines](https://jsonlines.org/)
- [NDJSON](https://github.com/ndjson/ndjson-spec)
- [PostgreSQL：JSON 类型](https://www.postgresql.org/docs/current/datatype-json.html)
- [PostgreSQL：JSON 函数与运算符](https://www.postgresql.org/docs/current/functions-json.html)
- [SQLite：JSON 函数与 JSONB](https://www.sqlite.org/json1.html)
