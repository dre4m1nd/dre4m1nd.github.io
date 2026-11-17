---
title: Pi 源码解读（六）：会话管理——树状存储与分叉
date: 2026-11-17 15:00:00
description: 深入 Pi 的会话管理：append-only JSONL 日志、id/parentId 构成的会话树、leaf 指针与 branch/branchSummary、跨会话 fork 的 parentSession，以及 v1→v2 迁移与从根到 leaf 的上下文重建。
slug: pi-session-tree
categories:
  - 技术
tags:
  - pi
  - 源码解读
  - TypeScript
cover: /img/2026/11/pi-session-tree.jpg
---

前五篇分别拆了 Agent 循环、工具管道、模型层、消息系统和上下文工程。上下文工程解决的是「窗口装不下」，但它默认了一个前提：会话已经存在，而且可以随时取出一条从根到当前位置的路径。会话到底怎么存？如果只是一个线性数组，回到三轮前改一句话、从某个节点开一条新分支、把整段对话搬到另一个项目，都会变成昂贵的数组手术。Pi 的答案很朴素：一条只追加的 JSONL 日志，用 `id`/`parentId` 把它组织成一棵树。

## 一、基础与进阶用法

### 1. 一个会话就是一个 JSONL 文件

默认目录由 `getDefaultSessionDirPath` 算出（`session-manager.ts:590-595`）：`~/.pi/agent/sessions/--<编码后的 cwd>--/`。每个会话对应一个 `.jsonl` 文件，文件名是「时间戳_会话 id」。文件第一行是 header：

```ts
// session-manager.ts:43-50
export interface SessionHeader {
	type: "session";
	version?: number;        // 作用：v1 会话没有这个字段，读取时按版本 1 处理
	id: string;              // 作用：会话 id，由 uuidv7 生成
	timestamp: string;
	cwd: string;             // 作用：会话启动时的工作目录
	parentSession?: string;  // 作用：fork 出来的会话在这里记录源文件路径
}
```

header 之后一行一个 entry。把与树结构无关的字段省略后，一次「提问 → 回答」的日志大概是这样：

```jsonc
{"type":"session","version":3,"id":"0192...","timestamp":"...","cwd":"/repo"} // 作用：第一行固定是 header，描述整个会话

{"type":"message","id":"a1b2c3d4","parentId":null,"timestamp":"...","message":{"role":"user","content":"..."}} // 作用：parentId 为 null，这条消息成为树根

{"type":"message","id":"c9d0e1f2","parentId":"a1b2c3d4","timestamp":"...","message":{"role":"assistant","content":"..."}} // 作用：parentId 指向上一条，形成父子链，leaf 随之前移
```

append-only 的含义是：正常运行时只往文件末尾追加一行，不修改、不删除已有行。只有迁移旧版本或需要整体重写时，才走一次整文件重写。纯文本的好处很实际——可以 `grep`、可以 `diff`、坏了也能手工修，后面要讲的容错和迁移都建立在这个格式上。

另一个细节是文件并非一开始就创建。`_hasConversation`（`session-manager.ts:1168-1178`）会检查是否已经出现了 user 或 assistant 消息；在此之前，`model_change`、`thinking_level_change` 这类设置型 entry 只留在内存里。这样「打开又关掉」不会留下一堆空会话，也解释了为什么 header 时间可能早于第一条消息。

### 2. leaf：当前分支的末端

树能成立，靠的是每条 entry 都带 `id` 和 `parentId`，`parentId` 为 `null` 的就是根。除此之外还有一个不在文件里、只存在于运行时的概念：**leaf**。它是「当前活跃分支的末端」。

规则只有两条：

- **追加**：以 leaf 为父节点新建 entry，然后把 leaf 前移到新节点；
- **分叉**：把 leaf 移回某个旧节点，下一次追加自然长出兄弟分支。

历史一行都不用改，分支就出现了。这是整个设计里最省力的一笔：分支不是「复制一份再改」，而是一次指针赋值。

读取文件时，leaf 也不需要额外元数据。`_buildIndex` 顺序扫描所有 entry，每遇到一条就把 `leafId` 指向它，所以最后一行天然就是当前分支的末端——因为最后写入的节点一定是刚追加的那个。

### 3. 日常动作对应的树操作

| 你做的事 | 树上发生的事 | 入口 |
| --- | --- | --- |
| 发一条消息 | 以 leaf 为父追加节点，leaf 前移 | `appendMessage` |
| 回到某条提问重新编辑 | leaf 移到该消息的父节点，原文回填输入框 | `branch` / `resetLeaf` |
| 从某个节点另起一条线 | leaf 移到该节点，后续追加形成新分支 | `branch` + `append*` |
| 切分支但保留旧分支要点 | 在目标位置追加一条分支摘要 | `branchWithSummary` |
| 把会话带到另一个项目继续 | 新建会话文件，header 记 `parentSession`，历史原样复制 | `forkFrom` |
| 恢复上次会话 | 读全部行、重建索引，leaf 指向最后一条 | `open` / `loadEntriesFromFile` |

「回到某条提问重新编辑」值得单独说。`agent-session.ts:4269-4280` 里，如果导航目标是用户消息或 `custom_message`，新的 leaf 取的是 `targetEntry.parentId`，消息原文回填编辑器；其余目标才直接把 leaf 设为目标节点。前者的语义是「把这条提问从历史里摘出来重发」，旧回答仍然留在另一条分支上；后者是「从这个节点之后继续」。两种都只是移动 leaf，没有任何历史被删除。

### 4. 树长什么样

假设你问了两轮，然后回到第一个回答处分叉：

```text
u1 ── model_change ── a1 ── u2 ── a2              ← 当前 leaf，root→leaf 进入上下文
                       │
                       └── branch_summary ── u2' ── a2'   ← 另一条分支
```

`branch_summary` 挂在分叉点 `a1` 下面，是 `u2` 的兄弟节点。它摘要的是被放弃的那段（`u2`、`a2`），但自身位于新分支上。于是新分支的上下文里只有「一段摘要 + 新对话」，旧分支的逐条消息不会挤进窗口。这就是「切换分支时避免无关分支占满窗口」的实现方式：并非删除旧分支，而是让它不在 leaf 到根的路径上。

### 5. 恢复会话

恢复没有独立的索引文件。`SessionManager.open` 先读 header，`loadEntriesFromFile` 读全部行，`_buildIndex` 重建 `byId` 与 label 映射，并把 leaf 指向最后一条 entry。日志是唯一真相，`byId`、`labelsById`、`leafId` 都只是可重建的缓存。这个选择让「恢复」退化成一次顺序读，也避免了索引与日志不一致的经典问题。

## 二、源码拆解

### 1. Entry 类型体系：一个基类，十一种判别

所有 entry 共享同一个基类（`session-manager.ts:57-62`）：

```ts
export interface SessionEntryBase {
	type: string;             // 作用：判别字段，决定这条 entry 怎么投影进上下文
	id: string;               // 作用：本节点 id，8 位十六进制，冲突时回退完整 UUID
	parentId: string | null;  // 作用：父节点 id；null 表示这是树根
	timestamp: string;
}
```

在此之上派生出十一种 entry，统一成 `SessionEntry` 联合类型（`session-manager.ts:183-194`）：

```ts
export type SessionEntry =
	| SessionMessageEntry       // 作用：一条对话消息（user/assistant/toolResult 等）
	| ThinkingLevelChangeEntry // 作用：思考等级变更
	| ModelChangeEntry         // 作用：模型切换
	| UsageEntry               // 作用：用量计量，不进入上下文
	| CompactionEntry          // 作用：历史压缩摘要
	| BranchSummaryEntry       // 作用：分支摘要
	| CustomEntry              // 作用：扩展状态，不进入上下文
	| CustomMessageEntry       // 作用：扩展注入的消息，进入上下文
	| ContextEditEntry         // 作用：对历史条目内容的追加式修改
	| LabelEntry               // 作用：书签/标记
	| SessionInfoEntry;        // 作用：会话元数据，如显示名
```

可以按职责分成四组：

- **对话内容**：`message`、`custom_message`，会变成模型可见的消息；
- **运行状态**：`model_change`、`thinking_level_change`、`usage`，回放时用来还原当时的配置与计量；
- **上下文治理**：`compaction`、`branch_summary`、`context_edit`，决定历史如何被折叠、替换；
- **用户与扩展元数据**：`label`、`session_info`、`custom`，其中 `custom` 明确不参与 LLM 上下文。

`context_edit` 很有意思：它不是原地改旧消息，而是追加一条「对某条历史 entry 的替换/隐藏指令」。原 entry 仍在，投影时才应用修改。这样「改历史」本身也变成了 append-only。

### 2. 追加：先改内存，再落盘，失败回滚

所有 `appendXxx` 最终都走 `_appendEntry`（`session-manager.ts:1199-1214`）：

```ts
private _appendEntry(entry: SessionEntry): void {
	const previousLeafId = this.leafId;   // 作用：记住旧 leaf，失败时回滚
	this.fileEntries.push(entry);
	this.byId.set(entry.id, entry);
	this.leafId = entry.id;               // 作用：leaf 前移到新节点
	try {
		this._persist(entry);
	} catch (error) {
		this.fileEntries.pop();           // 作用：内存回滚，避免出现文件里没有、内存里有的节点
		this.byId.delete(entry.id);
		this.leafId = previousLeafId;     // 作用：leaf 退回，后续 entry 不会挂在缺失的父节点上
		throw error;
	}
}
```

回滚这段是整棵树的一致性地基。假如写盘失败却仍然前移 leaf，下一条 entry 的 `parentId` 就会指向磁盘上不存在的节点，重启后这棵树直接断链。`_appendEntry` 用「push → 写 → 失败则 pop」保证了**内存中的 leaf 永远对应一条已经落盘的记录**。

落盘本身分两段（`session-manager.ts:1180-1196`）：第一次写入时用 `wx` 独占创建文件，把 header、此前缓存的设置型 entry 和本次 entry 一起写出；之后每次只 `appendFileSync` 一行。`wx` 的语义是文件已存在就失败，从而避免覆盖别人的会话文件。

具体到消息追加，`appendMessage` 只做三件事（`session-manager.ts:1222-1232`）：生成 id、把 `parentId` 设为当前 leaf、交给 `_appendEntry`。leaf 为 `null` 时 `parentId` 就是 `null`，这会创建一棵新树的根——`resetLeaf` 正是利用这一点，让你能回到第一条消息之前重新开局。

### 3. 分叉：移动 leaf 就是分叉

`branch` 的实现只有一行有效代码（`session-manager.ts:1597-1602`）：

```ts
branch(branchFromId: string): void {
	if (!this.byId.has(branchFromId)) {
		throw new Error(`Entry ${branchFromId} not found`);
	}
	this.leafId = branchFromId;   // 作用：只移动指针，不复制、不修改任何历史 entry
}
```

`resetLeaf` 则是把 `leafId` 设为 `null`（`session-manager.ts:1609-1611`）。两者都不触碰 `fileEntries`，所以分叉是 O(1) 的。

带摘要的切换是 `branchWithSummary`（`session-manager.ts:1618-1643`）：

```ts
const fromId = this.leafId ?? "root";   // 作用：先记下被放弃分支的末端
this.leafId = branchFromId;             // 作用：把 leaf 移到目标位置
const entry: BranchSummaryEntry = {
	type: "branch_summary",
	id: generateId(this.byId),
	parentId: branchFromId,               // 作用：摘要挂在新分支的起点
	timestamp: new Date().toISOString(),
	fromId,                               // 作用：记录摘要来自哪条旧分支
	summary,
	details,
	usage,
	fromHook,
};
this._appendEntry(entry);               // 作用：摘要成为新分支的第一个节点，leaf 随之前移
return entry.id;
```

注意顺序：先把旧 leaf 存进 `fromId`，再移动 leaf，最后追加摘要。摘要的 `parentId` 是**目标位置**而非旧分支末端，所以它属于新分支；`fromId` 则保留血缘，说明这段摘要是从哪条分支总结来的。`agent-session.ts:4282-4293` 的注释也强调同一件事：摘要附着在导航目标处，而不是旧分支上。

这解释了一个容易误解的点：切分支时生成摘要，并不是「给旧分支写墓志铭」，而是「给新分支写开场白」。旧分支一条不少地留在文件里，只是不再位于当前路径上；新分支从摘要开始，模型知道此前讨论过什么，却不用吞下全部细节。

### 4. fork：新文件 + parentSession

会话内的分叉靠移指针，跨会话/跨项目的 fork 则是另一套动作。`forkFrom`（`session-manager.ts:1833-1889`）先加载源会话，然后写一个新文件：

```ts
const newHeader: SessionHeader = {
	type: "session",
	version: CURRENT_SESSION_VERSION,
	id: newSessionId,                     // 作用：新会话 id，与源会话不同
	timestamp,
	cwd: resolvedTargetCwd,               // 作用：cwd 换成目标项目
	parentSession: resolvedSourcePath,    // 作用：记录源会话文件，保留血缘
};
const fd = openSync(newSessionFile, "wx");
try {
	writeFileSync(fd, `${JSON.stringify(newHeader)}\n`);
	for (const entry of sourceEntries) {
		if (entry.type !== "session") {
			writeFileSync(fd, `${JSON.stringify(entry)}\n`); // 作用：历史 entry 原样复制，id/parentId 保持不变
		}
	}
} finally {
	closeSync(fd);
}
```

三个要点：

1. **id 换新、cwd 换新、血缘留痕**：`parentSession` 指向源文件，`SessionInfo.parentSessionPath`（`session-manager.ts:229-243`）在列表里把它暴露出来；
2. **entry 原样复制**：不重新生成消息、不重排、不重新分配 id，`parentId` 链完整保留，所以复制过去仍是一棵合法的树；
3. **文件自包含**：源会话被移动或删除，fork 出来的会话照样能打开。

代价是 O(n) 的字节复制，但复制的是日志行，不是重建上下文，也不调用模型——相比「把历史重新喂给模型再生成一个新会话」，这几乎是最便宜的做法。

与之相对，`createBranchedSession`（`session-manager.ts:1650-1766`，其中重链部分 :1650-1700、label 重建部分 :1702-1728）只取 `root → leaf` 这一条路径，导出成独立会话：它会重链 `parentId`、把 `firstKeptEntryId` 里的 label 引用替换掉、再根据解析后的 label 映射重建 label entry。一个是「整棵树搬家」，一个是「剪下一根枝条」，用途不同，但都复用同一套 entry 格式。

### 5. 恢复与树遍历

读文件用 `loadEntriesFromFile`（`session-manager.ts:628-671`）：1MB 缓冲区、`StringDecoder` 处理跨块的多字节字符、逐行 `JSON.parse`，坏行直接跳过；文件末尾若缺换行会补一个。随后 `_buildIndex` 重建索引（`session-manager.ts:1116-1129`）：

```ts
for (const entry of this.fileEntries) {
	if (entry.type === "session") continue;
	this.byId.set(entry.id, entry);
	this.leafId = entry.id;        // 作用：顺序扫描，最后一条 entry 就是当前 leaf
	if (entry.type === "label") {
		if (entry.label) {
			this.labelsById.set(entry.targetId, entry.label);      // 作用：后写的 label 覆盖先写的
			this.labelTimestampsById.set(entry.targetId, entry.timestamp);
		} else {
			this.labelsById.delete(entry.targetId);                // 作用：空 label 表示清除标记
			this.labelTimestampsById.delete(entry.targetId);
		}
	}
}
```

取当前分支用 `getBranch`，就是一次 leaf→root 的回溯（`session-manager.ts:1487-1497`）：

```ts
getBranch(fromId?: string): SessionEntry[] {
	const path: SessionEntry[] = [];
	const startId = fromId ?? this.leafId;
	let current = startId ? this.byId.get(startId) : undefined;
	while (current) {
		path.push(current);                                                      // 作用：收集当前节点
		current = current.parentId ? this.byId.get(current.parentId) : undefined; // 作用：沿 parentId 上溯
	}
	path.reverse();                                                             // 作用：反转成 root→leaf
	return path;
}
```

要展示整棵树则用 `getTree`（`session-manager.ts:1547-1585`）。它先为每条 entry 建一个带 label 的节点，再按 `parentId` 挂父子关系：

```ts
for (const entry of entries) {
	const node = nodeMap.get(entry.id)!;
	if (entry.parentId === null || entry.parentId === entry.id) {
		roots.push(node);              // 作用：没有父节点（或自指）即根
	} else {
		const parent = nodeMap.get(entry.parentId);
		if (parent) {
			parent.children.push(node); // 作用：挂到父节点下，形成分支
		} else {
			roots.push(node);           // 作用：父节点缺失的孤儿也当根，避免整棵树丢失
		}
	}
}
```

两个防御性细节值得学：`parentId === id` 被当作根，避免自环；找不到父节点的孤儿也被提升为根，而不是静默丢弃。子节点排序用显式栈做迭代遍历，避免深树递归爆栈。

### 6. 上下文重建：只走当前路径

模型看到的内容，由 `buildSessionPath` 从 leaf 回溯得到（`session-manager.ts:390-416`）：

```ts
const path: SessionEntry[] = [];
let current: SessionEntry | undefined = leaf;
while (current) {
	path.push(current);                                                   // 作用：先把当前节点收进路径
	current = current.parentId ? index.get(current.parentId) : undefined; // 作用：上溯到根为止
}
path.reverse();                                                          // 作用：得到 root→leaf 的顺序
return path;
```

拿到路径后，`buildContextEntries` 再处理压缩（`session-manager.ts:476-512`）：找路径上**最后一条** `compaction`，用这条摘要取代它之前的全部历史，然后从 `firstKeptEntryId` 开始补回保留的原文，压缩记录之后的新条目则全部保留。这也解释了上一篇里 `firstKeptEntryId` 为什么必须是 id 而不是数组下标——树可以分叉、文件可以被复制，只有 id 在所有这些操作后仍然稳定。

分支摘要进入上下文的方式很直接（`session-manager.ts:458-460`）：

```ts
if (entry.type === "branch_summary" && entry.summary) {
	return [createBranchSummaryMessage(entry.summary, entry.fromId, entry.timestamp)]; // 作用：摘要作为一条独立消息进入上下文
}
```

所以最终的上下文是三层过滤的结果：**树**决定了哪些 entry 在候选路径上（只有 leaf 的祖先链），**压缩**决定了路径前段是否被摘要折叠，**投影**决定了每种 entry 是否产生模型可见消息。文件里存着所有分支，但进入模型的永远只有当前这一条。

### 7. 旧日志迁移：先补树，再改名

早期会话是线性日志，没有 `id`/`parentId`。`migrateV1ToV2` 的职责就是把线性历史改造成一条退化树（`session-manager.ts:286-313`）：

```ts
function migrateV1ToV2(entries: FileEntry[]): void {
	const ids = new Set<string>();
	let prevId: string | null = null;      // 作用：v1 是线性日志，用前一条的 id 当父节点

	for (const entry of entries) {
		if (entry.type === "session") {
			entry.version = 2;             // 作用：header 升版，避免重复迁移
			continue;
		}

		entry.id = generateId(ids);         // 作用：补一个 8 位短 id
		entry.parentId = prevId;            // 作用：接到前一条后面，线性历史变成一条单链
		prevId = entry.id;

		if (entry.type === "compaction") {
			const comp = entry as CompactionEntry & { firstKeptEntryIndex?: number };
			if (typeof comp.firstKeptEntryIndex === "number") {
				const targetEntry = entries[comp.firstKeptEntryIndex];
				if (targetEntry && targetEntry.type !== "session") {
					comp.firstKeptEntryId = targetEntry.id; // 作用：数组下标改成 id 引用，复制后依然有效
				}
				delete comp.firstKeptEntryIndex;
			}
		}
	}
}
```

迁移按版本顺序串起来（`session-manager.ts:337-347`）：`header.version` 缺省视为 1，依次跑 v1→v2、v2→v3（把 `hookMessage` 角色改名为 `custom`），任一迁移发生就返回 `true`，`_loadEntries` 随即重写整个文件。这样迁移只付一次成本，之后读到的都是当前格式。

## 三、设计思想与可迁移要点

**Append-only 日志作为唯一真相。** 只追加带来三个直接收益：写入是 O(1) 的一行、崩溃时最多丢最后半行、审计天然完整。所有查询结构（`byId`、label 映射、leaf）都能从日志重建，因此它们可以随便缓存、随便丢。把「日志」和「索引」分开，是这套设计最值得抄的一点。

**树让「历史」与「上下文」解耦。** 文件保存的是全部历史，模型看到的只是 root→leaf 的一条路径。于是「回到过去」不是回滚，而是移动 leaf；「尝试另一种回答」不是覆盖，而是长出新分支。一个线性数组做不到这点，因为它把「存储顺序」和「当前对话」绑死了。

**分叉的两种粒度，都避免重建。** 会话内分叉是 O(1) 的指针赋值；跨会话 fork 是日志行的原样复制，保留节点 id 与父子关系，不做消息重建、不调模型。前者共享内存里的树，后者共享格式与结构语义——共同点是都不需要「把历史重新理解一遍」。

**摘要放在新分支的入口，而不是旧分支的出口。** `branchWithSummary` 先记 `fromId` 再移 leaf，让摘要成为新分支的第一个节点。这样旧分支可以完整保留，新分支又带着必要的来龙去脉；同一个 leaf 机制，加不加摘要只是策略差异。

**状态也是事件。** 模型切换、思考等级、label、会话名、用量，全都是追加的 entry，而不是原地更新的字段。回放日志就能还原任意时刻的配置，不需要为每种状态维护一张可变表，也不需要考虑「字段什么时候被谁改过」。

**用不变量兜底。** `_appendEntry` 失败回滚、坏行跳过、孤儿节点提升为根、迁移后重写——这些细节都在守护同一条不变量：`parentId` 必须指向一个存在的节点，leaf 必须对应一条已落盘的记录。树的全部算法都建立在这条不变量上，守住它，上层逻辑才能写得这么短。

如果你要在自己的 Agent 里实现会话记忆，这套结构可以按下面的顺序落地：

1. 先用 JSONL + `id`/`parentId` 把会话写下来，别急着上数据库；
2. 用 leaf 指针 + `append` 接口封装写入，让「分支」退化成一次赋值；
3. 需要跨分支时，用摘要 entry 做压缩边界，而不是删旧消息；
4. 需要跨项目时，复制日志并记录 `parentSession`，保留原 id 与父子链；
5. 迁移函数按版本号顺序执行，迁移后立即重写，保证只付一次成本；
6. 所有索引都实现成可重建的派生结构，永远可以从日志重新算出来。

## 重点总结

- 会话是一个 append-only 的 JSONL 文件：首行 header，之后一行一个 entry；正常运行时只追加。
- 每条 entry 都有 `id`/`parentId`，`parentId` 为 `null` 的是根；`leaf` 是当前活跃分支的末端，只存在于运行时。
- 追加 = 以 leaf 为父新建节点并前移 leaf；分叉 = 把 leaf 移回旧节点，历史一行不改。`branch` 的有效逻辑只有 `this.leafId = branchFromId`。
- 十一种 entry 共享 `SessionEntryBase`，按职责分为对话内容、运行状态、上下文治理、元数据四组；`context_edit` 让「修改历史」也保持 append-only。
- `branchWithSummary` 先保存旧 leaf 到 `fromId`，再把摘要挂到目标位置：摘要属于新分支，旧分支完整保留，切换后只有摘要进入新路径。
- 跨会话 `forkFrom` 新建文件、换 id 与 cwd、把 `parentSession` 指向源文件，并原样复制所有 entry，`id`/`parentId` 不变，因此树结构无损。
- 恢复靠 `loadEntriesFromFile` + `_buildIndex`：顺序读、坏行跳过、leaf 指向最后一条；`getBranch` 沿 `parentId` 回溯，`getTree` 把孤儿提升为根并迭代排序。
- 上下文重建是三层过滤：leaf 祖先链选候选、`compaction` 折叠前段、投影决定 entry 是否产生消息。
- v1→v2 补 `id`/`parentId` 把线性日志变成单链树，并把 `firstKeptEntryIndex` 改成 `firstKeptEntryId`；迁移后整文件重写一次。
- 最值得迁移的三点：日志即真相、树让历史与上下文解耦、分叉只追加不重建。

## 参考

- [pi 仓库](https://github.com/earendil-works/pi)
- [packages/coding-agent/src/core/session-manager.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/session-manager.ts)（`SessionEntryBase` :57、entry 类型 :64-180、`SessionTreeNode` :200、v1→v2 迁移 :286、`buildSessionPath` :390、`buildContextEntries` :476、`loadEntriesFromFile` :628、`SessionManager` :995、`_buildIndex` :1111、`_persist` :1180、`_appendEntry` :1199、`appendMessage` :1222、`appendCompaction` :1279、`appendContextEdit` :1378、`getBranch` :1487、`getTree` :1547、`branch` :1597、`branchWithSummary` :1618、`createBranchedSession` :1650、`forkFrom` :1833）
- [packages/coding-agent/src/core/agent-session.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/agent-session.ts)（分支目标与 leaf 计算 :4265-4306）
- [packages/coding-agent/src/core/messages.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/messages.ts)（`createBranchSummaryMessage`、`createCompactionSummaryMessage`）
