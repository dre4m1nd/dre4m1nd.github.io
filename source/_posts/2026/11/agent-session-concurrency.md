---
title: "同一会话开两个终端会怎样：主流 Agent 的并发写方案横评"
slug: agent-session-concurrency
date: 2026-11-24 18:00:00
description: "会话文件是单写者资源，两个终端同时写同一个会话必然分叉。实测 pi、omp 的会话文件与锁，读源码看 DSH 的内核锁，查文档与 issue 看 Claude Code 与 Codex 的取舍，归纳出四种解法与各自的失败方式。"
categories:
  - 架构
tags:
  - Agent
  - 架构
cover: /img/2026/11/agent-session-concurrency.jpg
---

> 一道很小的实验：同一个会话，在两个终端里各发一句话，会发生什么。
>
> 答案是**会话会分裂**，而且几乎所有实现都默认会。这不是某个 agent 的 bug，而是「会话文件是单写者资源」这个假设被打破了。本文把 pi、omp、DSH、Claude Code、Codex 五家的做法摊开对比，全部基于本机实测的会话文件、安装包的源码、官方文档和公开 issue。

## 1. 为什么必然分裂

主流 agent 的会话存储是同一种形状：**只追加的日志 + 内存里的叶子指针**。

{% mermaid %}
%%{init: {'theme':'base', 'themeVariables': {'fontFamily':'inherit','fontSize':'14px','minNodeSpacing':20}}}%%
flowchart TB
    A["进程 A 启动<br/>读文件一次"] --> B["leafId = 最后一条"]
    C["进程 B 启动<br/>读文件一次"] --> D["leafId = 同一条"]
    B --> E["各自 append"]
    D --> E
    E --> F["同一父节点长出两条枝"]
    F --> G["各自的内存里只看到自己那条"]
{% endmermaid %}

三个动作构成了完整的问题：

1. **启动时只读一次**，之后 `leafId` 只存在于内存；
2. **写入只追加**，写完不回读、不校验 mtime；
3. **模型上下文来自内存里的 leaf 链**，不来自文件。

于是两个进程各自持有同一份快照，各自往后追加。文件层面长出一棵树，但两边都看不见对方那条枝。**失败方式永远是静默的**——从每个进程自己的视角看，一切正常。

## 2. 五种解法与它们的失败方式

{% mermaid %}
%%{init: {'theme':'base', 'themeVariables': {'fontFamily':'inherit','fontSize':'14px','minNodeSpacing':20}}}%%
flowchart LR
    Q["第二个写者出现"] --> A["不保护<br/>pi"]
    Q --> B["租约 + 搬到 sibling<br/>omp"]
    Q --> C["内核锁 + 拒绝<br/>DSH / Codex"]
    Q --> D["注册表 + attach / fork<br/>Claude Code"]
    A --> A2["静默长出多叶树"]
    B --> B2["一份会话变两个文件"]
    C --> C2["第二个进程报错"]
    D --> D2["文档说明 + 显式 fork"]
{% endmermaid %}

下面逐家展开，每家都给可核对的证据。

## 3. pi：不加保护，静默分叉

pi 1.5.2（`@earendil-works/pi-coding-agent`）的会话文件是 `~/.pi/agent/sessions/<编码cwd>/<时间戳>_<id>.jsonl`。

### 3.1. 实测：一个文件长出两条枝

我让同一份会话在两个终端里各发一句话，之后逐条解析 `parentId`：

```text
4cacb57d (assistant, 11.12 10:17:33 UTC)
├── c5280555 system (11.24 04:52:03.383) → a204b36c user「你好」
│   → 62d9c4c5 assistant → f16353ee system → c0412067 user「你在干什么」
│   → 4d35a268 assistant   ← 叶子 A
└── 34b2518d system (11.24 04:52:09.645) → 607f0edd user「你在干什么」
    → 668c0b39 … → a6bb2c15 user「我其实在做一个实验…」
    → … → fefe29c4 assistant   ← 叶子 B
```

两个 system 条目相隔 6.26 秒，各自带完整 `<tools>` 段——这是**每个进程启动时重新发一遍系统提示**，父节点都是当时文件里的最后一个叶子。这就是「两个进程都以为自己是唯一写者」的物证。

整份文件 135 行里，只有 `4cacb57d` 这一个 id 被两个条目当作父节点。

### 3.2. 源码：没有任何锁

```bash
# 在安装包里搜锁相关标识
$ grep -rho 'flock\|tryAcquireFileLock\|session-owners' \
    node_modules/@earendil-works/pi-coding-agent/dist
```

命中两次，都在 `highlight.min.js` 的语法高亮关键字表里（`flock` 是 Perl 内置函数名）。**会话层零命中**。

写入路径就是裸的追加：

```js
// 打包产物里的 _persist
_persist(entry){
  if(!this.flushed){ /* 首次写整份 */ }
  else appendFileSync(this.sessionFile, `${JSON.stringify(entry)}\n`)
}
```

而 `_buildIndex()` 在加载时逐条扫过去，`leafId = entry.id`，**最后一条物理条目胜出**。所以下次 resume 看到的是后写的那条枝，另一条被静默隐藏。

### 3.3. 全量重写的真实范围

流传的说法是「压缩、打 label 都会触发全量重写，会把对方新增的条目覆盖掉」。我数了 1.5.2 打包产物里的调用点，`_rewriteFile()` 只有 **3 处**：

| 调用点 | 触发条件 |
| --- | --- |
| `_setSessionFile` | 文件为空时初始化 header |
| `_loadEntries` | `migrateToCurrentVersion()` 返回 true（header `version < 3`） |
| `createBranchedSession` | fork / 分支时写新文件 |

`appendCompaction(...)` 是追加一条 `compaction` 条目，不重写；label 走内存表 + 追加。所以「全量重写丢数据」的风险成立，但范围比传闻窄——**实际只有 fork 和旧版本迁移这两条路**。

### 3.4. 唯一的补救是 `/tree`

被隐藏的分支并没有丢，只是不在默认叶子上。pi 有 `/tree` 命令，描述是 `Navigate session tree (switch branches)`，可以在枝之间切换。

但这是**事后手动操作**，不是机制。而且默认叶子的选择规则（最后一条物理条目）意味着你永远不会被告知存在另一条枝。

## 4. omp：租约 + 搬到 sibling 文件

omp 19.1.1 用的还是同一套 JSONL + `parentId` 树，但加了一层进程级租约。

### 4.1. 实测：文件被物理拆开

同样的实验，`~/.omp/agent/sessions/--D--notes-blog-hexo--/` 下出现两个文件：

| 文件 | 内容 |
| --- | --- |
| `2026-11-23T08-09-30-221Z_01a20773-….jsonl` | 原始会话，742 行 |
| `2026-11-24T04-42-08-564Z_01a20bdc-….jsonl` | 新文件，header 里 `parentSession` 与 `continuationOf` 都指向 `01a20773` |

两个文件开头的历史条目 **id 完全相同**（`4d3e88e0`、`09ffa143`…），说明第二个进程打开时把原 transcript 整体复制了一份，之后才分叉。

租约也能查：

```bash
$ omp session lease --json -- 01a20773-... 01a20bdc-...
{"held":["01a20773-...","01a20bdc-..."],"unknown":[]}
```

### 4.2. 机制

`~/.omp/run/session-owners/<session-id>` 是进程级租约：Windows 上是命名 mutex（不产生文件），Linux 是 `F_OFD_SETLK`，macOS 是 `flock`。

第二个写者的行为写在 `omp://docs/session.md` 里：**不碰别人的文件**，把完整 transcript 一次性发布到同目录的新 sibling 文件，新 session id + `parentSession` 指回原文件，然后继续增量追加。

这是「不阻塞也不损坏」的折中：两个终端都能继续工作，各自写各自的文件。代价是同一段历史存在两份，`--continue` 的行为取决于终端 breadcrumb。

它还会给出 `SessionPersistenceNotice` 警告——比 pi 的完全静默好一层。

## 5. DSH：内核锁 + 拒绝

DSH（`@deepseek-ai/dsh` 0.2.2-rc.1）走的是完全相反的方向：**内核级锁，第二个写者直接失败**。

### 5.1. 锁的实现

`@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js` 里的 `SessionWriteLease`：

```js
const LEASE_FILENAME = "session.lock";

// 争用判定：EAGAIN / EWOULDBLOCK 就是「别人拿着」
function isLockContention(error) {
  const code = error?.code;
  return code === "EAGAIN" || code === "EWOULDBLOCK";
}
```

两个平台分别处理：

| 平台 | 机制 | 特点 |
| --- | --- | --- |
| Windows | 命名信号量 `Local\dsh-session-lock-<sha256(path)>` + `WaitForSingleObject(handle, 0)` | 完全不碰文件系统 |
| POSIX | 对 `session.lock` 做非阻塞 `flock(2)` | 锁的是 inode，锁完还要校验 inode 没被替换 |

源码注释里的三条设计意图值得抄：

1. **没有过期时间**——"a live but wedged holder keeps the lock until its process exits: there is deliberately no expiry that could expropriate a stalled writer whose resumed appends would tear the log."宁可卡住也不抢锁，因为抢锁等于撕裂日志。
2. **进程死了锁自动释放**——内核在最后一个句柄关闭时销毁对象，崩溃不留僵尸锁。
3. **读者永远不碰锁**——读路径走 `access: "read"`，写操作才需要 `access: "write"`，否则抛 `SessionReadOnlyError`。

### 5.2. 争用之后发生什么

错误一路冒泡到 RPC 层：

```js
if (error.name === "SessionAlreadyOwnedError")
  return { error: new RemoteError("session/writer-held", error.message, { sessionId }) };
```

UI 把它翻译成用户能看懂的话（`dsh-client-ui-conversation` 的中文文案）：

> 当前会话已被占用，可能是其他正在运行的 DSH 导致的（如其他 dsh web、桌面端），请退出其他正在运行的 DSH 后重试。

这句文案暴露了它的架构：**DSH 是客户端/服务端**（`dsh web`、桌面端、ACP 都连同一个 host）。它真正解决的不是「两个进程抢一个文件」，而是**多个客户端连同一个会话时，谁是写者**。同一 host 内多客户端 attach 允许，跨 host 才争锁。

存储形态也不同：`~/.dsh/sessions/<编码cwd>/<session-id>/session.v4.jsonl.zstd`——每个会话一个目录、一个压缩日志、旁边一个 `session.lock`。

## 6. Claude Code：承认会分裂，给出 attach 与 fork

Claude Code 的存储形态和 pi 一样：`~/.claude/projects/<proj>/<session>.jsonl`，每行带 `uuid` + `parentUuid`。我核对了本机 transcript，确实是同一套树形结构。

### 6.1. 文件层面没有互斥

官方文档 `code.claude.com/docs/en/sessions` 写得很直白：

> If you resume the same session in two terminals or two `claude -p` runs at the same time, both write to one transcript. When you resume that session later, messages from one of them can be missing. To keep both conversations, add `--fork-session` to each `claude` command.

`~/.claude/sessions/` 目录里也没有 per-session 锁文件（本机实测是空的，只有 `.update.lock` 用于自更新）。

issue #97833 的复现记录更具体：两个进程同时 resume，同一文件长出两条枝；下次 resume **按「最后写入者」选叶子**，另一条被静默丢弃；有人扫了 58 份 transcript，4 份有并行期间写出的双枝。

### 6.2. 但它有两个真正的出口

**① 活会话注册表 + attach**

`~/.claude/sessions/<pid>.json` 每个活进程一个文件，字段包括 `pid`、`sessionId`、`cwd`、`status`（busy/idle/shell）、`tmux`（pane id）、`messagingSocketPath`、`peerProtocol`、`procStart`。

基于这张表：用 `--resume` 打开一个**还在后台跑**的会话时，它不加载 transcript，而是 `claude attach <id>` 直接接到那个进程上；`--continue` 遇到正在后台运行的会话会拒绝，并打印会话 ID。

**② `--fork-session` / `/branch`**

要并行就显式复制：`claude --continue --fork-session`，或会话内 `/branch`。新会话有独立 ID，原会话在磁盘上不动。

### 6.3. 漏掉的那一半

issue #69364 挂了五个月仍是 open：**两个交互式终端**互相 resume 时，注册表检查不生效。有人记录「两个终端各跑一整天，两边看起来都正常，重启后一天的工作消失」。#97833 里也补了一句：拒绝逻辑只覆盖「另一个进程是后台会话」，两个前台进程永远不会被拦住。

所以 Claude Code 的准确描述是：**互斥没有，检测有（但不完整），出口有（attach / fork）。**

## 7. Codex：写者锁 + 拒绝启动

Codex 0.169.0 是这批里唯一在**存储层就设了专用锁目录**的。

`~/.codex/` 下能看到这些与并发相关的产物：

```text
thread-writer-locks/          # 每个 thread 一个写者锁
  .coordination.lock          # 清理/协调用的全局锁
state_5.sqlite               # 索引与元数据（WAL）
session_index.jsonl.lock
```

从二进制里提取到的错误串，说明它选择让第二个进程失败：

```text
failed to acquire thread writer lock
timed out waiting for the thread writer coordination lock;
  another Codex process may be suspended on this or another host
Codex couldn't start because another Codex process is using its local data.
```

配套提供了三条替代路径：

| 命令/工具 | 作用 |
| --- | --- |
| `codex fork` | 显式分叉成新会话 |
| `codex queue` | 给正在跑的 thread 投递消息，而不是附着上去 |
| `read_thread` | "Read recent messages and status from another Codex task without opening it" |

这套组合是五种里最完整的：它把「查看」和「写入」彻底分开，并把「我想插一句话」从「附着会话」改成了「投递队列」。

顺带一提，它的 rollout 用 SQLite 索引（`threads` 表带 `rollout_path`、`rollout_ordinal`）加 JSONL 正文，SQLite 的 WAL 负责元数据侧的并发，JSONL 正文的并发由锁目录兜底。

## 8. opencode：单写者数据库 + 输入队列

opencode 换了个存储层：`~/.local/share/opencode/opencode.db`，SQLite，`journal_mode=wal`、`busy_timeout=5000`。

表结构本身就是答案：

```sql
event(id, aggregate_id, seq, type, data)
event_sequence(aggregate_id PRIMARY KEY, seq, owner_id)
session_input(id, session_id, prompt, delivery, admitted_seq, promoted_seq)
```

**事件溯源 + 每个 aggregate 一条单调递增的 seq**。写者不是「抢文件」，而是抢序列号；`session_input` 表带 `admitted_seq` / `promoted_seq`，说明用户输入是**先入队、再被提升进上下文**，而不是并发直接写。

这种设计下「两个窗口」天然不分裂：两边都只是往同一个队列投递，序列化由数据库保证。代价是整个存储层重了一个量级。

## 9. 横评

| | pi | omp | DSH | Claude Code | Codex | opencode |
| --- | --- | --- | --- | --- | --- | --- |
| 存储 | JSONL 树 | JSONL 树 | 目录 + zstd 日志 | JSONL 树 | JSONL + SQLite 索引 | SQLite 事件表 |
| 跨进程互斥 | ❌ | ✅ 租约 | ✅ 内核锁 | ❌ | ✅ 锁目录 | ✅ DB 事务 |
| 冲突时行为 | 静默分叉 | 迁到 sibling | 报错 `SessionAlreadyOwned` | 静默分叉（后台会话会 attach） | 拒绝启动 | 输入排队 |
| 是否告知用户 | ❌ | ✅ notice | ✅ 错误码 + 文案 | ⚠️ 仅文档说明 | ✅ 错误信息 | — 不需要 |
| 崩溃后残留 | 无锁 | 内核释放 | 内核释放 | 无锁 | 有 stale 清理逻辑 | 事务回滚 |
| 并行方式 | `/tree` 事后切 | 自动拆文件 | 另开 session | `--fork-session` / `/branch` | `codex fork` | 新 session |
| 只读打开 | 无专门模式 | 无 | ✅ `access: "read"` | 无 | `read_thread` | — |
| 定位 | 单机单写者 | 多终端可用 | 客户端/服务端 | 多端 + 后台会话 | 单写者 + 队列 | 数据库原生 |

## 10. 四种解法的本质区别

把上表压缩成一句话：**第二个写者出现时，你希望它做什么？**

| 期望 | 对应方案 | 代价 |
| --- | --- | --- |
| 别报错，让我继续干 | 租约 + sibling（omp） | 一份会话变成两个文件 |
| 报错，让我明确 fork | 写者锁（DSH、Codex） | 需要客户端/服务端或额外命令 |
| 根本不该有第二个写者，输入排队 | 单写者数据库（opencode） | 存储层重一个量级 |
| 不管，反正文件还是合法 JSON | 无保护（pi） | 静默丢分支 |

最后一行其实不算「错」——文件确实还是合法的树，`/tree` 还能取回被隐藏的分支。它错在**没有告诉用户发生了分叉**。

## 11. 三个值得记住的工程结论

### 11.1. 「静默」比「报错」更危险

pi 和 Claude Code 都会分裂，但两者的处境不同：pi 连文档都不提，Claude Code 至少在文档里写明了后果。

Codex 那句 `Codex couldn't start because another Codex process is using its local data.` 之所以是更好的设计，不是因为锁更强，而是因为它**把沉默换成了信息**。

### 11.2. 锁不能有过期时间

DSH 的注释值得单独抄一遍：没有过期机制，因为「抢锁」在只追加日志上等于「撕裂日志」。宁可让用户等一个卡死的进程退出，也不要让它被抢锁后继续 append。

这条对任何「只追加 + 内存指针」的存储都成立。

### 11.3. 读路径不该碰锁

DSH 把读和写分成 `access: "read"` / `access: "write"`，读者不碰锁文件。omp 的租约也只在写路径上申请。

反例是把锁加在打开文件上：一旦加锁，`omp share`、`--export`、列表预览这些只读操作都会被阻塞。

## 12. 参考

- [Claude Code 会话管理文档](https://code.claude.com/docs/en/sessions)——明确写了双开会导致消息丢失，以及 `--fork-session` 的用法
- [issue #69364：--continue / --resume 不检查活会话注册表](https://github.com/anthropics/claude-code/issues/69364)
- [issue #97833：resume 正在运行的会话会分叉 transcript](https://github.com/anthropics/claude-code/issues/97833)
- [issue #100824：活会话注册表 `~/.claude/sessions/<pid>.json` 的字段](https://github.com/anthropics/claude-code/issues/100824)
- [pi 仓库](https://github.com/earendil-works/pi)——`packages/coding-agent/src/core/session-manager.ts` 的 `_persist` / `_rewriteFile` / `_buildIndex`
- 本机安装包：`@earendil-works/pi-coding-agent@1.5.2`、`@deepseek-ai/dsh@0.2.2-rc.1`、`@openai/codex@0.169.0`、`omp 19.1.1`
- 本机数据：`~/.pi/agent/sessions/`、`~/.omp/agent/sessions/`、`~/.dsh/sessions/`、`~/.codex/thread-writer-locks/`、`~/.local/share/opencode/opencode.db`
