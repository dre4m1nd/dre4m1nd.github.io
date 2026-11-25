---
title: Pi 源码解读（三）：模型调用层——一行 streamSimple 背后的查表与翻译
slug: pi-model-layer
date: 2026-11-16 19:24:45
description: 深入 Pi 的模型调用层：streamSimple 一行背后的三层结构——查表派活的统一入口、12 种事件协议，以及各厂商翻译器的请求翻译、SSE 自解析、思考级别映射与缓存打点。
categories:
  - 技术
tags:
  - 专栏
  - Pi 源码解读
  - TypeScript
cover: /img/2026/11/pi-model-layer.jpg
---

> 在 Pi 里调用模型，入口永远只有一行 `streamSimple(model, context, { reasoning })`，但这一行背后是三层结构：查表派活的统一入口、12 种事件协议，以及各厂商翻译器的请求翻译、SSE 自解析、思考级别映射与缓存打点。这篇顺着一次调用，把这三层逐段拆开。

## 1. 一、基础与进阶用法

### 1.1. 一个问题：同一段对话，四种私有格式

在 Pi 里调用一个模型，入口永远只是一行：`streamSimple(model, context, { reasoning: "medium" })`。调用方不必关心模型背后是 Anthropic、OpenAI、Google 还是 Bedrock，但四家厂商的线上协议（wire format）彼此完全不兼容。同一段「用户说一句话、模型回一段话」的对话，落到各家请求体里是四种互不相同的写法：

- **Anthropic**：消息的 `content` 是内容块数组，每块带 `type`——文本是 `{ type: "text", text }`，工具调用是 `tool_use`，工具结果是 `tool_result`。角色只有 user/assistant 两种，工具结果以块的形式塞进 user 消息。
- **OpenAI（Chat Completions）**：每条消息是独立对象，`role` 是独立字段（`system` / `user` / `assistant` / `tool`），文本内容通常是字符串或 content part 数组，工具调用是独立的顶层消息。
- **Google（Gemini）**：content 由 `parts` 数组构成，文本、函数调用、函数响应都放在 parts 里，角色用 `role` 标记。
- **Bedrock（Converse）**：同样以 content block 数组组织，但 block 上没有 Anthropic 那样的 `type` 字段，文本块就是一个 `text` 字段。

如果让业务代码直接面对这四种格式，光消息转换就要写四套、流式解析再写四套。Pi 的做法是把「格式」全部收进模型调用层，业务层只面对一套统一的类型与事件。

### 1.2. 一行 streamSimple 背后的三层结构

`streamSimple` 不是某个翻译器的入口，而是三层结构的最外层：

1. **统一入口层**（`compat.ts`）：查表派活。拿到 model 后，先判断有没有内置 provider 直接处理，再做 Cloudflare 特判，最后用 `resolveApiProvider(model.api)` 在注册表里查表，把调用派发给对应的翻译器。
2. **事件协议层**（`types.ts`）：12 种 `AssistantMessageEvent` 事件。无论底层是 SSE 还是 SDK 流，翻译器输出的永远是同一套 start / delta / end / done / error 事件，上层 UI、agent loop 只认这一种协议。
3. **翻译器层**（`api/*.ts`）：每个 API 一份实现，内部都是五步骨架——建客户端 → 请求翻译 → 发送 → 响应翻译 → push done/error。

## 2. 二、源码拆解

### 2.1. 统一入口：查表派活

注册发生在模块加载时。`compat.ts:180` 的 `BUILTIN_APIS` 把内置 API 和它们的 stream 实现绑在一起：

```ts
// compat.ts:180
// 作用：内置 API 清单，[api id, 翻译器] 二元组，模块加载时据此注册到注册表
const BUILTIN_APIS: [Api, ProviderStreams][] = [
	["anthropic-messages", anthropicMessagesApi()],
	["openai-completions", openAICompletionsApi()],
	// ... 其余八个内置 API
];
```

`registerApiProvider`（`compat.ts:128`）是第三方扩展的注册口，用 `api` 作为 Map 的 key：

```ts
// compat.ts:128
// 作用：把 provider 存入 apiProviderRegistry，key 就是 model.api
apiProviderRegistry.set(provider.api, {
	provider: {
		api: provider.api,
		stream: wrapStream(provider.api, provider.stream),          // 作用：包一层 stream 签名
		streamSimple: wrapStreamSimple(provider.api, provider.streamSimple), // 作用：包一层 streamSimple 签名
	},
	sourceId,
});
```

`stream`（`compat.ts:252`）的派活顺序值得逐行看：

```ts
// compat.ts:252
// 作用：统一流式入口，决定这次调用走内置通道还是注册表查表
export function stream<TApi extends Api>(
	model: Model<TApi>,
	context: Context,
	options?: ProviderStreamOptions,
): AssistantMessageEventStream {
	const transcript = normalizeContext(context);             // 作用：把原始 context 规范化为 TranscriptContext
	const builtinProvider = getBuiltinProviderForModel(model); // 作用：判断该 model 是否命中内置 provider
	if (builtinProvider) {
		if (model.provider.startsWith("cloudflare-") && !hasResolvedCloudflareAuth(options)) {
			return compatModels.stream(model, transcript, ...); // 作用：Cloudflare 特判，未带显式鉴权走兼容通道
		}
		return builtinProvider.stream(model, transcript, withEnvApiKey(model, options)); // 作用：内置通道，注入环境变量 API key
	}
	const provider = resolveApiProvider(model.api);           // 作用：按 model.api 查注册表，找不到直接抛错
	return provider.stream(model, transcript, withEnvApiKey(model, options));
}
```

`streamSimple`（`compat.ts:278`）结构相同，区别是转发给翻译器的 `streamSimple`——它负责思考级别的翻译，比如 Anthropic 适配器把统一思考级别翻成 effort 或 thinking budget，OpenAI 适配器先做 clamp 再映射成 `reasoningEffort`（见下文）。

### 2.2. 事件协议：12 种事件

`AssistantMessageEvent`（`types.ts:831`）定义了流式输出的全部事件，共 12 种：

```ts
// types.ts:831
// 作用：流式事件协议，所有翻译器必须产出这套事件，上层只认它
export type AssistantMessageEvent =
	| { type: "start"; partial: AssistantMessage }                  // 作用：流开始，带当前部分结果
	| { type: "text_start"; contentIndex: number; partial }        // 作用：一个 text 块开始
	| { type: "text_delta"; contentIndex: number; delta: string }  // 作用：text 增量
	| { type: "text_end"; contentIndex: number; content: string }  // 作用：text 块结束（权威全文）
	| { type: "thinking_start"; contentIndex: number; partial }    // 作用：思考块开始
	| { type: "thinking_delta"; contentIndex: number; delta: string } // 作用：思考增量
	| { type: "thinking_end"; contentIndex: number; content: string } // 作用：思考块结束
	| { type: "toolcall_start"; contentIndex: number; partial }    // 作用：工具调用块开始
	| { type: "toolcall_delta"; contentIndex: number; delta: string } // 作用：工具参数 JSON 增量
	| { type: "toolcall_end"; contentIndex: number; toolCall: ToolCall } // 作用：工具调用块结束
	| { type: "done"; reason: ...; message: AssistantMessage }     // 作用：正常收尾，reason 为 stop/length/toolUse/deferred
	| { type: "error"; reason: "aborted" | "error"; error: AssistantMessage }; // 作用：异常收尾
```

协议注释还约定了时序：`start` 必须先于一切增量事件；`partial` 是「到目前为止的活响应」而非事件时刻的快照，块在 `*_start` 时为空、随 `*_delta` 增长，直到 `*_end` 给出权威全文。

### 2.3. StreamFunction 的三条签名规则

`StreamFunction`（`types.ts:406`）是每个翻译器实现的函数签名，文档注释里写明了三条规则：

```ts
// types.ts:397-405
// 作用：StreamFunction 的契约注释
// - 输入相同：收到规范化 transcript，system prompt 与 tools 都在首条 system 消息里
// - 输出相同：必须返回 AssistantMessageEventStream
// - 错误不抛：一旦返回流，请求/模型/运行时失败都编码进流内，以 stopReason "error"/"aborted" 终止
export type StreamFunction<TApi extends Api = Api, TOptions extends StreamOptions = StreamOptions> = (
	model: Model<TApi>,
	context: TranscriptContext,
	options?: TOptions,
) => AssistantMessageEventStream;
```

配套的 `StopReason`（`types.ts:497`）是终止原因的统一枚举：`"pending" | "stop" | "length" | "toolUse" | "error" | "aborted" | "deferred"`。查表的 key 就是 `model.api`——`KnownApi`（`types.ts:64`）枚举了十个内置 API id，注册与派发全靠这个字符串对齐。

### 2.4. 翻译器：五步骨架

以 Anthropic 翻译器为例，`stream`（`anthropic-messages.ts:808`）内部是一个 async IIFE，五步清晰可辨：

1. **建客户端**：`createClient(...)`（`:866`）创建 Anthropic SDK 客户端，处理 OAuth 与 federation；
2. **请求翻译**：`buildParams(...)`（`:897`）把统一 transcript 翻成 Anthropic 的 `MessageCreateParamsStreaming`；
3. **发送**：`send(params)`（`:884-889`）发起 `beta.messages.create`，带重试与 signal；
4. **响应翻译**：`stream.push({ type: "start", ... })`（`:942`）之后逐事件翻译增量；
5. **push done|error**：正常结束 push `done`，catch 里 push `error`。

### 2.5. 请求翻译与响应翻译：SSE 自解析 vs SDK 流

**请求侧**，Anthropic 的消息转换在 `convertMessages`（`anthropic-messages.ts:1617`），文本消息被翻成 content 块数组：

```ts
// anthropic-messages.ts:1692
// 作用：把统一的 user 消息翻译成 Anthropic 的 content[]+type 格式
params.push({
	role: "user",
	content: filteredBlocks, // 作用：每个块带 type，如 { type: "text", text }
});
```

OpenAI 翻译器的 `convertMessages`（`openai-completions.ts:1184`）则是另一种形态——独立 role 消息：

```ts
// openai-completions.ts:1258
// 作用：翻译成 OpenAI 的独立 role 消息，文本内容直接是字符串
params.push({
	role: "user",
	content: sanitizeSurrogates(msg.content),
});
```

**响应侧**，两种翻译器代表了两种流式解析路线。Anthropic 不依赖 SDK 的事件封装，而是自己逐行解析原始 SSE。`decodeSseLine`（`anthropic-messages.ts:653`）：

```ts
// anthropic-messages.ts:653
// 作用：解析一行 SSE——空行触发事件冲刷，":" 开头是注释，按字段名收集 event/data
function decodeSseLine(line: string, state: SseDecoderState): ServerSentEvent | null {
	if (line === "") {
		return flushSseEvent(state);   // 作用：空行代表一个事件结束，冲刷出完整事件
	}
	state.raw.push(line);
	if (line.startsWith(":")) {
		return null;                   // 作用：SSE 注释行，直接忽略
	}
	// ... 按 "field: value" 切分
	if (fieldName === "event") {
		state.event = value;           // 作用：记录事件类型
	} else if (fieldName === "data") {
		state.data.push(value);        // 作用：累积数据行
	}
	return null;
}
```

`iterateSseMessages`（`:708`）用 `TextDecoder` 流式解码字节流、按行切分；`iterateAnthropicEvents`（`:767`）再过滤出六种 Anthropic 事件、做 JSON 解析，并校验 `message_stop` 是否出现，否则抛错。OpenAI 则直接消费 SDK 返回的结构化 chunk 流，解析的是已经成型的 `ChatCompletionChunk`，无需自己处理行分隔。

**响应翻译**把各家事件统一翻成 12 种事件：Anthropic 的 `content_block_start/delta/stop` 分别触发 `text_start/text_delta/text_end`（`:977-1085`），`message_delta` 里的 `stop_reason` 映射成统一 `stopReason`（`:1090-1093`）。

### 2.6. 思考级别：六级映射与 clamp 回退

`ThinkingLevel` 是统一枚举，本地快照中定义在 agent 包 `types.ts:349`：`"off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max"`，业务层常用的是其中六级（off/minimal/low/medium/high/xhigh）。`SimpleStreamOptions.reasoning`（`types.ts:388`）直接接受这个类型。每个模型的 `Model.thinkingLevelMap`（`types.ts:876`）是一张映射表，把统一级别映射成该模型/厂商支持的具体值：

```ts
// types.ts:872-876
// 作用：Model 上的思考级别映射表，缺失的级别走 provider 默认值，null 表示该级别不支持
thinkingLevelMap?: ThinkingLevelMap;
```

Anthropic 适配器先查表，查不到再按级别回落（`mapThinkingLevelToEffort`，`anthropic-messages.ts:1184`）：

```ts
// anthropic-messages.ts:1184
// 作用：把统一 ThinkingLevel 映射为 Anthropic 的 effort 级别
const mapped = level ? model.thinkingLevelMap?.[level] : undefined;
if (typeof mapped === "string") return mapped as AnthropicEffort; // 作用：优先使用映射表的值
switch (level) {
	case "minimal":
	case "low":
		return "low";  // 作用：minimal/low 都归到 low
	case "medium":
		return "medium";
	case "high":
		return "high";
	default:
		return "high"; // 作用：无法识别时保守回落到 high
}
```

OpenAI 适配器则在调用前先做 clamp：`clampThinkingLevel(model, options.reasoning)`（`openai-completions.ts:731`，该函数定义于 `models.ts`，在文件 `:14` 导入），策略是先向上找到模型支持的最高级别，再向下回退到最近的受支持档位，保证请求不会因级别不支持而失败。

### 2.7. 缓存打点：同一语义，三种落点

`cacheRetention?: CacheRetention`（`types.ts:252`）是统一语义抽象（`none/short/long`），各家翻译器把它翻译成自己的缓存机制。Anthropic 打点 `cache_control: { type: "ephemeral" }` 有三处：

1. **system 部分**（`anthropic-messages.ts:1494/1501/1510`）：system 的各个文本块都带上 `cache_control`——OAuth 的 Claude Code 身份块（首个）、OAuth 与非 OAuth 两路的 `initialSystemText`；
2. **最后一个 tool**（`:1936`）：工具定义列表的末位工具带 `cache_control`（`index === tools.length - 1` 时打点）；
3. **最新一条 user 消息**（`:1795-1821`）：做 rolling 打点，每轮请求都把缓存断点滚动到最新位置：

```ts
// anthropic-messages.ts:1795
// 作用：在最后一条 user/system 消息的最后一个内容块上打 cache_control 缓存断点
if (cacheControl && params.length > 0) {
	const lastMessage = params[params.length - 1];
	if (lastMessage.role === "user" || lastMessage.role === "system") {
		if (Array.isArray(lastMessage.content)) {
			const lastBlock = lastMessage.content[lastMessage.content.length - 1];
			if (lastBlock && (lastBlock.type === "text" || lastBlock.type === "image" || ...)) {
				(lastBlock as any).cache_control = cacheControl; // 作用：断点落在最后一个块上
			}
		}
	}
}
```

retention 为 `long` 且模型支持时，TTL 升级为 `"1h"`（`:101-104`）。Bedrock 的翻译器插的是 `cachePoint` 节点，OpenAI 走请求级 `prompt_cache_key`：

```ts
// openai-completions.ts:819
// 作用：OpenAI 把缓存语义翻译成 prompt_cache_key，绑定会话以复用前缀缓存
prompt_cache_key:
	cacheRetention !== "none" && supportsPromptCacheKey
		? clampOpenAIPromptCacheKey(options?.sessionId)
		: undefined,
```

### 2.8. 错误注入：异常编码进流

翻译器的 catch 把异常翻译成流内事件，而不是抛出去：

```ts
// anthropic-messages.ts:1168
// 作用：catch 中根据 signal 判断中止还是错误，把异常编码进流协议
} catch (error) {
	output.stopReason = options?.signal?.aborted ? "aborted" : "error"; // 作用：中止与错误统一编码进 stopReason
	output.errorMessage = error instanceof Error ? withCauseDetail(error) : JSON.stringify(error);
	stream.push({ type: "error", reason: output.stopReason, error: output }); // 作用：以 error 事件收尾
	stream.end();
}
```

OpenAI 翻译器同样如此（`openai-completions.ts:696-713`）：先给未完成的思考块补 reasoning details，再按 `signal.aborted` 判定 `aborted`/`error`，push `error` 事件后 `end()`。上层拿到流之后无论成功失败，读取的都是同一个 `AssistantMessage` 结构。

## 3. 三、设计思想

**协议 > 实现。** 整个模型调用层没有抽象基类。`StreamFunction` 只是一个函数类型签名（`types.ts:406`），Anthropic、OpenAI、Google、Bedrock 各写各的翻译器，靠「实现同一个签名、产出同一套事件」来对齐，而不是继承某个基类、实现某个接口。协议用类型写出来，比抽象类更轻：新增一个厂商，只需新增一个函数，并在 `BUILTIN_APIS` 里注册一行。

**统一枚举 + 映射表。** 思考级别、停止原因、API id 都是统一枚举（`ThinkingLevel`、`StopReason`、`KnownApi`），差异不散落在业务代码里，而是收进每张模型上的映射表（`thinkingLevelMap`、`promptCache`）。查表失败时有确定的回落策略（Anthropic 按级别回落、OpenAI 先 clamp 再映射），语义集中、行为可预测。

**语义统一，实现分散。** `cacheRetention` 这一个选项，Anthropic 翻译成三处 `cache_control` 打点，Bedrock 翻译成 `cachePoint` 节点，OpenAI 翻译成 `prompt_cache_key`；`reasoning` 一个选项，各家翻译成 effort、budget 或 `reasoning_effort`。统一层只承诺语义（缓存多久、思考多深），具体落点由翻译器按各家协议实现。业务代码从此不必知道任何一家的线上格式。

## 4. 重点总结

- 模型调用层是三层结构：`compat.ts` 的查表入口、`types.ts` 的 12 种事件协议、`api/*.ts` 的翻译器。
- `stream`/`streamSimple` 的派活顺序：内置 provider → Cloudflare 特判 → `resolveApiProvider(model.api)` 查表；`model.api` 就是查表 key。
- `StreamFunction` 三条规则：输入相同、输出相同、错误不抛——失败编码进流，以 `stopReason: "error"/"aborted"` 的 `error` 事件收尾。
- 响应侧两条路线：Anthropic 自解析原始 SSE 逐行解码，OpenAI 消费 SDK 结构化 chunk，但都翻译成同一套 12 种事件。
- 思考级别六级统一枚举，靠 `thinkingLevelMap` 映射表 + `clampThinkingLevel` 回退策略消化厂商差异。
- 缓存打点三种落点：Anthropic 三处 `cache_control`（system 末尾 / 最后一个 tool / 最新 user 滚动）、Bedrock `cachePoint` 节点、OpenAI `prompt_cache_key`。

## 5. 参考

- [earendil-works/pi 仓库](https://github.com/earendil-works/pi)
- [packages/ai/src/compat.ts](https://github.com/earendil-works/pi/blob/main/packages/ai/src/compat.ts)
- [packages/ai/src/types.ts](https://github.com/earendil-works/pi/blob/main/packages/ai/src/types.ts)
- [packages/ai/src/models.ts](https://github.com/earendil-works/pi/blob/main/packages/ai/src/models.ts)
- [packages/ai/src/api/anthropic-messages.ts](https://github.com/earendil-works/pi/blob/main/packages/ai/src/api/anthropic-messages.ts)
- [packages/ai/src/api/openai-completions.ts](https://github.com/earendil-works/pi/blob/main/packages/ai/src/api/openai-completions.ts)
