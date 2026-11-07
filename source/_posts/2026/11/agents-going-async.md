---
title: Agents Are Going Async：Agent 正在拆成「编排官 + 后台 worker」
date: 2026-11-06 12:00:00
description: 基于 Sydney Runkle《Agents Are Going Async》（2026-11-05）的中文笔记：为什么串行的 ReAct 循环撑不住大任务，业界为什么收敛到「一个陪用户的编排官 + 后台异步 subagent」，以及五个任务工具、update_strategy、通知与审批机制。结构跟原文一致，术语解释为补充。
categories:
  - 笔记
tags:
  - AI
  - Agent
  - LangChain
  - 异步
  - 架构
cover: /img/2026/11/agents-going-async.jpg
---

> 本文是对 LangChain Blog《Agents Are Going Async》（Sydney Runkle、Thushanth Bengre，2026-11-05）的中文笔记转述，结构跟随原文；名词解释是我补的，观点归属原作者。原文链接见文末。

## 1. 要点速览

- 当 agent 承接更大的目标时，它要同时做到两件事：对用户保持响应，同时在多个长任务上持续推进。
- **async subagents** 把 agent 拆成两部分：一个始终对用户可用的 orchestrator，加上一批在后台跑任务、完成后回报的 subagent。
- 后台化正在成为 agent 基础设施的常态——从 Claude Code 这类 coding agent，到 OpenAI dots 这类 personal agent。

## 2. 一个类比：会消失的幕僚长

想象你有个幕僚长（chief of staff）：每次你把一个大项目交给他，他就消失了，直到全部做完才回来。你大概会当场把他开掉。

好的幕僚长应该是：**项目在后台推进，同时他随时能找到、一路给你更新**。

作者说，当我们要求 agent 去做更大的目标时，它也需要同样的两个属性：

- **responsive（有求必应）**：接到新指令立刻响应，并且带着之前全部上下文
- **productive（持续产出）**：同时在多个大任务上推进

## 3. 老架构的问题：ReAct 循环是串行的

我们用了很久的 agent 架构，同时满足不了这两点。

**ReAct 循环**（模型调工具 → 等结果 → 决定下一步，循环往复）的问题是：**每个耗时长的工具调用都会阻塞这个循环，其他任务只能排队**。

一个长任务卡住，用户想插一句话也得等——这正是"会消失的幕僚长"。

## 4. 业界正在收敛到「编排官 + 后台 worker」

作者观察到，生态正在收敛到一种拆分：**一个 agent 留在用户身边，后台 worker 干长活**。她举了三个例子：

- **Claude Code** 默认把 subagent 放到后台跑
- **OpenAI 的 dots** 把工作交给后台 worker，同时推进多件事
- **DeepSeek Harness** 把它的 super agent 建在"一个跟人对话的 router + 并行跑任务的后台 worker"上

LangChain 把这套模式带进 Deep Agents，叫 **async subagents**：

- **orchestrator（编排官）**：一直对用户可用，维护对话上下文
- **async subagents**：作为后台 worker 运行，完成后回报

这样，**agent 能承接的工作量随后台 worker 的数量增长，而不是随单个循环的长度增长**。

## 5. async subagent 到底怎么工作

一个 agent 本质上是个循环：模型调工具、等结果、决定下一步。历史上，工具和 subagent 都会**阻塞**这个循环直到返回——就像代码里逐个 `await` 每个慢调用。

**async subagent 则像一个用 `asyncio.create_task` 起的任务，或者一个你还没 `await` 的 Promise**：调用立刻返回，工作在后台独立跑，结果稍后回来。

> 名词补充：`asyncio.create_task` 是 Python 里"把协程丢到后台跑、先拿个句柄"的写法；Promise 是 JS 里"表示一个未来结果"的对象，不 `await` 就不会卡住当前流程。

这种异步依赖系统的两个性质：

- **用户能触达 orchestrator**。subagent 不再占着 orchestrator 的循环，所以只要它自己的循环不忙，用户随时能找到它，不用等所有 subagent 跑完。
- **任务并行、互不阻塞**。orchestrator 来一个任务就起一个 subagent，而不是等一整批返回。

## 6. 五个任务工具与 update_strategy

orchestrator 用五个工具管理 async subagent：

- `start_async_task`：在独立线程上起一个 subagent，立刻返回
- `check_async_task`：查任务状态；完成后取结果
- `update_async_task`：给运行中的任务发新指令
- `cancel_async_task`：停止运行中的任务
- `list_async_tasks`：列出所有任务及状态

**"给运行中的 subagent 发跟进"和"触达 orchestrator"是两件事**。orchestrator 用 `update_async_task` 发跟进时，subagent 定义里的 `update_strategy` 字段决定行为：

- **`"interrupt"`（默认）**：停掉当前 run，用新指令重启 subagent。适合纠正，比如"改用 Postgres"。
- **`"enqueue"`**：把跟跟进压到当前 run 结束后再处理。适合追加，比如"跑完顺便把测试也跑了"。

## 7. 通知：任务怎么回来

每个未完成的任务都会列在 orchestrator 的 **system prompt** 里，所以它永远知道有什么在飞。它可以用 `check_async_task` 轮询，任务也可以自己回报：

- orchestrator **忙**：每次模型调用前检查未完成任务，跑到一半就能把结果捡起来
- orchestrator **空闲**：subagent 用一个新 run 唤醒它
- orchestrator **卡在审批上**：审批不动，用户答复后结果才到

## 8. 审批：在 subagent 自己的线程里回答

需要审批的 subagent 会显示为 **waiting**，用户在 **subagent 自己的线程**里回答，**不打断 orchestrator**。在 Slack 上的 Managed Deep Agents 里，这个请求会发回原来的 thread。

这样"等审批"就不会把整个编排官冻住——这和 4 节里"用户随时能触达 orchestrator"是同一个设计目标。

## 9. 这套模式会推广到工具

作者预计这个模式会从 subagent 推广到**所有工具**。她提到 OpenAI 最近加了 **async tool calling**：模型调用工具后可以继续干活，应用在之后的一次请求里把结果送回去。

## 10. 怎么用（代码）

async subagents 在 Deep Agents 的 Python 和 JavaScript 版本里都有，也在 Managed Deep Agents 里。在 Managed Deep Agents 里，**把一个 subagent 变成异步只需要一个字段**：

```python
from managed_deepagents import define_deep_agent

agent = define_deep_agent(
    name="research-assistant",
    model="openai:gpt-5.5",
    subagents=[
        {
            "name": "researcher",
            "description": "Researches a topic in the background.",
            "system_prompt": "Research the topic and report your findings.",
            "async": True,
        },
    ],
)
```

此外，Managed Deep Agents 里**每个被服务的 agent 都会额外得到一个 general-purpose subagent 的异步副本**，于是它可以在运行时决定：委派出去的工作是前台跑还是后台跑。

## 11. 现状与限制

- **任务通知还在 beta**，API 可能还会变。
- `async-deep-agents` 仓库里有可跑的示例：一个 supervisor，加 researcher 和 coder 两个 subagent，Python 和 TypeScript 两个版本都有。
- 作者邀请大家试用，并在 GitHub issues 或 forum 反馈。

## 12. 参考

- 原文：LangChain Blog, [Agents Are Going Async](https://www.langchain.com/blog/agents-are-going-async)，Sydney Runkle、Thushanth Bengre，2026-11-05
- [Deep Agents 文档](https://www.langchain.com/deep-agents)
- [Deep Agents（Python）async subagents 文档](https://docs.langchain.com/oss/python/deepagents/async-subagents)
- [Deep Agents（JavaScript）async subagents 文档](https://docs.langchain.com/oss/javascript/deepagents/async-subagents)
- [Managed Deep Agents subagents 文档](https://docs.langchain.com/langsmith/python/managed-deep-agents-subagents)
- [async-deep-agents 示例仓库](https://github.com/langchain-ai/async-deep-agents)
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [OpenAI async tool calling](https://developers.openai.com/api/docs/guides/async-tool-calling)
</content>
