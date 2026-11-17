---
title: "Pi 源码解读（二）：工具系统——五步管道与「错误即消息」"
date: 2026-11-16 12:00:00
description: 从 Tool、AgentTool、ToolDefinition 三层类型出发，逐段拆解 Pi 的工具执行五步管道：参数预处理、TypeBox 校验、前置钩子、执行与进度回调、后置钩子，并讲透「错误即消息」的设计取舍。
categories:
  - 技术
tags:
  - pi
  - 源码解读
  - TypeScript
cover: /img/2026/11/pi-tool-pipeline.jpg
---

上一篇我们读完了 Agent Loop 的主循环，这一篇聚焦其中最值得反复看的部分：**工具系统**。模型输出一个 `ToolCall` 之后，到它变成一条 `ToolResultMessage` 塞进会话历史之前，中间经过了一条严格的五步管道。本文先看工具类型的分层，再逐段拆管道，最后聊这套设计可以带走的思想。

## 1. 一、基础与进阶用法

### 1.1. 一次工具调用的旅程

模型在 `AssistantMessage` 里产出 `toolCall` 内容块，Loop 把这些调用收集起来，交给 `executeToolCalls`（agent-loop.ts:518）。它按 `executionMode` 决定走串行还是并行调度（agent-loop.ts:526-532，具体调度在第一篇讲过，这里不展开），无论哪条路，每个调用最终都被塑形成同一种结果：`ToolResultMessage`。这条消息会连同 `isError` 标志一起回灌给模型，成为下一轮推理的输入。

### 1.2. 三层工具类型：各管一段

Pi 把工具拆成三层，每层只暴露自己这一层需要的能力：

```ts
// packages/ai/src/types.ts:779
// 作用：最内层 Tool——只描述「给模型看什么」，纯声明，不含任何执行逻辑
export interface Tool<TParameters extends object = object> {
    name: string;                       // 作用：模型调用时使用的唯一标识
    description: string;                // 作用：模型据以判断何时调用的说明
    parameters: TParameters;           // 作用：参数的 JSON Schema，即 JSON Schema 本身
    constrainedSampling?: false | ConstrainedSamplingConfig; // 作用：可选地约束采样格式
}
```

第二层是执行层 `AgentTool`，挂在 agent 包（agent/src/types.ts:478）：

```ts
// packages/agent/src/types.ts:478
// 作用：AgentTool 继承 Tool，增加「给 Loop 执行什么」的字段
export interface AgentTool<TParameters extends object = object, TDetails = any> extends Tool<TParameters> {
    label: string;                       // 作用：给人看的展示名（UI 显示）
    prepareArguments?: (args: unknown) => AgentToolParams<TParameters>; // 作用：校验前修正原始参数
    outputSchema?: object;               // 作用：成功结果里 structuredContent 的 schema
    execute: (                          // 作用：真正执行，失败可 throw，也可返回 isError: true
        toolCallId: string,
        params: AgentToolParams<TParameters>,
        signal?: AbortSignal,
        onUpdate?: AgentToolUpdateCallback<TDetails>, // 作用：执行中推增量进度给 UI
    ) => Promise<AgentToolResult<TDetails>>;
    replay?: "never" | "safe";            // 作用：对「意图已持久化但结果未知」的副作用给出重放策略
    executionMode?: ToolExecutionMode;  // 作用：本工具的并行/串行调度策略
}
```

第三层是产品层 `ToolDefinition`，在 coding-agent 里定义，除执行字段外还携带 `promptSnippet`、`promptGuidelines`（注入系统提示）、`renderShell` 等展示字段，以及执行期注入的 `ctx`（`ExtensionToolContext`）。**为什么要分三层？** 本质是依赖范围的收束：`pi-ai` 只负责把 `Tool` 声明发给模型提供商，它不能、也不应该依赖终端 UI 或工作区；`AgentTool` 只负责执行契约，不理解产品展示；产品层的自由度被压在 `ToolDefinition` 里，再通过一个包装函数降级回 `AgentTool`。

### 1.3. 用闭包注入 ctx：Loop 永远不知道 ctx 的存在

`wrapToolDefinition`（tool-definition-wrapper.ts，全文仅 77 行）就是这层「降级」的胶水：

```ts
// packages/coding-agent/src/core/tools/tool-definition-wrapper.ts:27
// 作用：把带 UI/提示词元数据与扩展上下文的 ToolDefinition 包成 AgentTool
export function wrapToolDefinition<TDetails = unknown>(
    definition: ToolDefinition<any, TDetails>,
    ctxFactory?: ToolContextFactory,
): AgentTool<any, TDetails> {
    return {
        name: definition.name,               // 作用：逐字段透传给 AgentTool
        label: definition.label,
        description: definition.description,
        parameters: definition.parameters,
        outputSchema: definition.outputSchema,
        constrainedSampling: definition.constrainedSampling,
        prepareArguments: definition.prepareArguments,
        executionMode: definition.executionMode,
        // 作用：闭包在第 5 个参数上偷渡 ctx——Loop 只按 4 个参数调用，
        // 传进来的 ctx 恒为 undefined，于是由 ctxFactory 现造一个
        execute: (toolCallId, params, signal, onUpdate, ctx?: ExtensionToolContext) =>
            definition.execute(
                toolCallId,
                params,
                signal,
                onUpdate,
                ctx ?? (ctxFactory?.(toolCallId, signal) as ExtensionToolContext), // 作用：缺省时按调用现场创建上下文
            ),
    };
}
```

关键点在于：**Loop 一侧的 `execute` 签名只有 4 个参数**（见下文 agent-loop.ts:835），产品层的 `ctx`（含工具列表、`executeTool` 等）由闭包在包装边界注入，核心运行时对扩展体系零感知。这就是三层划分的直接收益——依赖是单向的，核心不需要 import 产品层。

## 2. 二、源码拆解：五步管道

管道整体是 `prepareToolCall`（第 1~3 步）→ `executePreparedToolCall`（第 4 步）→ `finalizeExecutedToolCall`（第 5 步）。

### 2.1. 第 1 步：prepareArguments——修模型怪癖

```ts
// packages/agent/src/agent-loop.ts:694
// 作用：可选的参数预处理，只发生在 schema 校验之前
function prepareToolCallArguments(tool: AgentTool<any>, toolCall: AgentToolCall): AgentToolCall {
    if (!tool.prepareArguments) {
        return toolCall;                          // 作用：没配预处理就直接用原参数
    }
    const preparedArguments = tool.prepareArguments(toolCall.arguments); // 作用：修正模型输出的原始参数
    if (preparedArguments === toolCall.arguments) {
        return toolCall;                          // 作用：对象未变，复用原调用对象，省一次拷贝
    }
    return {
        ...toolCall,
        arguments: preparedArguments as Record<string, any>, // 作用：只替换 arguments，其余字段保留
    };
}
```

预处理修的是真实存在的模型怪癖。`edit` 工具的实现注释写得很直白（edit.ts:105-118）：部分模型（Opus 4.6、GLM-5.1）会把 `edits` 数组序列化成 JSON 字符串，或者只发单个 edit 对象。`prepareEditArguments` 会先尝试 `JSON.parse`，再把单对象包成数组，让后续校验拿到的是规范结构。注意它运行在校验**之前**——脏数据在这一步就被抚平，而不是让校验器报一个对模型无用的错。

### 2.2. 第 2、3 步：校验与前置钩子

`prepareToolCall` 是管道的入口，串起校验与 `beforeToolCall`：

```ts
// packages/agent/src/agent-loop.ts:718
// 作用：先处理两种「还没执行就注定失败」的情况
    if (signal?.aborted) {                       // 作用：已取消则跳过预处理与钩子
        return {
            kind: "immediate",
            result: createErrorToolResult("Operation aborted"), // 作用：仍然留一条结果，不产生无结果调用
            isError: true,
        };
    }
    const tool = tools.find((t) => t.name === toolCall.name);
    if (!tool) {                                 // 作用：工具未注册
        return {
            kind: "immediate",
            result: createErrorToolResult(`Tool ${toolCall.name} not found`), // 作用：把缺失也变成一条消息
            isError: true,
        };
    }

    try {
        const preparedToolCall = prepareToolCallArguments(tool, toolCall); // 作用：第 1 步
        const validatedArgs = validateToolArguments(tool, preparedToolCall); // 作用：第 2 步，TypeBox 运行时校验
        if (config.beforeToolCall) {             // 作用：第 3 步，前置钩子（如权限检查）
            const beforeResult = await config.beforeToolCall(
                {
                    assistantMessage,           // 作用：发起调用的那条助手消息
                    toolCall,
                    args: validatedArgs,        // 作用：钩子拿到的是已校验的参数
                    context: currentContext,
                },
                signal,
            );
```

钩子可以拦截，也可以要求终止：

```ts
// packages/agent/src/agent-loop.ts:754
// 作用：beforeToolCall 返回 { block: true } 时拦截执行
            if (beforeResult?.block) {
                const result = createErrorToolResult(beforeResult.reason || "Tool execution was blocked"); // 作用：拦截原因作为错误内容
                if (beforeResult.terminate === true) {
                    result.terminate = true;      // 作用：拦截同时可请求终止整批
                }
                return {
                    kind: "immediate",           // 作用：走「即时结果」分支，跳过真正的执行
                    result,
                    isError: true,
                };
            }
```

校验失败或钩子抛错时，外层 `catch`（agent-loop.ts:772-778）同样收敛为 `kind: "immediate"` 的错误结果。三个前置分支全部「即时」——不进入执行，但仍占一条结果消息。

### 2.3. 第 4 步：execute 与进度回调

执行阶段的主角是 `executePreparedToolCall`，重点是 `onUpdate` 与那道「闸门」：

```ts
// packages/agent/src/agent-loop.ts:829
// 作用：执行阶段——收集进度事件，settle 后关闸，丢弃迟到的回调
    const updateEvents: Promise<void>[] = [];     // 作用：暂存每次 onUpdate 的发送 Promise
    let acceptingUpdates = true;                  // 作用：闸门标志，settle 后置 false
    const startedAt = performance.now();          // 作用：计时起点，用于上报耗时

    try {
        const result = await prepared.tool.execute(
            prepared.toolCall.id,                 // 作用：调用 ID，回调事件按它归组
            prepared.args as never,               // 作用：已校验的参数
            signal,                               // 作用：取消信号透传给工具
            (partialResult) => {                  // 作用：进度回调——工具边跑边推增量结果
                if (!acceptingUpdates) return;    // 作用：闸已关，迟到的进度直接丢弃
                updateEvents.push(Promise.resolve(onUpdate(partialResult))); // 作用：异步派发，不阻塞工具
            },
        );
        const durationMs = elapsed();
        acceptingUpdates = false;                // 作用：settle 关闸，之后的回调不再入队
        await Promise.all(updateEvents);         // 作用：先把已受理的进度全部发完，再返回结果
        return { result, isError: result.isError === true, durationMs };
    } catch (error) {
        const durationMs = elapsed();
        acceptingUpdates = false;                // 作用：异常路径同样先关闸
        await Promise.all(updateEvents);         // 作用：先发完进度，再编码错误，UI 不会漏掉过程
        return {
            result: createErrorToolResult(error instanceof Error ? error.message : String(error)), // 作用：异常转成结构化结果
            isError: true,
            durationMs,
        };
    } finally {
        acceptingUpdates = false;                // 作用：双保险，任何出口都关闸
    }
```

这一小段是「错误即消息」最浓的一处：**catch 里先 `await Promise.all(updateEvents)`，再构造错误结果**。工具可能跑了十秒、推了几十条进度，最后才抛错；如果先抛错后清队，前面的进度事件就会随执行上下文一起作废，UI 只剩一个孤零零的报错。先发完进度，模型和用户拿到的都是完整画面。

### 2.4. 第 5 步：afterToolCall——字段级覆盖

```ts
// packages/agent/src/agent-loop.ts:886
// 作用：后置钩子返回值对结果做字段级覆盖，而非整体替换
            if (afterResult) {
                // Structured content not replaced along with the content may no longer match it.
                const structuredContent =                                   // 作用：单独处理结构化内容，避免与 content 不同步
                    afterResult.structuredContent ?? (afterResult.content ? undefined : result.structuredContent);
                result = {
                    ...result,                                             // 作用：保留原结果，逐字段覆盖
                    content: afterResult.content ?? result.content,       // 作用：仅当钩子给了 content 才替换
                    details: afterResult.details ?? result.details,
                    usage: afterResult.usage ?? result.usage,
                    terminate: afterResult.terminate ?? result.terminate, // 作用：钩子可补上终止标记
                };
                if (structuredContent === undefined) delete result.structuredContent; // 作用：content 被换掉时同步清掉失效的结构化内容
                else result.structuredContent = structuredContent;
                isError = afterResult.isError ?? isError;                 // 作用：钩子还能改写错误标志
            }
```

钩子自身抛错则被 catch（agent-loop.ts:901-904）收敛为错误结果。注意 `terminate` 是钩子可以**补写**的字段——这是它与普通覆盖不同的地方。

### 2.5. 错误即消息：六种失败，一个出口

整条管道里，失败永远不会以异常形式逃逸给 Loop，而是统一变成 `isError: true` 的 `ToolResultMessage`：

1. **工具未找到**——`prepareToolCall` 里直接构造（agent-loop.ts:726-732）；
2. **已取消**——`signal.aborted` 短路，返回 "Operation aborted"（进入前 718-724；钩子返回后还会复检一次，747-753）；
3. **预处理抛错**——外层 catch 包装（agent-loop.ts:772-778）；
4. **校验失败**——`validateToolArguments` 抛出，同样被该 catch 捕获；
5. **被拦截**——`beforeToolCall` 返回 `{ block: true }`（agent-loop.ts:754-764）；
6. **execute 抛错**——`executePreparedToolCall` 的 catch（agent-loop.ts:848-856），以及**后置钩子抛错**（agent-loop.ts:901-904）。

出口只有一个 `createErrorToolResult`：

```ts
// packages/agent/src/agent-loop.ts:915
// 作用：错误结果的构造函数——只搬运，不改写、不加戏
function createErrorToolResult(message: string): AgentToolResult<any> {
    return {
        content: [{ type: "text", text: message }], // 作用：错误原因放进正文，模型能直接读到
        details: {},                                // 作用：details 保持空对象，维持结构一致
    };
}
```

它不添加 `isError`（`isError` 由各调用点自行标注），也不吞掉信息——错误文本原样进入消息流，成为模型下一次推理的输入。**错误是给模型的反馈，不是给框架的终止信号**，这是整套设计的核心立场。

工具内部也在主动配合：框架管管道，工具管「把失败讲清楚」。

```ts
// packages/coding-agent/src/core/tools/bash.ts:386
// 作用：把已产生的输出与失败原因打包成一段文本，而不是只抛裸错误
const appendStatus = (text: string, status: string) => `${text ? `${text}\n\n` : ""}${status}`;
```

```ts
// packages/coding-agent/src/core/tools/bash.ts:434
// 作用：非零退出码不算异常，而是返回带状态的 isError 结果
            if (exitCode !== 0) {
                return {
                    content: [{ type: "text", text: appendStatus(outputText, `Command exited with code ${exitCode}`) }], // 作用：输出 + 退出码一起回给模型
                    details,
                    structuredContent,
                    isError: true,                // 作用：明确标记为错误，供框架与 UI 识别
                };
            }
```

`bash` 把「命令已经输出了一半才失败」的场景处理成「已输出内容 + 原因」的完整消息，模型不会因为一个 exit code 而丢失上下文。`read` 则把越界信息讲到位：

```ts
// packages/coding-agent/src/core/tools/read.ts:311
// 作用：Offset 越界时，把文件总行数附在错误里，模型能据此修正下一次读取
if (startLine >= totalFileLines) {
    throw new Error(`Offset ${offset} is beyond end of file (${totalFileLines} lines total)`);
}
```

模型看到 "beyond end of file (142 lines total)" 后会知道该把 offset 改小，而不是盲目重试。错误消息本身就是可操作的反馈。

### 2.6. terminate 的 every 语义

```ts
// packages/agent/src/agent-loop.ts:690
// 作用：一批调用的终止判定——用 every 而非 some
function shouldTerminateToolBatch(finalizedCalls: FinalizedToolCallOutcome[]): boolean {
    return finalizedCalls.length > 0 && finalizedCalls.every((finalized) => finalized.result.terminate === true);
}
```

**全批每个调用都要求停，整批才停**。并行执行时各调用互不阻塞，`some` 会因为某一支的 `terminate` 而误杀还在跑的调用；`every` 让终止成为全体共识。并行/串行如何调度见第一篇，这里只需记住一点：**五步管道发生在每一批的每个调用上**，串并行只是这些调用之间的运行关系，不改变每个调用内部的管道。

## 3. 三、设计思想与可迁移要点

**管道 + 钩子模式。** 固定的五步（预处理 → 校验 → 前置钩子 → 执行 → 后置钩子）封装了「一次工具调用该做什么」的通用逻辑，钩子保留了产品与扩展的注入点。前置钩子能拦、能改参数、能要求终止；后置钩子能做字段级覆盖。核心管道对具体工具一无所知，工具也无需了解管道——这就是 `AgentTool` 四参数契约的威力。

**错误是给模型的反馈，不是给框架的终止信号。** 六种失败路径收敛到同一个 `createErrorToolResult`，异常的语义被刻意压扁为 `isError: true` 的消息。框架不因错误而中断会话，模型拿到的是一段可读、可据此调整下一步行动的文本。配合 catch 里先发完进度的写法，错误既完整又及时。

**Operations 抽象，工具不直接碰底层。** 内置工具通过注入的 `ops` 对象访问文件系统与进程（如 `ops.readFile`、`ops.exec`、`ops.access`），不直接 import `fs`。这让工具逻辑可 mock、可替换——测试时换掉 `ops`，远程场景换成 SSH 实现，工具本身一行不改。`edit` 用 `ops.access` 检查文件存在、`bash` 用 `ops.exec` 拉起命令，都是同一套手法。

**依赖单向分层。** `pi-ai` 不依赖终端 UI，agent 核心不依赖产品层；产品层的丰富性通过 `wrapToolDefinition` 这一层薄闭包收敛成核心认识的 `AgentTool`。当你需要给框架加产品能力时，先问一句「这能力该放在哪一层、由谁来依赖谁」，比先写实现更重要。

## 4. 重点总结

- 工具分三层：`Tool`（给模型看）、`AgentTool`（给 Loop 执行）、`ToolDefinition`（给产品层展示与扩展），分层的依据是依赖范围，而非功能多少。
- `wrapToolDefinition` 用闭包把 `ctx` 偷渡进 `execute` 的第 5 个参数，核心运行时对扩展体系零感知。
- 五步管道：`prepareArguments` 修模型怪癖 → `validateToolArguments` 运行时校验 → `beforeToolCall` 拦截 → `tool.execute` 执行（`onUpdate` 推进度）→ `afterToolCall` 字段级覆盖。
- 六种失败（未找到 / 已取消 / 预处理抛错 / 校验失败 / 被拦截 / execute 或后置钩子抛错）全部收敛为 `isError: true` 的消息；catch 先 `await Promise.all(updateEvents)` 再编码错误，闸门 `acceptingUpdates` 在 settle 后丢弃迟到回调。
- 工具主动包装错误：`bash` 的 `appendStatus` 保留已输出内容，`read` 的越界错误附文件总行数；`createErrorToolResult` 只搬运不改写。
- `terminate` 用 `every`：全批都要求停才停。
- Operations 抽象让工具与底层解耦，可 mock、可替换。

## 5. 参考

- [pi 仓库](https://github.com/earendil-works/pi)
- [packages/agent/src/agent-loop.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts)（`prepareToolCallArguments` :694、`prepareToolCall` :708、`executePreparedToolCall` :824、`finalizeExecutedToolCall` :862、`createErrorToolResult` :915、`shouldTerminateToolBatch` :690）
- [packages/agent/src/types.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/types.ts)（`AgentTool` :478）
- [packages/ai/src/types.ts](https://github.com/earendil-works/pi/blob/main/packages/ai/src/types.ts)（`Tool` :779）
- [packages/coding-agent/src/core/tools/tool-definition-wrapper.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/tool-definition-wrapper.ts)（`wrapToolDefinition` :27）
- [packages/coding-agent/src/core/tools/bash.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/bash.ts)（`appendStatus` :386）
- [packages/coding-agent/src/core/tools/read.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/read.ts)（Offset 越界错误 :312）
- [packages/coding-agent/src/core/tools/edit.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/edit.ts)（`prepareEditArguments` 修数组序列化怪癖）
