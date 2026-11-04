---
title: 两个超级 Agent：Agno 和 DeepSeek 对「自驱动公司」的两种答案
date: 2026-11-04
description: Ashpreet Bedi 和 DeepSeek Harness 团队几乎同时写了 Super-agent 的设计。一个从产品出发讲"管结果不管过程"，一个从系统出发讲 Router/Worker、Inline & Spill、算存分离和 Watchdog。这篇把两套设计拆开对比，附 DeepSeek 的实测数据。
categories:
  - 技术
tags:
  - AI
  - Agent
  - 架构
  - Super Agent
cover: /img/super-agent-designs.jpg
---

## 摘要

两篇前后脚发出来的文章——Agno 的 Ashpreet Bedi《Building a Super Agent》和 DeepSeek Harness 团队《Exploring Super-agent Design》——在讲同一件事：**agent 不该被绑在"一个手动发起的会话"上，人应该管结果，系统管 agent。**

但两人的落点不同：Ashpreet 从**产品**出发，讲一个"经理 agent"怎么把活派给 coding agent、再把公司组织成 Products/Projects/Tasks；DeepSeek 从**系统**出发，把这事当成造操作系统来做——Router/Worker 两层、事件驱动、Inline & Spill、算存分离、Watchdog。这篇把两套设计拆开对比。

## 一、共同前提：会话是瓶颈

两篇文章都从同一个观察开始：**主流 agent 还是"单会话"为单位，会话之间互相隔离。**

DeepSeek 说得更直白：

> 一个人同时最多跟 3~5 个活跃会话。这样设计下，单个任务的上限是模型能力，**多任务的上限是人的注意力**。

给现有 agent 加 CLI、MCP、外部连接器，能让它收到外部消息，但根本限制还在：仍然是一个同步会话、长时间操作会阻塞、不同任务的上下文会混、设备离线就全停。

所以结论一致：**要把 agent 从"单个手动驱动的会话"里解耦**，变成一个持续存在、跨会话保留上下文、能同时推进多个复杂任务且互不干扰的实体。

## 二、Ashpreet（Agno）：管结果，不管过程

Agno 的哲学一句话：

> **Humans should manage outcomes while the system manages agents.**

Super Agent 的样子：它了解你的公司，知道有哪些 agent 可用，能自己把活派出去。那些 agent 在后台跑，你继续跟 Super Agent 对话——问进展、改方向、派新活。

**触发方式**三种：消息（Slack/Telegram/WhatsApp 里问一句）、事件（GitHub issue 开了、PR 被 review、构建挂了）、定时（每天早上出简报）。

**收到请求后的六种反应**：

1. **直接回答**——"文档更新到哪了？"它查一下给你状态；
2. **跑现成 agent**——"准备这周客户报告"，把请求和上下文转给已有的 agent；
3. **组织更大的活**——"把文档准备好发版"，让 Company Manager 建一个 Project + 若干 Task（查示例、更新 API 引用、写迁移指南），进队列等 agent 执行；
4. **现造一个 agent**——没有合适的，就让 Platform Builder 用平台上的工具临时造一个；
5. **接着干进行中的**——"PR 看着不错，补个空响应测试"，把反馈接到原 Task 上，退回给正在干的 agent；
6. **不动**——重试过了、是重复 issue、或已经有人在处理。**有时候什么都不做才是对的。**

**组成**：coding agent（Claude Code、Codex + 一堆 workflow）+ company manager（把活组织成 Products/Projects/Tasks）+ platform builder（按需造 agent/workflow）+ platform manager + 平台里已有的其他 agent。

**学习**：用 Agno 的 Learning Machines 从会话里学，记住合作过的人，把经验带到下一个任务；还支持**决策记忆**（决定了什么、为什么、后来怎样），但默认没开。

**底座**：AgentOS 提供持久运行时、会话管理、队列执行、调度、追踪、认证和 RBAC；Studio 造 agent/团队/workflow；CompanyOS 把活组织成 Products/Projects/Tasks。一句话：**AgentOS runs the work, Studio builds the agents, CompanyOS organizes what needs doing.**

Ashpreet 也说了它的定位：**不会替代他日常的 coding agent（还是用 Codex），但适合"尾巴上那一堆活"**——SDK 改了之后测受影响的示例并修好、复现 Slack 里报的 bug 并带回失败测试和修复、自动看客户反馈并提议 Project。结果他还是要 review，但不用自己管每个会话和跟进。

## 三、DeepSeek：五个模块，像造操作系统

DeepSeek 把 Super-agent 拆成**四个特征 + 五个模块**，而且明显在借计算机系统的经典思路。

**四个特征**：
- **Continuous**：在 IM、GitHub 里交互，始终像一个 agent，不用想"哪个会话里有哪条信息"；
- **Productive**：快速响应，并行推进多个复杂任务，上一条命令没完就能接新指令；
- **Proactive**：不等逐步指令，监控环境事件，该干就干，不该干就闭嘴；
- **Persistent**：永远在线，连真实工作环境，长跑中自动从异常恢复。

> "没有任何一个 ReAct 循环能同时给出这四点，它们必须来自模型外围的系统架构。"

**五个模块**：

### 1. 两层架构：Router + Worker
连续性 vs 吞吐是个硬取舍：所有事件进一个会话，上下文最连续，但 ReAct 一次一步，吞吐低、不同任务细节还互相污染；每个事件开新会话，吞吐最高，但没有全局上下文、结果彼此脱节。

解法是分层：**Router 层**长期存在，接所有人机交互、做全局协调和记忆，**自己绝不执行任务**（甚至可以完全没有 Bash 工具）；**Worker 层**上下文隔离，高并发干活。

> 会话应该成为系统的实现细节，而不是用户的心智负担。

Router 和 Worker 之间靠 **Thread 订阅**通信：订阅了就走快路径（事件直接透传给 Worker），没订阅走慢路径（Router 决策后再派）。订阅是多对多的，多个 Worker 订阅同一个 Thread 时，新事件广播给所有订阅者，它们自己协调冲突。

### 2. 事件驱动：把上下文当缓存
触发器（消息/PR/CI/邮件）先过滤再派发。事件进来后怎么塞上下文？DeepSeek 借了编译器的两个操作：
- **Inline**：把马上要用的信息塞进当前窗口，省掉额外工具调用；
- **Spill**：超预算或很少用的信息放窗口外，只留引用/摘要，要用时再读。

再配上**局部性**（locality）：先给 ID + 摘要 → 逐步 inline 邻近内容 → 超长就截断留指针。把这套用到系统里所有对象上，就得到 **Chain of Recall**：对象有唯一 ID，注入时带上相关对象的 ID，形成引用图，模型可以顺着引用一跳跳回忆上下文。

还有 **Acting Ahead**（投机执行）：根据环境信号在后台先干起来，结果有用就交付、没用就丢弃。比如 DeepSeek 内部群里配了"静默复现并修复"策略——有人报 issue，agent 先在后台复现、找修复，确认了才说话，否则一直安静。

### 3. 全双工多通道
经典 ReAct 里 `run()` 工具调用是同步阻塞的。DeepSeek 把它换成异步的 `start()` / `stop()`：`start()` 立刻返回 "Started"，工具在后台跑完再作为新事件送回会话；模型还能 `stop()` 掉跑太久的后台命令。

多通道则是**按渠道定规矩**：IM 里像人类同事，只在需要决策/签字时打扰，**一条回复硬上限 100 词**；GitHub/邮件/文档这类异步渠道，给结构化的、信息密度高的输出。

### 4. 算、状态、环境三分离
本地 agent 把三样东西绑在一台设备上：跑 Agent Loop 的**算力**、要持久化的**会话状态**、**执行环境**（代码仓库、本地工具链）。设备一睡，agent 就停。

解法借**算存分离**：
- **算力与状态分离**：Agent Loop 跑在无状态弹性容器里，会话状态放数据库。容器可以扩缩、重启、替换，状态保证连续性——设备睡了也不影响。
- **算力与执行环境分离**：不把环境搬到云上，而是**把 Agent Loop 放云上，环境留在原地**，每个端点装个轻量 daemon（不存状态，只执行命令、返回结果）。这样支持 **BYOM（Bring Your Own Machine）**——把你自己的开发机接进云端 agent。

这和 Anthropic 的"把大脑和手解耦"是同一个思路，区别在目标场景：Anthropic 讲的是托管服务和客户 VPC 里的沙箱；DeepSeek 要先连上大家天天用的个人机器（有未提交改动、本地凭证、可能只是间歇在线）。

### 5. Watchdog：独立于主系统的控制环
持久在线光靠算存分离不够，还得能从异常里自动恢复。**一个持久在线的分布式系统，如果只靠内部逻辑，很难长期可靠。**

而且 agent 的异常很多**不是崩溃**：进程还在跑，但模型卡在无产出的循环里，或者偏离了目标。所以不能只用进程存活探针。

DeepSeek 的做法是一个独立的 **Watchdog Session**，由定时消息驱动：处理 API 错误、状态恢复失败这类基础设施故障，也用模型判断每个 Worker 是不是在**实质性推进**、有没有偏离总目标；发现异常就修，暂时性外部故障就反复重试。

因为 Watchdog 本身是个有全套工具的 agent 会话，维护者可以**用自然语言问它为什么失败**，也可以在系统运行时让它改主系统的行为（加/删 prompt、调触发规则）。

## 四、实测数据

DeepSeek 跑了两组实验（合成负载、简化环境，数字仅供参考）。

**消融实验**（四种设计，各跑 5 次，约 300 条消息、20 个真实工作请求）：

| 设计 | 任务完成时间 p50 / p95（分钟） | 每次运行缓存读取 token |
| --- | --- | --- |
| Super-agent | **12.4 / 15.7** | 23.2M |
| Super-agent 去掉透传 | 12.6 / 15.5 | 31.8M |
| 单会话 + subagent 工具（中性 prompt） | 20.4 / 29.5 | 6.1M |
| 单会话 + subagent 工具（委派优先 prompt） | 13.8 / 29.0 | 10.8M |

几个读数：
- Super-agent 明显更快更稳；
- 单会话设计**高度依赖 prompt**：中性 prompt 下 5 次里模型一次都没调 subagent，全在主会话里干，被新消息不断打断，p95 冲到 29.5 分钟；
- 两层架构在**系统层面**解决了这个问题——Router 不执行任务，Worker 只收到自己订阅的 Thread 的消息；
- 透传（pass-through）不改变完成时间，但让 Router 的 token 从 31.8M 降到 23.2M，**省下约 37%**。

**Router 批处理压力测试**：触发率从 1 涨到 40 次/分钟，平均批大小 1.0→2.8，单请求时间只从 2.5s 涨到 3.9s，**每次决策的摊销推理时间从 6.4s 降到 1.6s**。结论：突发事件可以靠批处理扛，团队现阶段没必要为了吞吐提前分片 Router、牺牲全局上下文。

## 五、两套设计的对照

| | Agno（Ashpreet） | DeepSeek Harness |
| --- | --- | --- |
| 出发点 | 产品：经理 agent 派活 | 系统：像造 OS |
| 核心比喻 | 自驱动公司 | 分布式系统 / 操作系统 |
| 分层 | Super Agent + Company Manager + 各类 agent | Router + Worker |
| 组织模型 | Products / Projects / Tasks | Thread 订阅 + Task |
| 事件处理 | 消息/事件/定时触发 | 触发器 + 过滤 + Inline & Spill |
| 连续性 | Router 持有全局上下文 | Router + Chain of Recall |
| 并发 | 后台 worker | 上下文隔离的 Worker |
| 主动 | 监控 Sources 自己派活 | 事件驱动 + Acting Ahead |
| 持久 | AgentOS 持久运行时 | 算存分离 + BYOM + Watchdog |
| 学习 | Learning Machines / 决策记忆 | 暂无（Open Problems） |
| 实验 | 无公开数据 | 有消融 + 压测数据 |

**共同点**：都把人从"协调会话"里解放出来，让系统管 agent；都把 Router/Manager 做成不执行任务的那一层；都强调"该不动时不动"。

**分歧**：Agno 更关注**产品形态**（公司怎么组织、任务怎么建模、agent 怎么按需造），DeepSeek 更关注**系统机制**（上下文怎么省、算力怎么分离、异常怎么自愈），而且给了实验数据。

## 六、对我们意味着什么

1. **"会话"不再是产品概念。** 两个团队都主张把它变成实现细节。你自己写 agent 工具时，别让用户去管"哪个会话有什么"。
2. **Router 不干活。** 负责协调的那一层如果也执行任务，就会变成瓶颈。让它只做三件事：接人、派活、记全局。
3. **上下文要当缓存管。** Inline 常用的、Spill 超长的，留 ID 走引用。这一条对单 agent 也成立。
4. **主动性要有闸门。** "该不动时不动"和"该干时干"一样重要——DeepSeek 用过滤器 + Watchdog 判进度，Agno 用"leave it alone"。
5. **持久化 ≠ 持久在线。** 状态存数据库只是第一步，还要算存分离、执行环境解耦、独立 Watchdog。
6. **别过早分片。** DeepSeek 的数据说：现阶段单个 Router 靠批处理就能扛，提前分片反而牺牲全局连续性。

## 常见坑

- **把 Router 写成会自己干活的 agent**：它会成为性能瓶颈，还会污染全局上下文。
- **只存状态就以为持久了**：设备一睡、进程一崩，正在跑的活动就丢；要有独立的控制环和可恢复的执行。
- **无脑 inline 全部上下文**：窗口会爆，注意力会被稀释。要 Inline + Spill 配合。
- **主动性没有过滤**：不对事件做筛选就派活，agent 会变成一个"很快地反复重开已解决问题"的噪音源。
- **过早分片 Router**：牺牲全局连续性换吞吐，在团队规模还没到瓶颈前是负收益。
- **把会话边界当项目管理边界**：用户管的是任务和结果，不是会话。

## 参考

- [Building a Super Agent（Ashpreet Bedi / Agno）](https://x.com/ashpreetbedi/status/2117671978354000139)
- [Exploring Super-agent Design: Towards a More Autonomous Agent System（DeepSeek Harness）](https://x.com/DeepSeekHarness/article/2116857257245987236)
- [DeepSeek 英文全文翻译](https://offloop.org/learn/exploring-deepseek-super-agent-design)
- [dsh-superagent-prototype（DeepSeek 研究原型）](https://github.com/deepseek-ai/dsh-superagent-prototype)
- [Agno / AgentOS](https://agno.com)
