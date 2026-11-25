---
title: Pi 源码解读（五）：上下文工程——截断与压缩
date: 2026-11-17 14:47:31
description: 深入 Pi 的上下文工程：从工具输出的双限制截断，到历史压缩的切点算法、结构化摘要与 firstKeptEntryId 生效路径，看懂一套大模型会话如何在固定窗口里对抗无限增长的上下文。
slug: pi-context-engineering
categories:
  - 技术
tags:
  - 专栏
  - Pi 源码解读
  - TypeScript
cover: /img/2026/11/pi-context-engineering.jpg
---

> 在 Pi 这类编码 Agent 里，模型的上下文窗口是固定的（比如 200K token），但对话是无限增长的：读一个文件、跑一条命令、改一段代码，都会把内容塞进会话。如果不加以控制，上下文迟早溢出，要么请求失败，要么成本失控。Pi 的做法不是靠某一种「银弹」，而是层层设防。本篇就聚焦其中最关键的两层——**截断**与**压缩**，顺着源码看它们如何各司其职、又如何衔接。

## 一、基础与进阶用法

### 问题引入：固定窗口 vs 无限增长

一次会话里，上下文的增长来自两个方向：**单条输出过大**（例如一次 `cat` 把整份日志、一次构建把整屏堆栈带回来）和**历史条目过多**（几十轮来回，每轮都有工具调用与结果）。前者是「点状爆炸」，后者是「线状累积」，性质不同，对策也不同。

Pi 用一套**四层防线**来消化这种增长：

1. **截断**——在工具输出这一层动手，单条内容再大也先削掉，控制「每条」的体积；
2. **提示词组装**——在拼装发送给模型的上下文时，按压缩边界选择性收集，控制「总量」；
3. **压缩**——当历史整体过长时，把旧对话折叠成一段结构化摘要，控制「历史」的体积；
4. **分支摘要**——切换分支时对另一条路径做摘要，避免无关分支占满窗口。

本篇聚焦**截断**与**压缩**。可以粗略记：**截断解决「单条太大」，压缩解决「历史太长」**。前者是局部的、无损取舍（原文仍在，只是给模型看个概要），后者是全局的、有损折叠（旧内容被摘要取代）。

### 截断与压缩的分工

- **截断**发生在工具返回的瞬间：输出超过上限，立刻按方向裁剪，并把完整内容落盘，给出一个「逃生通道」提示，让模型知道去哪儿拿全量。它不改变会话结构，只控制单条消息的体量。
- **压缩**发生在会话层：当累计 token 逼近窗口上限，就把旧的若干条对话交给模型生成摘要，用一条 `compaction` 条目替换掉，后续组装上下文时只保留摘要 + 切点之后的原文。它改变的是会话的表示结构。

理解了这层分工，再看源码就顺了。

## 二、源码拆解

### 1. 截断：双限制，先到者胜

截断的核心实现在 `packages/coding-agent/src/core/tools/truncate.ts`。三个常量定义了默认上限（`truncate.ts:11-13`）：

```ts
export const DEFAULT_MAX_LINES = 2000;          // 作用：默认最多保留 2000 行
export const DEFAULT_MAX_BYTES = 50 * 1024;     // 作用：默认最多保留 50KB（字节上限）
export const GREP_MAX_LINE_LENGTH = 500;        // 作用：单条 grep 匹配行最多 500 字符
```

注意这是**双限制**：行数和字节，**谁先触顶就以谁为准**，而不是两个都满足才截断。`truncateHead` 从头部保留，`truncateTail` 从尾部保留，二者结构对称，核心都是逐行累加、先到先停。

以 `truncateHead` 为例，它的主循环（`truncate.ts:126-133`）就是双限制的落点：

```ts
for (let i = 0; i < lines.length && i < maxLines; i++) {   // 作用：行数闸——最多只取前 maxLines 行
	const line = lines[i];
	const lineBytes = Buffer.byteLength(line, "utf-8") + (i > 0 ? 1 : 0); // 作用：按 UTF-8 算本行字节，非首行补 1 字节换行
	if (outputBytesCount + lineBytes > maxBytes) {          // 作用：字节闸——累计一旦超 50KB，立即停
		truncatedBy = "bytes";                              // 作用：标记本次是因字节而非行数触发的截断
		break;
	}
	outputLinesArr.push(line);                              // 作用：该行完整保留
	outputBytesCount += lineBytes;                          // 作用：累加已用字节
}
```

循环结束后还有一段收尾判断（`truncate.ts:140`）：如果是因为塞满 `maxLines` 行而停、且字节没超，就把 `truncatedBy` 记为 `"lines"`。这样 `truncatedBy` 要么是 `"lines"` 要么是 `"bytes"`，明确告知是哪一闸先触发。

#### 方向选择：head 保结构，tail 保结论

`truncateHead` 与 `truncateTail` 的区别只在「保留哪一端」，而这个选择对应工具语义：

- **`truncateHead`（保头部）**：`read.ts:133` 直接调用它。读文件时，文件头部往往是 import、接口声明、类定义这些**结构信息**，模型最需要先看到，所以从头部保留。
- **`truncateTail`（保尾部）**：bash 的输出走尾部方向。命令执行的结果、错误堆栈、最终报错都在**末尾**，所以保留最后若干行。`bash.ts:283` 的工具描述也写明了「truncated to last 2000 lines or 50KB」，而 `bash.ts:372-373` 正是按尾部窗口反推 `startLine = totalLines - outputLines + 1`，印证了保留尾部。

#### UTF-8 边界安全

中文、emoji 等多字节字符在按字节裁剪时，最怕切在字符中间产生乱码。`truncateTail` 在「整行塞不进、又一条都还没保留」的极端情况下，会只取该行**尾部**的一段，这时调用 `truncateStringToBytesFromEnd`（`truncate.ts:208`）做边界对齐（`truncate.ts:257`）：

```ts
while (start < buf.length && (buf[start] & 0xc0) === 0x80) {   // 作用：若切点落在某字符的续字节上，就向后移到字符起点
	start++;
}
```

`sliceHead`/`sliceTail`（`truncate.ts:279-295`）则在按 UTF-16 码元裁剪时，用高低代理对判断避免拆开一个字符。

#### 单行超限与 `lastLinePartial`

当**单行**本身就超过字节上限，`truncateTail` 走尾部截该行，并把 `lastLinePartial` 置为 `true`（`truncate.ts:211`），表示保留区的第一行是**被截断的残行**。`truncateHead` 则在第一行就超限时，直接返回空内容并置 `firstLineExceedsLimit: true`（`truncate.ts:105-115`），把「连一行都放不下」这种情况单独标记出来。这些标志位会原样传给调用方，用于生成更精准的提示。

#### 逃生通道：临时文件 + 尾部提示行

截断不是丢弃，完整内容会写进临时文件。调用方据此在输出末尾追加一行提示，让模型知道去哪个路径拿全量。以 bash 为例（`bash.ts:378`）：

```ts
text += `\n\n[Showing lines ${startLine}-${endLine} of ${truncation.totalLines}. Full output: ${snapshot.fullOutputPath}]`;
// 作用：告知模型当前只展示了尾部窗口，完整输出在 fullOutputPath，可自行读取
```

这一行提示是截断的「逃生通道」：模型看到后能主动用 `read` 工具去临时文件取需要的部分，既控制了当前上下文体量，又没有真正丢失信息。

### 2. 压缩触发：阈值与 token 估算

压缩的入口在 `packages/coding-agent/src/core/compaction/compaction.ts`。默认配置定义了两个关键阈值（`compaction.ts:126-130`）：

```ts
export const DEFAULT_COMPACTION_SETTINGS: CompactionSettings = {
	enabled: true,
	reserveTokens: 16384,      // 作用：为后续工具调用、响应预留的余量，压缩前要留出这段缓冲
	keepRecentTokens: 20000,   // 作用：切点算法保留的最近 token 预算，这些原文不进摘要
};
```

触发判断是 `shouldCompact`（`compaction.ts:267-269`）：

```ts
export function shouldCompact(contextTokens: number, contextWindow: number, settings: CompactionSettings): boolean {
	if (!settings.enabled) return false;                              // 作用：开关关闭时一律不压缩
	return contextTokens > contextWindow - settings.reserveTokens;   // 作用：当前 token 超过「窗口 − 预留」即触发
}
```

对 200K 窗口、默认 16,384 预留，阈值就是 **183,616**。这是**预防式**触发：在真正溢出前就动手。与之对应还有**应急式**触发——当 API 报 overflow（上下文超限）时，也会强制触发一次压缩，作为兜底。

token 估算用 `estimateTokens`（`compaction.ts:298`），其返回统一走 `Math.ceil(chars / 4)`（如 `compaction.ts:311`）：

```ts
return Math.ceil(chars / 4);   // 作用：按「每 4 字符约 1 token」的启发式估算，向上取整偏保守
```

源码注释说明这是**保守（偏高估）**的估算。要留意一个坑：`chars / 4` 是按**字符**而非**字节**计，对中文这种「一个字占多 token」的语言，`chars / 4` 会**低估**实际 token 数。因此这个估算用于触发判断时是偏乐观的，Pi 用 `reserveTokens` 留出缓冲、并保留应急压缩来弥补这一偏差。

### 3. 切点算法：从后累积，只认合法切点

决定「哪些进摘要、哪些保留原文」的是 `findCutPoint`（`compaction.ts:446`）。思路很直白：**从最新往回累加 token，攒够 `keepRecentTokens`（20K）就停，停点即切点**。

但「停在哪」不是任意位置都行。`findValidCutPoints`（`compaction.ts:394-406`）先筛出**合法切点**：

```ts
for (let i = startIndex; i < endIndex; i++) {          // 作用：遍历候选区间
	const entry = entries[i];
	if (entry.type === "compaction") continue;         // 作用：压缩条目本身不是切点，跳过
	if (sessionEntryToContextMessages(entry).some(isCutPointMessage)) {  // 作用：只认 user / assistant 消息
		cutPoints.push(i);                             // 作用：toolResult 不在合法切点里
	}
}
```

关键约束是：**绝不在 toolResult 处切**。工具结果是跟随其 tool call 的，切在结果中间会让后面的结果失去归属。合法切点只包含 user 与 assistant 消息。`findCutPoint` 从后往前累积，越过预算后，取「不早于当前位置的最近合法切点」（`compaction.ts:472-476`），再向后扫描把相邻的、不影响上下文的元数据条目一并纳入，最后判定切点语义（`compaction.ts:493-499`）：

```ts
const startsTurn = isTurnStartEntry(cutEntry);                               // 作用：切点是否正好是某个 Turn 的起点
const turnStartIndex = startsTurn ? -1 : findTurnStartIndex(entries, cutIndex, startIndex); // 作用：若不是起点，回溯该 Turn 的 user 起点
return {
	firstKeptEntryIndex: cutIndex,                          // 作用：保留区的第一条 entry 索引
	turnStartIndex,
	isSplitTurn: !startsTurn && turnStartIndex !== -1,     // 作用：是否把一个 Turn 从中间切断
};
```

**切点 = 保留区第一条**：`firstKeptEntryIndex` 之前的进摘要，之后的保留原文。

#### 切在 Turn 中间：`isSplitTurn` 与 `turnPrefix`

如果切点落在一个 Turn 的中间（`isSplitTurn` 为真），直接把 Turn 拦腰斩断会让保留区丢失「用户最初问了什么」。Pi 的做法是**并行生成一段 `turnPrefix` 摘要**，与主摘要拼在一起。准备阶段先切出 `turnPrefixMessages`（`compaction.ts:895-899`）：

```ts
const turnPrefixMessages = cutPoint.isSplitTurn
	? projectedEntries.slice(cutPoint.turnStartIndex, cutPoint.firstKeptEntryIndex)  // 作用：取出 Turn 起点到切点之间的前缀消息
	.flatMap(getMessagesFromProjectedEntryForCompaction)
	: [];
```

`turnPrefix` 用一段独立的三段式模板（`TURN_PREFIX_SUMMARIZATION_PROMPT`，`compaction.ts:929`，含 Original Request / Progress So Far / Context Needed to Continue）。最终在 `compact()` 里把历史摘要与前缀摘要合并（`compaction.ts:1018`）：

```ts
summary = `${historyText}\n\n---\n\n**Turn Context (split turn):**\n\n${turnPrefixResult.text}`;
// 作用：用分隔线把「历史摘要」与「被切断 Turn 的前缀摘要」拼成一份，保证保留区能接上被截断的上下文
```

这样即使切在 Turn 中间，保留区仍能读到「用户原本的请求 + 已完成的进度」，不会因断层而失忆。

### 4. 摘要：6 段模板、增量更新、文件跟踪

摘要不是自由发挥，而是**结构化**的。`SUMMARIZATION_PROMPT`（`compaction.ts:507`）规定了固定的 6 段格式：

- **Goal**——用户要达成的目标；
- **Constraints & Preferences**——约束与偏好；
- **Progress**——分 **Done / In Progress / Blocked** 三个子项；
- **Key Decisions**——关键决策及理由；
- **Next Steps**——有序的后续步骤；
- **Critical Context**——必须保留的路径、函数名、错误信息。

模板末尾明确要求「Preserve exact file paths, function names, and error messages」，用固定结构对抗摘要漂移。

**增量更新**靠 `UPDATE_SUMMARIZATION_PROMPT`（`compaction.ts:577`）。当已有一份历史摘要时，`generateSummaryWithUsage` 选择更新模板（`compaction.ts:714`）：

```ts
let basePrompt = previousSummary ? UPDATE_SUMMARIZATION_PROMPT : SUMMARIZATION_PROMPT;
// 作用：有旧摘要就用「增量更新」模板，没有则用「首次生成」模板
```

更新模板的核心规则是 **PRESERVE（保留旧信息）+ ADD（补充新进展）+ UPDATE（推进 Progress / Next Steps）**，并把旧摘要包在 `<previous-summary>` 标签里一起喂给模型，让摘要随对话**渐进演化**而非每次重写。

**文件跟踪**由 `extractFileOperations`（`compaction.ts:60`）完成：它既从上一版 `CompactionEntry.details` 继承 `readFiles` / `modifiedFiles`，也从本轮消息里提取工具调用涉及的文件，累积成文件清单，最终作为 `details` 写进压缩条目。

### 5. 生效路径：`CompactionEntry` 与 `firstKeptEntryId`

压缩产出一个 `CompactionEntry`，其结构在 `session-manager.ts:91-99`：

```ts
export interface CompactionEntry<T = unknown> extends SessionEntryBase {
	type: "compaction";
	summary: string;            // 作用：6 段结构化摘要（含文件清单）
	firstKeptEntryId: string;   // 作用：保留原文的起始 entry 的 UUID，是选择性收集的锚点
	tokensBefore: number;       // 作用：压缩前的 token 基线
	details?: T;                // 作用：扩展数据，Pi 内部放 readFiles / modifiedFiles
	usage?: Usage;
}
```

`compact()` 返回这个结构（`compaction.ts:1048-1056`）：

```ts
return {
	summary,                                            // 作用：结构化摘要正文
	firstKeptEntryId,                                   // 作用：交给 SessionManager 落盘，作为保留起点
	tokensBefore,
	usage: summaryUsage,
	details: { readFiles, modifiedFiles } as CompactionDetails, // 作用：文件跟踪结果
};
```

真正让压缩「生效」的是组装上下文时的**选择性收集**，在 `buildContextEntries`（`session-manager.ts:476`，`buildSessionContext` 的前置环节）。它拿到路径上最新的 `compaction` 条目后，按 `firstKeptEntryId` 决定保留范围（`session-manager.ts:503-512`）：

```ts
if (entry.id === compaction.firstKeptEntryId) {     // 作用：命中保留起点，从此之后的 entry 才进入上下文
	foundFirstKept = true;
}
if (foundFirstKept && !(entry.type === "message" && entry.message.role === "system")) {
	contextEntries.push(entry);                      // 作用：起点之后原样保留；起点之前（已被摘要取代）的跳过
}
```

注意这里的语义是**跳过而非删除**：被摘要取代的旧条目仍留在会话记录里，只是在拼装发给模型的上下文时被排除。压缩条目本身作为「摘要代表」放在最前，其后紧跟 `firstKeptEntryId` 之后的原文。于是模型看到的是：**一段摘要 + 切点之后的完整原文**，历史体积被压下来，近期细节却完整无损。

## 三、设计思想与可迁移要点

**1. 多层防护，没有银弹。** 截断管单条、压缩管历史、组装管总量、分支摘要管路径，四层各自兜住一种溢出形态。任何单一机制都无法同时处理「点状爆炸」与「线状累积」，分层让每一层的规则都保持简单、可独立验证。

**2. 加法与减法分家。** 截断是**减法**——在内容进入上下文前削减体积；压缩是**加法**——把旧内容折叠成一段摘要加进上下文，同时用 `firstKeptEntryId` 做减法跳过原文。二者方向不同、时机不同，组合起来才能既控体量又不丢信息。

**3. 结构化对抗摘要漂移。** 摘要最容易出的问题是随模型自由发挥而漂移、丢失关键事实。Pi 用**固定 6 段模板 + 增量更新规则 + 强制保留路径/函数名/错误信息**来约束，让摘要稳定、可复现、可叠加，而不是每次重写一份泛泛的概述。

**4. 边界安全与可恢复性。** 按字节裁剪时对齐 UTF-8 字符边界、用 `lastLinePartial` / `firstLineExceedsLimit` 标记残行、截断后写临时文件并给出提示行——这些细节让「削减」是可解释、可恢复的，而非粗暴丢弃。

**5. 切点语义优先。** 切点只在 user/assistant 处、绝不切在 toolResult；切在 Turn 中间时补一段 `turnPrefix` 摘要。这说明压缩的设计重点不是「尽量少留」，而是「留得合理」——保证保留区能无缝接上被截断的上下文。

## 重点总结

- **截断**用双限制（2000 行 / 50KB，先到者胜）在工具输出层削体积，方向上 `truncateHead` 保结构（read）、`truncateTail` 保结论（bash），并做 UTF-8 边界对齐、单行超限标记，最后以临时文件 + 提示行留出逃生通道。
- **压缩**在会话层对抗历史过长：`shouldCompact` 按 `tokens > 窗口 − reserveTokens`（默认 183,616）预防式触发，`estimateTokens = ceil(chars/4)` 保守估算（对中文会低估，靠预留与应急兜底）。
- **切点算法**从最新往回累积到 `keepRecentTokens`（20K），合法切点只含 user/assistant、排除 toolResult；切点即保留区第一条；切在 Turn 中间时用 `turnPrefix` 三段式摘要并行补齐。
- **摘要**用 6 段结构化模板（Goal / Constraints / Progress / Key Decisions / Next Steps / Critical Context），支持基于 `previousSummary` 的增量更新，并累积 `readFiles` / `modifiedFiles` 做文件跟踪。
- **生效路径**通过 `CompactionEntry { summary, firstKeptEntryId, tokensBefore, details }`，在 `buildSessionContext` 组装时按 `firstKeptEntryId` **跳过**更早条目（非删除），呈现「摘要 + 切点后原文」。
- 设计上：多层防护、加法与减法分家、结构化对抗摘要漂移。

## 参考

- [earendil-works/pi 仓库](https://github.com/earendil-works/pi)
- [truncate.ts — 工具输出截断工具](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/truncate.ts)
- [compaction.ts — 压缩触发、切点算法与摘要生成](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/compaction/compaction.ts)
- [session-manager.ts — CompactionEntry 与 buildSessionContext 选择性收集](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/session-manager.ts)
- [read.ts — truncateHead 的使用方](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/read.ts)
- [bash.ts — 尾部截断与逃生通道提示行](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/bash.ts)
