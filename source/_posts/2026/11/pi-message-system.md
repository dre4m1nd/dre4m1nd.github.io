---
title: "Pi 源码解读（四）：消息系统——内富外严的两层翻译"
date: 2026-11-17 12:00:00
description: 从一条 `!ls -la` 命令出发，看 Pi 如何用 4 种标准消息加 4 种自定义消息，把「UI 要结构化字段」与「LLM 只认标准 role」这对矛盾拆成两层，并逐段拆解 convertToLlm 的 role 分派、三档可见性，以及签名透传带来的有损单向翻译。
categories:
  - 技术
tags:
  - 专栏
  - Pi 源码解读
  - TypeScript
cover: /img/2026/11/pi-message-system.jpg
---

前一篇读完了工具系统的五步管道，这一篇把镜头对准更底层、也更容易被忽略的一环：**消息**。在整个 Agent 工程里，消息是最不起眼却最容易被写歪的数据结构——因为它有两个读者，而这两个读者的需求是冲突的。本文从一条 `!ls -la` 讲起，先看用法，再逐段拆 `convertToLlm`，最后聊这套设计里可以带走的几条原则。

## 1. 一、基础与进阶用法

### 1.1. 一条 `!ls -la` 的三种形态

在 Pi 里敲 `!ls -la`，你是在绕过模型直接执行命令。这条命令在系统里会依次以三种形态出现。

**形态一：终端里的一段文本。** 你看到命令、输出、退出码，输出太长时还有一行「已截断，完整输出见某文件」。

**形态二：会话历史里的一条结构化消息。** 执行结果由 `recordBashResult`（agent-session.ts:4053）落成 `BashExecutionMessage`：

```ts
// packages/coding-agent/src/core/messages.ts:29
// 作用：一次 `!` 命令的完整记录——注意它是一个独立的 role，而不是 user 消息
export interface BashExecutionMessage {
    role: "bashExecution";     // 作用：自造 role，标准 Message 里没有这个值
    command: string;           // 作用：原始命令，UI 要原样回显
    output: string;            // 作用：合并后的 stdout/stderr，UI 与 LLM 都要
    exitCode: number | undefined; // 作用：失败要染色、要显示，所以必须留结构化数字
    cancelled: boolean;        // 作用：用户中途 Ctrl-C，和「失败」语义不同
    truncated: boolean;        // 作用：输出被截断时 UI 要提示，LLM 也要知道
    fullOutputPath?: string;   // 作用：完整输出的落盘路径，供 LLM 二次读取
    timestamp: number;         // 作用：时间戳，排序与摘要都要用
    /** If true, this message is excluded from LLM context (!! prefix) */
    excludeFromContext?: boolean; // 作用：可见性开关，「给 UI 看」但不「给模型看」
}
```

它被 `session-manager.ts:1222` 的 `appendMessage` 写进会话历史，于是成为 `AgentMessage[]` 的一员。

**形态三：模型眼里的一段用户文本。** 当这一轮要发给 LLM 时，`convertToLlm` 把它翻译成一条普通的 `UserMessage`：`role` 变成 `"user"`，`content` 是一段由 `bashExecutionToText` 拼出来的纯文本。模型永远不知道「bashExecution」这个东西存在。

三种形态，两个世界。这就是整个消息系统的全部要点。

### 1.2. 两个读者，两种语言

矛盾在这里：

- **UI 要富。** 要渲染 shell 块、要红绿标记退出码、要显示「已截断」徽标、要能点开完整输出。这些都要求字段独立、类型明确。
- **LLM 要严。** 各家提供商的 API 只接受固定的几种 role：`system`、`user`、`assistant`、`toolResult`。你塞一个 `role: "bashExecution"` 进去，请求直接 400。

朴素的做法是二选一：要么全部塞进 `content` 字符串，让 UI 去正则解析退出码和截断提示；要么把富对象直接当消息发给供应商，指望它容忍未知 role。前者把结构丢给了脆弱的文本解析，后者则连第一轮请求都发不出去。还有一种折中——把富字段挂在一个 `metadata?: unknown` 里——看似两全，实际放弃了类型检查：谁都能往里塞东西，谁也说不清里面该有什么。

一个数据结构不可能同时满足两边，除非在中间做一次翻译。Pi 的选择是：**内层按 UI 的需要建模，出口按 LLM 的需要翻译**。于是类型也分了两层：

```ts
// packages/ai/src/types.ts:667
// 作用：外层契约——供应商能接受的全部消息种类，只有 4 种
export type Message = SystemMessage | UserMessage | AssistantMessage | ToolResultMessage;
```

```ts
// packages/agent/src/types.ts:365
// 作用：内层容器——默认是空接口，应用层通过声明合并往里加 role
export interface CustomAgentMessages {
    // Empty by default - apps extend via declaration merging
}

// packages/agent/src/types.ts:374
// 作用：AgentMessage 把所有自定义 role 并进联合类型，编译期就能收窄
export type AgentMessage = Message | CustomAgentMessages[keyof CustomAgentMessages];
```

`Message` 是出口，`AgentMessage` 是内部存储。核心包的出口只有 `Message` 这 4 种 role，产品层用声明合并往 `AgentMessage` 里加东西。

### 1.3. 进阶：三种扩展路径

**`!!` 前缀。** 命令前多一个感叹号，执行照旧、历史照记、UI 照显示，但不会进入模型上下文。`executeBash` 的选项里带着 `excludeFromContext`（agent-session.ts:4011），一路传到 `recordBashResult`（agent-session.ts:4053）写进字段。这是最轻量的「可见性」控制——一个布尔值，不删数据。

**扩展注入消息。** 扩展用 `sendMessage()` 往会话里塞东西，落成 `CustomMessage`：带 `customType` 便于分类渲染，带 `display` 控制 UI 是否展示，带 `details` 存任意业务数据。

**摘要消息。** 上下文压缩（compaction）和分支回溯（branch summary）都需要把「一大段历史」替换成「一段摘要」，但摘要又不是用户说的话。Pi 给它们各开一个 role，翻译时再加 `<summary>` 包裹，让模型明确知道这是压缩产物而非用户意图。

## 2. 二、源码拆解：两层八种消息

### 2.1. 内层之外：4 种标准消息

先纠正一个常见误解：标准消息不是 3 种，**是 4 种**，`system` 是其中之一。

```ts
// packages/ai/src/types.ts:569
// 作用：系统消息是一等公民，可以在对话中段出现，用来「改写」此后的提示词
export interface SystemMessage {
    role: "system";                                 // 作用：标准 role
    content: string | TextContent[];                // 作用：指令文本；首条是基础提示词，后续是追加
    sections?: Record<string, string | null>;       // 作用：命名段落，中段可替换、可置 null 删除
    toolsAdded?: Tool[];                            // 作用：从这一刻起可用的工具定义
    toolsRemoved?: ToolReference[];                 // 作用：从这一刻起失效的工具
    timestamp: number;                              // 作用：Unix 毫秒时间戳
}

// packages/ai/src/types.ts:587
// 作用：用户消息最朴素——一段文本或多模态块
export interface UserMessage {
    role: "user";                                   // 作用：标准 role
    content: string | (TextContent | ImageContent)[]; // 作用：字符串或多模态内容块
    timestamp: number;                              // 作用：Unix 毫秒时间戳
}
```

`SystemMessage` 值得多说一句。它不是「会话开头那一段静态提示词」，而是**可重放的状态变更**：中段插入一条 system 消息，`content` 追加指令、`sections` 按名替换段落、`toolsAdded`/`toolsRemoved` 改工具集。把所有 system 消息按序重放，就得到当前完整的提示词与工具表——支持中段 system 的供应商就地发送，不支持的供应商则在前置 system 消息上重建。这也解释了为什么 `system` 必须是标准消息之一：它是 prompt 的唯一真相来源。

另外两种：

```ts
// packages/ai/src/types.ts:593
// 作用：助手消息带满了「回传供应商需要的元数据」，注意后三个签名字段
export interface AssistantMessage {
    role: "assistant";                              // 作用：标准 role
    content: (TextContent | ThinkingContent | ToolCall)[]; // 作用：文本/思考/工具调用三种块
    api: Api;                                       // 作用：用哪个 API 形态产生的
    provider: ProviderId;                           // 作用：供应商标识
    model: string;                                  // 作用：请求的模型名
    usage: Usage;                                   // 作用：token 计量
    stopReason: StopReason;                         // 作用：停止原因
    timestamp: number;                              // 作用：请求开始时间
    // ……省略诊断、延迟、响应 ID 等审计字段
}
```

```ts
// packages/ai/src/types.ts:648
// 作用：工具结果——条件类型，details 不满足 JSON 兼容时整条退化为 never
export type ToolResultMessage<TDetails = JsonValue> = IsJsonCompatible<TDetails> extends true
    ? {
          role: "toolResult";                      // 作用：标准 role
          toolCallId: string;                      // 作用：回指哪个调用
          toolName: string;                        // 作用：工具名，便于模型定位
          content: (TextContent | ImageContent)[]; // 作用：结果内容，支持图片
          details?: JsonRepresentation<TDetails>;  // 作用：结构化细节，UI 用，不一定给模型
          isError: boolean;                        // 作用：错误也是消息（上一篇讲过）
          // ……省略 usage、nestedCalls、durationMs 等执行期字段
          timestamp: number;                       // 作用：结果创建时间
      }
    : never;
```

至此 4 种齐了：`system`、`user`、`assistant`、`toolResult`。再往上加任何 role，都不再是 `Message`。

### 2.2. 外层：4 种自定义消息与声明合并

coding-agent 通过声明合并，往 `CustomAgentMessages` 里注入 4 个 role（messages.ts:70-77），于是 `AgentMessage` 在这个构建里是 8 种：

```ts
// packages/coding-agent/src/core/messages.ts:70
// 作用：声明合并——不修改核心包一行代码，就把它认识的联合类型拓宽
declare module "@earendil-works/pi-agent-core" {
    interface CustomAgentMessages {
        bashExecution: BashExecutionMessage;      // 作用：`!` 命令的执行记录
        custom: CustomMessage;                    // 作用：扩展注入的任意消息
        branchSummary: BranchSummaryMessage;      // 作用：分支回溯摘要
        compactionSummary: CompactionSummaryMessage; // 作用：上下文压缩摘要
    }
}
```

另外三种消息的字段都很克制：

```ts
// packages/coding-agent/src/core/messages.ts:46
// 作用：扩展消息——customType 供 UI 分类，display 控制是否渲染
export interface CustomMessage<T = unknown> {
    role: "custom";                    // 作用：自定义 role
    customType: string;                // 作用：扩展自己定义的类别名
    content: string | (TextContent | ImageContent)[]; // 作用：正文
    display: boolean;                  // 作用：true 才在 UI 里展示（模型照样能看到）
    details?: T;                       // 作用：业务数据，翻译时直接丢弃
    timestamp: number;                 // 作用：时间戳
}

// packages/coding-agent/src/core/messages.ts:55
// 作用：分支摘要——fromId 指向回退到哪个节点
export interface BranchSummaryMessage {
    role: "branchSummary";             // 作用：自定义 role
    summary: string;                   // 作用：摘要正文
    fromId: string | null;             // 作用：来源消息 ID
    timestamp: number;                 // 作用：时间戳
}

// packages/coding-agent/src/core/messages.ts:62
// 作用：压缩摘要——多留一个 tokensBefore 用于展示压缩收益
export interface CompactionSummaryMessage {
    role: "compactionSummary";         // 作用：自定义 role
    summary: string;                   // 作用：摘要正文
    tokensBefore: number;              // 作用：压缩前 token 数，UI 展示「省了多少」
    timestamp: number;                 // 作用：时间戳
}
```

**这套机制的精妙处在于零依赖。** `pi-agent-core` 里 `CustomAgentMessages` 就是个空接口，核心包对 coding-agent 一无所知；但 TypeScript 的声明合并让 `AgentMessage` 在应用层自动变成 8 种。核心包里没有 role 分派的 switch，它用 filter 只保留 4 种标准 role；应用层的 switch 则对全部 8 种 role 做穷尽检查，编译期就能发现漏掉的分支。

### 2.3. convertToLlm：一次 role 分派

翻译器本体只有不到 50 行（messages.ts:148-196），但每一段都在回答「这条消息对模型意味着什么」。

```ts
// packages/coding-agent/src/core/messages.ts:148
// 作用：跨层翻译器（应用层实现），纯函数，输入 AgentMessage[]，输出 Message[]
export function convertToLlm(messages: AgentMessage[]): Message[] {
    return messages
        .map((m): Message | undefined => {
            switch (m.role) {
                case "bashExecution":
                    // 作用：可见性闸门——`!!` 命令在这里被丢弃，数据仍在历史里
                    if (m.excludeFromContext) {
                        return undefined;
                    }
                    // 作用：结构化字段降维成一段文本，包成标准 user 消息
                    return {
                        role: "user",
                        content: [{ type: "text", text: bashExecutionToText(m) }],
                        timestamp: m.timestamp, // 作用：时间戳原样带过去
                    };
                case "custom": {
                    // 作用：字符串正文规范成内容块数组，其余字段（details/display）直接丢弃
                    const content = typeof m.content === "string" ? [{ type: "text" as const, text: m.content }] : m.content;
                    return {
                        role: "user",
                        content,
                        timestamp: m.timestamp,
                    };
                }
                case "branchSummary":
                    // 作用：加前后缀包成 <summary>，让模型知道这是摘要而非用户发言
                    return {
                        role: "user",
                        content: [{ type: "text" as const, text: BRANCH_SUMMARY_PREFIX + m.summary + BRANCH_SUMMARY_SUFFIX }],
                        timestamp: m.timestamp,
                    };
                case "compactionSummary":
                    // 作用：同上，但用的是压缩摘要的前后缀（文案不同，语义更明确）
                    return {
                        role: "user",
                        content: [
                            { type: "text" as const, text: COMPACTION_SUMMARY_PREFIX + m.summary + COMPACTION_SUMMARY_SUFFIX },
                        ],
                        timestamp: m.timestamp,
                    };
                case "system":
                case "user":
                case "assistant":
                case "toolResult":
                    return m; // 作用：标准消息原样透传，一个字段都不动
                default:
                    // biome-ignore lint/correctness/noSwitchDeclarations: fine
                    const _exhaustiveCheck: never = m; // 作用：穷尽检查——新增 role 未处理时编译报错
                    return undefined;
            }
        })
        .filter((m) => m !== undefined); // 作用：把被过滤掉的消息从结果里剔除
}
```

四个自定义 role 全部翻译成 `user`，这是有意的：模型侧没有「系统注入」这种语义，任何非模型自己产出的内容，对模型来说都是「用户告诉我的」。摘要用 `<summary>` 包裹，是因为模型需要区分「这是压缩后的二手信息」还是「用户此刻的原始诉求」——两者的可信度与处理方式不同。

`default` 分支的 `const _exhaustiveCheck: never = m` 是这套设计的安全网。核心包新增一种标准 role 时，这里会立刻编译失败，逼你回来决定它该怎么翻译，而不是悄悄掉进 `default` 被丢弃。

### 2.4. bashExecutionToText：结构化的降维损失

降维发生在 `bashExecutionToText`（messages.ts:82-98）：

```ts
// packages/coding-agent/src/core/messages.ts:82
// 作用：把一个富对象压成一段人可读、模型可读的文本
export function bashExecutionToText(msg: BashExecutionMessage): string {
    let text = `Ran \`${msg.command}\`\n`; // 作用：先交代「跑了什么」，让模型知道上下文
    if (msg.output) {
        text += `\`\`\`\n${msg.output}\n\`\`\``; // 作用：输出包进围栏块，避免与指令文本混淆
    } else {
        text += "(no output)"; // 作用：「无输出」要显式写出来，否则模型会以为结果缺失
    }
    if (msg.cancelled) {
        text += "\n\n(command cancelled)"; // 作用：取消单独一行，语义优先于退出码
    } else if (msg.exitCode !== null && msg.exitCode !== undefined && msg.exitCode !== 0) {
        text += `\n\nCommand exited with code ${msg.exitCode}`; // 作用：只有非 0 才提，成功是默认预期
    }
    if (msg.truncated && msg.fullOutputPath) {
        text += `\n\n[Output truncated. Full output: ${msg.fullOutputPath}]`; // 作用：给模型一条「可以自己去读」的线索
    }
    return text;
}
```

注意这里的信息损失：`exitCode: 0` 在文本里**完全消失**（成功不占 token），`cancelled` 与「非 0 退出」被压成同一维度下的二选一，`truncated` 只有在 `fullOutputPath` 存在时才被提及。结构化字段有 6 个，落到文本只剩 4 类句子。

这不是偷懒，是**故意的单向有损**。它带来两个直接后果：翻译只能正向做，反向不可能——你没法从 `"Command exited with code 1"` 这行字可靠地还原出 `exitCode` 的原始取值，更没法判断一个非 0 退出究竟是正常失败还是被信号中断。

### 2.5. 三档可见性

两个布尔字段，各管一个读者：

| 档位 | 机制 | UI | 模型 | 持久化 |
| --- | --- | --- | --- | --- |
| 全可见 | 默认 | 可见 | 可见 | 是 |
| 模型不可见 | `bashExecution.excludeFromContext`（`!!`） | 可见 | 丢弃 | 是 |
| UI 不可见 | `custom.display = false` | 隐藏 | 可见 | 是 |

两者不是同一字段的两个取值，而是分别作用在不同消息类型上、互相正交的开关：一个决定「翻译时是否输出」，一个决定「渲染时是否输出」。

关键在最后一列：**所有档位都保留持久化**。`convertToLlm` 里的 `return undefined` 只影响这一次翻译的结果，原始消息仍完整躺在会话历史里——回放、审计、导出、切换模型重发，都能拿到结构化数据。可见性是**翻译时的一次过滤**，不是**写入时的删除**。

这个区别很实际：如果把 `!!` 实现成「执行完不记录」，那会话回放时用户会看到历史里凭空少了一条命令，而载入旧会话又无法恢复。用一个布尔字段表达可见性，代价是每次翻译多一次判断，收益是数据永不丢失、策略永远可改。

### 2.6. 两阶段：transformContext 与 convertToLlm

翻译不是唯一一道工序。`streamAssistantResponse` 里连着两步（agent-loop.ts:397-404）：

```ts
// packages/agent/src/agent-loop.ts:397
// 作用：第一阶段——同层裁剪/改写，输入输出都是 AgentMessage[]
let messages = context.messages;
if (config.transformContext) {
    messages = await config.transformContext(messages, signal); // 作用：可异步，能看全部自定义类型
}

// packages/agent/src/agent-loop.ts:403
// 作用：第二阶段——跨层翻译，输出收窄为 Message[]
const llmMessages = await config.convertToLlm(messages);
```

两阶段的类型签名就是分工说明书：

- `transformContext`：`AgentMessage[] → AgentMessage[]`。同层操作，能读 `bashExecution.output`、能改 `system.toolsAdded`，但产出的仍是内部消息。典型用法是 coding-agent 里剔除被隐藏的工具声明（agent-session.ts:1866-1880）：遍历消息，只处理带 `toolsAdded`/`toolsRemoved` 的 system 消息，过滤掉隐藏项后原样返回同构消息。
- `convertToLlm`：`AgentMessage[] → Message[]`。跨层操作，必须产出供应商能接受的形状，因此必然有损。

**为什么必须分开？** 因为两者的变更频率完全不同。想换裁剪策略（按 token 预算裁历史、按工具集投影、按时间窗截断），只动第一阶段，翻译器一行不改；想换应用（比如接入一个新的终端产品、自定义出 3 个新 role），只动翻译器与声明合并，裁剪逻辑不受影响。若合成一步，「裁剪 + 翻译」会被焊死在一个函数里，任何一边的改动都要重新验证另一边。

还有一个细节支持这个判断：`convertToLlm` 并不只在 Loop 里被调用。压缩摘要在生成摘要前也要把历史翻成 LLM 消息（compaction.ts:721、1076），会话在解析模型时也会调用它（agent-session.ts:621）。它是个**可独立调用的纯函数**，而不是 Loop 的私有步骤——这才让「同一份历史，多种消费方式」成为可能。

### 2.7. 签名透传：有损单向的另一半原因

`AssistantMessage` 的内容块上挂着三个不透明的签名字段：

```ts
// packages/ai/src/types.ts:430
// 作用：文本块——textSignature 是供应商给的元数据（旧版 id 字符串或 TextSignatureV1 JSON）
export interface TextContent {
    type: "text";
    text: string;
    textSignature?: string; // 作用：多轮回传时必须原样带回，否则供应商可能拒绝
}

// packages/ai/src/types.ts:436
// 作用：思考块——thinkingSignature 是加密后的推理重放数据
export interface ThinkingContent {
    type: "thinking";
    thinking: string;
    thinkingSignature?: string; // 作用：不透明载荷，只能存不能解析
    redacted?: boolean;         // 作用：被安全过滤时，加密数据就在 signature 里
}

// packages/ai/src/types.ts:452
// 作用：工具调用块——Google 特有，复用思考上下文用的不透明签名
export interface ToolCall {
    type: "toolCall";
    id: string;
    name: string;
    arguments: JsonObject;
    thoughtSignature?: string; // 作用：Google-specific，必须逐字节回传
}
```

这些字段的共同点是：**模型与供应商生成，Pi 不解释，但下一轮必须原样回传**。它们可能携带加密的推理状态（`redacted` 时的 `thinkingSignature`），一旦被重新序列化、拼接、截断，多轮对话就可能失效或被拒。

所以 `convertToLlm` 对 `assistant` 的处理是 `return m`——整个对象原样透传，连浅拷贝都不做。反过来也说明为什么这层翻译**不能反向**：如果某人想写一个 `convertFromLlm` 把 `UserMessage` 还原成 `BashExecutionMessage`，他不仅猜不出 `exitCode`，还可能破坏 assistant 消息上的签名完整性。有损单向不是能力不足，是**合同约束**——内层才是真相，外层只是投影。

## 3. 三、设计思想与可迁移要点

**内层结构化，出口翻译。** 整套设计的支点只有一句：内部按消费者（UI、回放、统计）的需要建模，边界处按协议（供应商 API）的需要翻译。`Message` 是协议，`AgentMessage` 是模型；`convertToLlm` 是应用层那条主要的、可测试的边界（核心包另有只保留 4 种标准 role 的默认实现）。任何「前端富、后端严」的边界都能套用这个形状——富文本邮件导出纯文本、事件溯源里的事件投影成读模型、埋点数据聚合成报表行，都是同一件事：**富表示留在内层，严表示生成在出口，翻译函数保持纯函数且可被多方复用**。

**核心零依赖，应用层声明合并。** `pi-agent-core` 不知道 `bashExecution` 存在，也不该知道。它只提供 `CustomAgentMessages` 这个空接口作为扩展点，应用层用 `declare module` 注入自己的 role，联合类型自动拓宽，应用层的 switch 对 8 种 role 做穷尽检查。结果是依赖方向永远单向：核心包不需要 import 产品包，产品包也不需要 fork 核心包来加类型。这种「用类型系统的开放接口换运行时零耦合」的手法，比自己维护一个 `type: string` 的松散字段强得多——后者放弃的正是编译期安全。

**可见性是一个布尔字段，不是一次删除。** `excludeFromContext` 与 `display` 各管一个读者，互不干扰，且都不触碰持久化。这让「同一条记录对不同消费者呈现不同面貌」变成一个可组合的小问题：两个布尔值，四种组合，零数据丢失。相比「按需删数据」的实现，它的代价只是翻译时多一次判断，收益却是策略随时可改、历史永远完整。

**有损才敢单向。** 承认翻译是有损的，反而让接口变干净：不需要双向同步，不需要考虑「翻译回来是否一致」，不需要为每种 role 写一对互逆函数。代价是所有结构化消费必须读原始消息——而这恰恰是对的，因为原始消息才是真相。

## 4. 重点总结

- 标准消息是 **4 种**（`system` / `user` / `assistant` / `toolResult`，ai/types.ts:569/587/593/648，联合在 667），`system` 是一等公民，因为它承载可重放的提示词与工具状态变更。
- `AgentMessage = Message | CustomAgentMessages[keyof CustomAgentMessages]`（agent/types.ts:374）；`CustomAgentMessages` 默认空（365），coding-agent 用声明合并注入 4 种（messages.ts:70-77），本构建下共 8 种。
- 4 种自定义消息：`BashExecutionMessage`（29-40，含 `excludeFromContext`）、`CustomMessage`（46-53，含 `display`）、`BranchSummaryMessage`（55-60）、`CompactionSummaryMessage`（62-67）。
- `convertToLlm`（148-196）按 role 分派：`bashExecution` 先过 `excludeFromContext` 闸门，再由 `bashExecutionToText`（82-98）降维成 `UserMessage`；`custom` 转 user 并丢弃 `details`/`display`；两种摘要加前后缀（11-24）包成 `<summary>` 的 user；4 种标准消息原样透传；`default` 用 `const _: never` 穷尽检查；末尾 `filter` 剔除 `undefined`。
- 两阶段分工：`transformContext`（agent-loop.ts:399-401）同层裁剪改写 `AgentMessage[] → AgentMessage[]`，`convertToLlm`（404）跨层翻译 `AgentMessage[] → Message[]`；翻译器还是纯函数，压缩与会话解析都会直接调用。
- 签名字段 `textSignature`（433）、`thinkingSignature`（439）、`thoughtSignature`（457）必须逐字回传，因此 assistant 只能原样透传，翻译是**有损单向**，不可逆。
- 可见性三档（全可见 / 模型不可见 / UI 不可见）都基于字段而非删除，持久化永远保留。

## 5. 参考

- [pi 仓库](https://github.com/earendil-works/pi)
- [packages/ai/src/types.ts](https://github.com/earendil-works/pi/blob/main/packages/ai/src/types.ts)（`SystemMessage` :569、`UserMessage` :587、`AssistantMessage` :593、`ToolResultMessage` :648、`Message` :667、`textSignature` :433、`thinkingSignature` :439、`thoughtSignature` :457）
- [packages/agent/src/types.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/types.ts)（`CustomAgentMessages` :365、`AgentMessage` :374）
- [packages/agent/src/agent-loop.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts)（`streamAssistantResponse` 的两阶段转换 :397-404）
- [packages/coding-agent/src/core/messages.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/messages.ts)（摘要前后缀 :11-24、4 种自定义消息 :29-67、声明合并 :70-77、`bashExecutionToText` :82-98、`convertToLlm` :148-196）
- [packages/coding-agent/src/core/agent-session.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/agent-session.ts)（`executeBash` 的 `excludeFromContext` 选项 :4011、`recordBashResult` :4053、`transformContext` 投影示例 :1866）
- [packages/coding-agent/src/core/compaction/compaction.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/compaction/compaction.ts)（摘要流程直接调用 `convertToLlm` :721、:1076）
