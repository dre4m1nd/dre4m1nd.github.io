---
title: Agent Loop：十几行内核撑起一个 Agent
date: 2026-11-16 12:00:00
description: 拆解 earendil-works/pi 的 Agent Loop 源码，看十几行内核如何通过双层循环、stopReason 判停与流式原地替换撑起一个完整的 Agent。
categories:
  - 技术
tags:
  - pi
  - Agent
  - 源码解读
  - TypeScript
  - LLM
cover: /img/2026/11/pi-agent-loop.jpg
---

## 1. 一、基础与进阶用法

pi（earendil-works/pi，MIT 协议）是一个"极简 Agent 内核 + 可插拔产品层"的工具包。理解它的 Agent，从两个文件开始：核心循环 `packages/agent/src/agent-loop.ts`（952 行）与状态封装 `packages/agent/src/agent.ts`（623 行）；内核只做一件事——跑通"调模型 → 执行工具 → 再调模型"的循环。

调用链很直白：`Agent.prompt()` 把用户输入规范化成消息，调用 `runPromptMessages()`（agent.ts:441），后者在生命周期包装里调用 `runAgentLoop(...)`（agent.ts:446）：

```typescript
private async runPromptMessages(
    messages: AgentMessage[],
    options: { skipInitialSteeringPoll?: boolean } = {},
): Promise<void> {
    await this.runWithLifecycle(async (signal) => {
        await runAgentLoop(
            messages,
            this.createContextSnapshot(),
            this.createLoopConfig(options),
            (event) => this.processEvents(event),
            signal,
            this.streamFunction,
        );
    });
}
```

`runAgentLoop` 六个参数各司其职（agent-loop.ts:111）：`prompts` 是本轮注入的新消息；`context` 是运行上下文（消息历史 + 可执行工具集）；`config` 是回调集合；`emit` 是事件出口；`signal` 是中止信号；`streamFn` 是底层模型流函数。值得注意 `context` 的传入方式：`Agent` 通过 `createContextSnapshot()`（agent.ts:469）浅拷贝 `messages` 与 `tools`，循环内所有写入都发生在副本上，消息经由逐条 `message_end` 事件落回宿主（agent.ts:587），`agent_end` 仅表示运行结束并清理流式状态（agent.ts:610-612）。这就是"副本隔离"：内核随意改上下文，宿主状态只在事件确认后更新。

入口先补发 `agent_start`、`turn_start`，把 prompts 逐条以 `message_start`/`message_end` 发出，然后进入主循环（agent-loop.ts:126-133），事件序列全程闭合：

```text
agent_start → (turn_start → message_* → tool_execution_* → turn_end)* → agent_end
```

两个概念要分清：**一次完整运行** 指从 `agent_start` 到 `agent_end` 的整个过程（源码里没有 "trace" 这个术语，这里为行文方便借用）；**Turn（轮）** 指一次 assistant 响应及其引发的全部工具调用与工具结果（types.ts:532 注释原话："a turn is one assistant response + any tool calls/results"）。UI、日志、持久化订阅这套事件序列即可重建现场。

## 2. 二、源码逐段拆解

### 2.1. 最小循环：伪代码与真实代码

剥掉钩子，内核不过十几行伪代码：

```text
while 有更多工具调用或有待处理消息:
    assistant = 调模型(上下文)
    若 assistant.stopReason 是 error/aborted: 硬停
    tools = assistant 中的工具调用
    若 tools 非空: 执行工具，把结果写回上下文
    发 turn_end
若还有后续消息: 继续下一轮
```

真实的双层循环（agent-loop.ts:188-192）与伪代码对应：内层处理"工具接力"，外层处理"接力结束后是否续跑"：

```typescript
while (true) {
    let hasMoreToolCalls = true;

    // Inner loop: process tool calls and steering messages
    while (hasMoreToolCalls || pendingMessages.length > 0) {
```

每圈的核心三步：流式获取 assistant 响应（agent-loop.ts:251）、硬停判断（254 行起）、执行工具调用（272 行起）：

```typescript
const message = await streamAssistantResponse(currentContext, config, signal, emit, streamFunction);
newMessages.push(message);

// Check for tool calls
const toolCalls = message.content.filter((c) => c.type === "toolCall");

const toolResults: ToolResultMessage[] = [];
hasMoreToolCalls = false;
if (toolCalls.length > 0) {
```

### 2.2. stopReason 判停与硬停分支

循环的每次转向都由 `stopReason` 一个字段决定。参与判停的取值中，`stop`、`length`、`toolUse`、`deferred` 来自模型（`done` 事件的 reason 可能是这四种，见 pi-ai 的 `AssistantMessageEvent` 定义）；`error`、`aborted` 则由各 provider 适配器在 `catch` 里注入——出错时适配器把消息改写为对应值再推给流。内核只认这个字段，不关心谁造的。

硬停分支（agent-loop.ts:254-265）：一旦 `error` 或 `aborted`，立刻组装 `lastCompletedTurn`、发 `turn_end` 与 `agent_end`，然后 `return`——**不执行工具、不看 followUp、不进外层续跑**：

```typescript
if (message.stopReason === "error" || message.stopReason === "aborted") {
    lastCompletedTurn = {
        message,
        toolResults: [],
        context: currentContext,
        newMessages,
    };
    await config.finishTurn?.(lastCompletedTurn, signal);
    await emit({ type: "turn_end", message, toolResults: [] });
    await emit({ type: "agent_end", messages: newMessages });
    return;
}
```

另一个分支是 `length`（agent-loop.ts:273-279）：输出被 token 上限截断时，工具参数可能残缺，直接执行等于"执行了坏调用"，所以内核标记为失败并写回错误结果，交由模型重新发起。工具执行在 `executeToolCalls`（agent-loop.ts:518）里按 `config.toolExecution` 分流串行/并行：

```typescript
async function executeToolCalls(
    currentContext: AgentContext,
    assistantMessage: AssistantMessage,
    config: AgentLoopConfig,
    signal: AbortSignal | undefined,
    emit: AgentEventSink,
): Promise<ExecutedToolCallBatch> {
    const toolCalls = assistantMessage.content.filter((c) => c.type === "toolCall");
    const hasSequentialToolCall = toolCalls.some(
        (tc) => currentContext.tools?.find((t) => t.name === tc.name)?.executionMode === "sequential",
    );
    if (config.toolExecution === "sequential" || hasSequentialToolCall) {
        return executeToolCallsSequential(currentContext, assistantMessage, toolCalls, config, signal, emit);
    }
    return executeToolCallsParallel(currentContext, assistantMessage, toolCalls, config, signal, emit);
}
```

真正跑单个工具的是 `executePreparedToolCall`（agent-loop.ts:824），它包住 `tool.execute()`，收集部分更新，并把异常统一转成错误结果——失败不抛异常，只产 `isError: true`。错误结果的统一出口是 `createErrorToolResult`（agent-loop.ts:915）：

```typescript
function createErrorToolResult(message: string): AgentToolResult<any> {
    return {
        content: [{ type: "text", text: message }],
        details: {},
    };
}
```

### 2.3. 流式原地替换：消息条数恒为 1

流式的常见坑是往历史里堆中间态。pi 的做法是**原地替换**：一轮 assistant 消息在 `context.messages` 里恒占一个槽位。`streamAssistantResponse`（agent-loop.ts:390）收到 `start` 时先推空壳（426-431 行）：

```typescript
case "start":
    partialMessage = event.partial;
    context.messages.push(partialMessage);
    addedPartial = true;
    await emit({ type: "message_start", message: { ...partialMessage } });
    break;
```

之后每个 `text_delta`、`toolcall_delta` 等增量事件都用 `event.partial` 整体覆盖最后一个元素（442-451 行），并发出 `message_update`：

```typescript
if (partialMessage) {
    partialMessage = event.partial;
    context.messages[context.messages.length - 1] = partialMessage;
    await emit({
        type: "message_update",
        assistantMessageEvent: event,
        message: { ...partialMessage },
    });
}
```

`done`/`error` 时用最终消息做最后一次覆盖（453-466 行）；若流没有 `start`（`addedPartial` 为 false），则退化为直接 push 最终消息并补发 `message_start`：

```typescript
const finalMessage = await result();
if (addedPartial) {
    context.messages[context.messages.length - 1] = finalMessage;
} else {
    context.messages.push(finalMessage);
}
if (!addedPartial) {
    await emit({ type: "message_start", message: { ...finalMessage } });
}
await emit({ type: "message_end", message: finalMessage });
return finalMessage;
```

UI 看到的是同一条消息逐步刷新，落库历史里只有一条最终消息。

### 2.4. steering 插队与 followUp 外层循环

steering（插队）和 followUp（收尾后续）是产品层叠加，插队检查点由内核安排：进入循环**之前**先问一次（agent-loop.ts:185）；`prepareNextTurn` 长耗时准备后若队列为空再补问一次（213-215 行，避免 one-at-a-time 模式下一轮塞两条）；每圈内层循环**结尾**再查一次（303-307 行）：

```typescript
explicitContinuation = decision?.action === "continue";
pendingMessages = (await config.getSteeringMessages?.()) || [];
if (hasMoreToolCalls || pendingMessages.length > 0) {
    explicitContinuation = false;
}
```

steering 消息在下一圈开头先注入并补发 `message_start`/`message_end`，然后才调模型——插队只发生在"本轮工具完成、下轮模型未开跑"的窗口。内层循环结束后，外层询问 followUp（agent-loop.ts:311-317）：

```typescript
const followUpMessages = (await config.getFollowUpMessages?.()) || [];
if (followUpMessages.length > 0) {
    // Set as pending so inner loop processes them
    explicitContinuation = false;
    pendingMessages = followUpMessages;
    continue;
}
```

### 2.5. 内核与叠加：剥掉叠加仍能跑

拆开看，**内核**只有三样：调模型（`streamAssistantResponse`，含 `convertToLlm` 在调用边界做 `AgentMessage[] → Message[]` 转换，agent-loop.ts:404）、执行工具（`executeToolCalls` 一族）、发 `turn_end`/`agent_end` 闭合事件。这十几行不依赖任何产品。

**叠加层**全部通过 `config` 的可选回调注入：`getSteeringMessages`/`getFollowUpMessages`（队列插队）、`prepareNextTurn`/`prepareRequest`（轮间准备）、`finishTurn`（轮后决策，`action: "end"` 直接终止，"本轮后是否停下"这类判断挂在这）、`beforeToolCall`/`afterToolCall`（权限与结果改写）。全部置为 `undefined`，内核仍能跑通"调模型 → 执行工具 → 判停"的最小闭环——这就是 pi 把内核与产品解耦的方式。

## 3. 三、设计思想与可迁移要点

**判据极简。** 循环转向只依赖两个布尔量：`hasMoreToolCalls` 和 `pendingMessages.length > 0`，外加一个 `stopReason` 字段。没有任务完成度评分、没有状态机枚举，"继续跑"与"停下"完全由它们表达。任意时刻都能回答"为什么还在跑"——要么工具没执行完，要么消息没注入。

**副本隔离。** 入口拷贝 `messages`/`tools`，内核在副本上自由读写，宿主通过逐条 `message_end` 事件接收新消息，`agent_end` 只作为运行结束信号。流式原地替换（2.3 节）也依赖这一前提：中间态可反复覆盖同一槽位而不污染外部状态。写自己的 Agent 时，"内核操作副本、事件驱动落库"远胜"内核直接改宿主状态"，重试、回放、分支都更简单。

**事件序列闭合。** `agent_start → turn_start → message_* → tool_execution_* → turn_end → agent_end` 严格嵌套、成对闭合。UI、持久化、审计层可无差别订阅同一条事件流重建现场，内核与消费者无需共享内部状态。

**内核 + 叠加。** 内核只保留所有 Agent 都需要的最小闭环，产品特性（插队、续跑、轮间准备、权限钩子）以可选回调挂载。可迁移的做法：先写出不依赖任何回调的裸循环，再逐步叠加钩子，每加一个都验证内核行为不变。

## 4. 重点总结

- 调用链为 `Agent.prompt() → runPromptMessages() → runAgentLoop()`；后者接收 `prompts / context / config / emit / signal / streamFn` 六个参数，context 以副本传入。
- 内层 `while (hasMoreToolCalls || pendingMessages.length > 0)` 处理工具接力，外层 `while (true)` 处理 followUp 续跑；steering 在进入循环前、长耗时准备后、每圈结尾三个检查点插队。
- 参与判停的 `stopReason` 取值中，`stop/length/toolUse/deferred` 来自模型，`error/aborted` 由适配器在 catch 中注入；后者走硬停分支，不执行工具、不看 followUp，直接返回。
- 流式原地替换：`start` 推空壳、delta 用 `event.partial` 覆盖 `messages[last]`、`done` 用最终消息覆盖，一轮 assistant 恒占一条。
- 内核只有调模型、执行工具、事件闭合三件事；steering、followUp、prepareNextTurn、finishTurn 等都是可插拔的产品叠加，剥掉后内核仍能运行。

## 5. 参考

- [earendil-works/pi（GitHub，MIT）](https://github.com/earendil-works/pi)
- [packages/agent/src/agent-loop.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts)
- [packages/agent/src/agent.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent.ts)
- [pi 官方文档](https://pi.dev/docs)
