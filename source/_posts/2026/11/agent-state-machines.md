---
title: Agent 状态机：给 agent 加确定性脚手架
date: 2026-11-04
description: agent 的运营规则不该写在 prompt 里让模型自觉遵守。这篇拆 Josh Rosen 的四层状态机——推理循环内、工作流、监督多个 agent、建模工作本身——讲清两种 checkpoint 的区别、为什么大家最后还是自己写，以及最小实现怎么和 harness 接线。
categories:
  - 折腾
tags:
  - AI
  - Agent
  - 架构
cover: /img/agent-state-machines.jpg
---

## 摘要

**如果你不用某种 agent 状态机，你就完全被模型的非确定性摆布。** 让模型自己决定下一步做什么动作、什么时候算完成——你真的放心吗？大多数 agent 是一个 `while` 循环：收 prompt、决定调不调工具、处理结果、重复到它觉得完成。单会话里这够用，可一旦要按流程走、处理外部事件、跨会话继续、动作前审批、工具失败恢复、完成前校验，把这些规则写进 prompt 就等于**把运营规则交给模型自觉遵守**。状态机做的事只有一件：把规则搬到模型外面——模型可以**提议**动作和转移，允不允许由外围软件决定。

## 一、简单循环的天花板

先看那个几乎所有 agent 框架都长得一样的骨架：

```ts
while (true) {
  const reply = await model.chat(messages)
  if (reply.toolCall) {
    messages.push(await runTool(reply.toolCall))
    continue
  }
  if (reply.saysDone) break        // ← 完成由模型自己宣布
  messages.push(reply)
}
```

这个循环有三个隐含决定，全交给了模型：**下一步做什么、能不能做、做完了没有**。

单会话、单任务、失败就重来时，这三个决定交给模型是合理的——它比任何硬编码的 if-else 都灵活。问题出在你开始有"流程"的时候：

- **要按流程走**：先方案、再实现、再验证、最后才允许提交；
- **要处理外部事件**：PR 来了、CI 红了、issue 被重新打开；
- **要跨会话继续**：昨天的活今天接着做，不能从头再来；
- **动作前要审批**：删库、发版、改生产配置，必须有人点头；
- **工具失败要恢复**：重试、降级、放弃，得有个上限；
- **完成前要校验**：模型说"做完了"不算做完。

这六条只要有一条成立，你就得在 prompt 或 skill 里写规则："在提交前一定要先跑测试"、"不要动 migrations 目录"、"如果测试失败就修到通过为止"。写完之后你会发现：**这些规则是运营规则，不是建议，但它们的执行者是一个会忘、会偷懒、会被上下文挤掉的模型。**

## 二、把规则搬到模型外面

状态机的分工可以一句话说完：

> 模型提议动作和转移，外围软件决定允不允许。

| 谁 | 负责什么 |
| --- | --- |
| 模型 | 读懂任务、提出"我想调用 `deploy`"、"我认为可以进入 review" |
| 状态机 | 现在允许哪些事件、事件之后状态变成什么、什么条件下算完成 |
| 执行环境 | 真正跑工具、落库、重试、写日志 |

关键差别在**权威状态**（authoritative state）在哪。在简单循环里，权威状态是"模型脑子里对进度的理解"，它每次被调用都可能变；在状态机里，权威状态是一行数据库记录，模型只能发事件来请求改变它。

状态机不做智能的事。它只做一件：**当模型说"我想做 X"时，判断现在允不允许；以及做完之后，状态变成什么。**

## 三、四种状态机，四个层级

原文最有价值的地方，是把"agent 状态机"拆成四层。它们管的东西完全不同，经常被混为一谈。

| 层级 | 它控制什么 | 代表实现 | 什么时候需要 |
| --- | --- | --- | --- |
| 1 推理循环 | 单次会话内 agent 的执行环 | XState / Stately Agent | 要审批、要错误恢复、要限定可用动作 |
| 2 工作流 | 一串活动的顺序与共享状态 | LangGraph / Mastra / n8n | 步骤固定、中断后要能续跑 |
| 3 监督 | 派发出去的工作的生命周期 | OpenAI Symphony / Pi Missions | 一个 agent 派多个 worker |
| 4 工作本身 | 什么算做完、先后依赖 | ThruWire | 完成必须被证据验证 |

### 3.1 推理循环内：控制 agent 自己怎么转

最小的一层，就套在 `while` 循环里面。把"推理 / 执行工具 / 等审批 / 处理错误 / 完成"显式写成状态，模型每轮只能**提议**一个转移。

Stately Agent 走的就是这条路：把 agent 的执行环做成 XState 状态机，模型写回复，应用控制允许哪些转移。用 XState v5 写出来大概是这样（示意，省略了工具执行细节）：

```ts
import { setup, assign } from 'xstate'

export const agentLoop = setup({
  types: {
    context: {} as { pending: ToolCall | null; evidence: string[] },
    events: {} as
      | { type: 'PROPOSE'; call: ToolCall }
      | { type: 'APPROVE' }
      | { type: 'REJECT'; reason: string }
      | { type: 'RESULT'; ok: boolean }
      | { type: 'FINISH'; evidence: string[] },
  },
  guards: {
    // 风险等级由软件判定，不由模型自称
    isRisky: ({ event }) => 'call' in event && RISKY_TOOLS.has(event.call.name),
    // "完成"也要有证据才允许
    hasEvidence: ({ event }) => 'evidence' in event && event.evidence.length > 0,
  },
}).createMachine({
  id: 'agent-loop',
  initial: 'thinking',
  states: {
    thinking: {
      on: {
        PROPOSE: [
          { guard: 'isRisky', target: 'awaitingApproval', actions: assign({ pending: ({ event }) => event.call }) },
          { target: 'executing', actions: assign({ pending: ({ event }) => event.call }) },
        ],
        FINISH: { guard: 'hasEvidence', target: 'done', actions: assign({ evidence: ({ event }) => event.evidence }) },
      },
    },
    awaitingApproval: {
      on: { APPROVE: 'executing', REJECT: 'thinking' },
    },
    executing: {
      on: {
        RESULT: [
          { guard: ({ event }) => event.ok, target: 'thinking' },
          { target: 'recovering' },
        ],
      },
    },
    recovering: { after: { 3000: 'thinking' } },
    done: { type: 'final' },
  },
})
```

注意两个 guard：模型只能"提议"，能不能进 `executing` 取决于 `isRisky`——**模型再怎么说"这一步很安全"，也改不了 `RISKY_TOOLS` 这个集合**；同理 `FINISH` 要带证据才允许进 `done`。

这一层的价值在于：它不改变 agent 的灵活性，只把"哪些动作在什么状态下允许"变成代码。缺点是它只管一次会话——会话结束，状态就没了。

### 3.2 工作流：控制一串活动

往上一层，控制的不再是"一轮对话"，而是"一串活动"。基本形状是**节点 + 共享状态 + 条件边**。

- **LangGraph** 的 `StateGraph`：节点读写共享 state，条件边决定下一跳，配合 checkpointer 做持久执行；
- **Mastra** 的 `createStep` / `createWorkflow`：每个 step 声明输入输出 schema，用 `.then()` 串起来、`.commit()` 收口；
- **n8n**：把同一套节点+边的思路做成了可视化编排。

LangGraph 的最小形状（共享状态用 zod 声明，验证不过就回到 plan）：

```ts
import { StateGraph, StateSchema, GraphNode, START, END, interrupt } from '@langchain/langgraph'
import * as z from 'zod'

const State = new StateSchema({
  plan: z.array(z.string()),
  passed: z.boolean(),
})

// 动手前挂起：图停在这一行，状态由 checkpointer 存下，等外部 Command({ resume }) 回来
const actNode: GraphNode<typeof State> = async (state) => {
  const ok = interrupt('可以动手了吗？')
  if (!ok) return { passed: false }
  return { passed: await runActions(state.plan) }
}

const graph = new StateGraph(State)
  .addNode('plan', planNode)
  .addNode('act', actNode)
  .addNode('verify', verifyNode)
  .addEdge(START, 'plan')
  .addConditionalEdges('plan', (s) => (s.plan.length ? 'act' : END))
  .addEdge('act', 'verify')
  .addConditionalEdges('verify', (s) => (s.passed ? END : 'plan'))
  .compile({ checkpointer })   // interrupt() 必须有 checkpointer，否则挂起就丢了
```

`interrupt()` 和编译期的 `interruptBefore` 不一样：后者是调试用的静态断点，官方明确不建议拿它做 human-in-the-loop。

这一层解决的是**顺序和续跑**：步骤是固定的，状态是共享的，跑到一半崩了可以从最后一个 checkpoint 接着来。它不解决"这个任务到底做完了没有"——那是第 4 层的事。

### 3.3 监督层：控制委派出去的工作

再往上一层，状态机跑到 agent **外面**去了。它不管单个 worker 内部怎么想，只管**派出去的工作的生命周期**：派给谁、跑到哪、失败了重试几次、超时了要不要收尸。

两个例子正好代表两种接线方式：

- **OpenAI Symphony**：一个长跑的服务，按固定节奏轮询 issue tracker（demo 里是 Linear 看板），每个 issue 建一个隔离 workspace，起一个 Codex app-server 会话来干，用指数退避管重试，issue 状态一变就把在跑的会话停掉。它把"项目工作"变成一个个隔离的、自主的实现运行，团队管的是工作，不是盯着 agent。
- **Pi Missions**：通过 Pi 的扩展 API 嵌进 harness 内部，由一个监督 agent 调用工具派 worker，每个 worker 跑一个全新的 Pi 进程。因为嵌在 harness 里，它能看见会话、能复用工具，但每个 worker 的状态是干净的。

这一层的分界线很清楚：**它不碰 worker 的推理过程**。worker 内部是不是用状态机、用什么模型、跑多久，监督层都不关心；它只关心"这个工作单元现在处于哪个阶段"。

### 3.4 工作本身：建模工作状态

最高一层，状态机建模的对象已经不是"agent 怎么执行"，而是**工作本身处于什么状态**。

ThruWire 的做法是：把工作拆成一张 **AI checkpoint 图**。每个 checkpoint 定义三件事——必须满足的需求、证明需求被满足的证据、以及依赖（依赖没完成，这个 checkpoint 就不被接受）。agent 怎么干、用什么工具、跑几个会话，系统不管；系统只评估**提交上来的证据是否满足需求**。

```json
{
  "checkpoint": "auth-flow-works",
  "requires": ["登录成功返回 200", "错误密码返回 401", "token 过期后能刷新"],
  "evidence": ["tests/auth.test.ts 全绿", "CI run #1842 通过"],
  "dependsOn": ["db-schema-migrated"]
}
```

这一层最反直觉，也最关键：**"完成"从模型的一句声明，变成一个可以被别人检查的事实。**

### 3.5 最容易混的一处：两个 checkpoint

LangGraph 有 checkpoint，ThruWire 也有 checkpoint，但它们不是一回事。这是原文专门点出的易混点：

| | LangGraph checkpoint | ThruWire checkpoint |
| --- | --- | --- |
| 存的是什么 | **执行状态**：图跑到哪个节点、thread 里的消息 | **工作状态**：需求、证据、依赖 |
| 解决什么问题 | 中断后能续跑 | 需求没满足前，工作不被接受 |
| 谁写的 | 运行时自动写 | agent 交证据，系统判定 |
| 丢了会怎样 | 得从头重跑 | 完成度不再可信 |

一句话区分：**执行状态回答"跑到哪了"，工作状态回答"做完了没有"。** 很多团队上了 LangGraph 就以为解决了完成度问题，其实只解决了续跑。

## 四、为什么大多数人是自己写

四种现成方案都在，但现实中大量团队是自己撸一个。原文给了三个真实理由，都不是"不懂行"：

1. **就是简单。** 只要 5 个任务状态（queued / running / review / done / failed）加一个派编码 agent 的动作，几个转移函数加一个轮询就够了，没必要上通用图运行时。为了 5 个状态引入一整套 DSL，是负收益。
2. **已有执行环境。** 围着 Claude Code / Codex / Pi 搭工作流的人，想保留现有 harness（工具、权限、上下文管理都是现成的），只在外面管任务生命周期。换个运行时等于把 harness 重写一遍。
3. **要接现有基建。** 团队已经有数据库、队列、调度器，甚至有专门的状态机服务。在这些东西上加"agent 执行"，比把整条链路搬进 agent 框架容易得多。

代价也很实在：**从简单起步，最后往往被迫自己实现 checkpointing、分布式锁、调度、可观测性、崩溃恢复——把想避开的基建又重造了一遍。**

这中间的判断标准不是"简单 vs 复杂"，而是：**你的规则会不会长到需要可观测、可回放、可迁移的程度。** 会，就别假装它只是一个 `switch`。

## 五、最小实现：状态存起来，转移写成函数

真要做，核心只有两件事：状态存在 JSON 或数据库里；转移写成"校验事件 + 更新状态"的纯函数。

```ts
// task-machine.ts —— 权威状态在这里，模型只能发事件
export type TaskState = 'queued' | 'running' | 'review' | 'done' | 'failed'

export type TaskEvent =
  | { type: 'claim'; worker: string }
  | { type: 'submit'; evidence: string[] }
  | { type: 'approve'; reviewer: string }
  | { type: 'reject'; reason: string }
  | { type: 'fail'; reason: string }

const ALLOWED: Record<TaskState, Partial<Record<TaskEvent['type'], TaskState>>> = {
  queued: { claim: 'running' },
  running: { submit: 'review', fail: 'failed' },
  review: { approve: 'done', reject: 'running' },
  done: {},
  failed: { claim: 'queued' },
}

export function apply(task: Task, event: TaskEvent): Task {
  const next = ALLOWED[task.state][event.type]
  if (!next) throw new IllegalTransition(task.id, task.state, event.type)
  // 规则校验写在这里，而不是写在 prompt 里
  if (event.type === 'submit' && event.evidence.length === 0) {
    throw new EvidenceMissing(task.id)
  }
  return { ...task, state: next, updatedAt: Date.now() }
}
```

落库时要带乐观锁，否则两个 worker 会同时 `claim` 同一个任务：

```sql
UPDATE tasks SET state = $next, version = version + 1
WHERE id = $id AND state = $expected AND version = $version;
-- 影响 0 行 = 有人抢先改了：重读状态，重新决定
```

### 5.1 和 harness 接线：三种方式

真正难的不是状态机，是"agent 怎么请求一次转移"。三种接法：

| 方式 | 谁发起转移 | 适合 | 代价 |
| --- | --- | --- | --- |
| 外部编排器（SDK / 子进程） | 你的进程 | 全新搭一套 | 自己管进程、日志、超时、回收 |
| harness 扩展暴露工具 | agent 在会话里调用 | 已有 Claude Code / Codex / Pi | 依赖那家的扩展 API |
| MCP server | 任何支持 MCP 的 harness | 多个 harness 混用 | 状态机变成独立服务，要部署运维 |

第三条最通用：把状态机做成 MCP server，暴露三个工具，任何 harness 的 agent 都能接。

| 工具 | 语义 | 服务端动作 |
| --- | --- | --- |
| `claim_task` | "给我一个能干的活" | 原子地挑一个 queued 任务，转 running |
| `submit_evidence` | "我做完了，这是证据" | 转 review，把证据挂到任务上 |
| `complete_task` | "审批通过" | 只有 review 态才允许，转 done |

```ts
server.registerTool('claim_task', { inputSchema: { worker: z.string() } }, async ({ worker }) => {
  const task = await store.claimNext(worker)   // 内部跑 apply(task, { type: 'claim', worker })
  return { content: [{ type: 'text', text: JSON.stringify(task) }] }
})
```

这套设计的好处是：**换 harness 不用换规则**。Claude Code 里的 agent 和 Pi 里的 agent 看到的是同一份状态机。

### 5.2 持久化不等于持久执行

这是最容易踩的一个概念坑。**状态机持有权威状态、强制转移规则；但把状态写进 JSON 只解决了"存"，没解决"持久执行"。**

真正的持久执行要保证：进程崩了能从最后一次成功的活动继续、一个活动只执行一次、定时器和重试在重启后依然有效。这些交给专门的运行时——**Temporal、Restate、DBOS**——而不是自己用 `setInterval` 加一张表硬凑。

分工是：状态机定义**规则**，持久执行运行时保证**规则被执行到底**。

## 六、真正的主张：确定性脚手架可以叠层

原文最有洞察的一句是：**状态机可以在不同层级同时存在，不需要一个状态机控制整个系统。**

{% mermaid %}
%%{init: {'theme':'base', 'themeVariables': {'fontFamily':'inherit','fontSize':'14px','minNodeSpacing':20}}}%%
graph TB
    Q{"这活现在该干什么？"}:::ask
    L1["第 1 层 · 推理循环<br/>thinking → executing → thinking<br/>XState / Stately Agent"]:::loop
    L2["第 2 层 · 工作流<br/>节点 + 共享状态 + 条件边<br/>LangGraph / Mastra / n8n"]:::flow
    L3["第 3 层 · 监督<br/>派出去的 worker 的生命周期<br/>Symphony / Pi Missions"]:::sup
    L4["第 4 层 · 工作状态<br/>需求 + 证据 + 依赖<br/>ThruWire"]:::work

    Q --> L1 --> L2 --> L3 --> L4

    classDef ask fill:#ede9fe,stroke:#8b5cf6,color:#5b21b6;
    classDef loop fill:#e0e7ff,stroke:#6366f1,color:#312e81;
    classDef flow fill:#ccfbf1,stroke:#14b8a6,color:#115e59;
    classDef sup fill:#fef3c7,stroke:#f59e0b,color:#78350f;
    classDef work fill:#dcfce7,stroke:#16a34a,color:#14532d;
{% endmermaid %}

四层各管一件事，互不越界：会话内部一个状态机（管动作允许性），跨会话监督一个（管派发出去的工作），再有一个判断"工作是否满足需求"（管完成度）。**几层叠起来用，才是完整的脚手架。**

作者的判断：随着 agent 承担越来越长、越来越关键的工作，这些确定性层会成为 agent 基建的标准部分——不是因为大家爱写状态机，而是因为**把关键判断留在模型里，风险随任务变长而线性增长**。

## 七、和 pi 的关系

原文点名的 Pi Missions，走的正是"扩展 API 嵌进 harness、监督 agent 调工具派 worker"这条路——对应第 3 层。

而 pi 的 subagent workflow（用 `runs.run` / `runs.all` 编排 subagent）就是这一层的实例。这个博客仓库里就有一条现成的，`.pi/workflows/blog-write.js`：

```js
// research → draft → cover → review → publish
const research = await runs.run("research", { label: "阶段1 调研：事实+大纲", agent: "scout", task: "..." });
const draft    = await runs.run("draft",    { label: "阶段2 起草：写文章",   agent: "worker", task: "..." });
const cover    = await runs.run("cover",    { label: "阶段3 配图：封面图",   agent: "worker", task: "..." });
const review   = await runs.run("review",   { label: "阶段4 审查：准确性+结构", agent: "reviewer", task: "..." });
const publish  = await runs.run("publish",  { label: "阶段5 修订+发布",     agent: "worker", task: "..." });
```

这五个阶段就是五个状态。**阶段顺序由 workflow 决定，不由负责写作的那个 agent 决定**——它不能自作主张跳过审查直接发布。每一阶段内部，worker 爱怎么想怎么想；阶段之间的边界，是确定性的。

这就是"确定性脚手架"最朴素的样子：你不需要引入通用图运行时，**把流程写成代码，把流程内的自由留给模型**。

## 重点总结
- **把规则写进 prompt 就当实现了。** prompt 是建议，模型会忘、会被上下文挤掉、会自我合理化。要强制的规则就落进 `ALLOWED` 表。
- **让模型宣布完成。** "我认为任务已完成"不是完成，是提议。完成要有证据，证据要能被别人检查。
- **混淆两种 checkpoint。** 上了 LangGraph 的 checkpointer 只解决了续跑，不解决完成度——别以为一回事。
- **状态存在 JSON 里就当持久执行。** 进程一崩，正在跑的活动就丢了；要"崩了能接着跑、一个活动只跑一次"，用 Temporal / Restate / DBOS。
- **忘了并发。** 两个 worker 同时 `claim`，同一个任务被做两遍。更新语句必须带 `AND state = $expected AND version = $version`。
- **状态机管太多。** 一开始就画一张覆盖全流程的大图，改一处要动全身。先做 5 个状态，需要时再叠层。
- **用状态机限制模型的思考。** 状态机该管"允不允许动作"，不该管"推理必须走几步"。约束在边界上，中间放开。
- **不记录转移历史。** 只存当前状态，出问题没法回放"它为什么走到这一步"。事件日志和状态一样重要。

## 参考

- [Agent State Machines: Building Deterministic Scaffolding for Agents（Josh Rosen）](https://x.com/josh_rosen)——原文
- [Stately Agent 文档（XState 团队的 agent 状态机）](https://stately.ai/docs/agents/agents)
- [从循环到状态机：Stately Agent 的迁移指南](https://stately.ai/docs/packages/agent/from-a-loop)
- [LangGraph Persistence（checkpointer 与持久执行）](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Mastra Workflows（createStep / createWorkflow）](https://mastra.ai/docs/workflows/overview)
- [n8n 工作流文档](https://docs.n8n.io/workflows/)
- [OpenAI Symphony（监控 issue tracker、派 Codex 会话）](https://github.com/openai/symphony)
- [ThruWire（checkpoint 图：需求 + 证据 + 依赖）](https://thruwire.ai)
- [Temporal](https://temporal.io) · [Restate](https://restate.dev) · [DBOS](https://dbos.dev)——持久执行运行时
