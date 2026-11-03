---
title: AI 代码审查全景：从 FIG A 看每个阶段 AI 做什么、人的精力放哪
date: 2026-10-29 15:45:00
description: 以 Anthropic 那张「一次改动的生命周期」图为核心，逐阶段拆解 AI 在 code review 里具体做了什么、人的精力放在哪、个人开发者怎么把这些阶段塞进自己的开发工作流。
categories:
  - 技术
tags:
  - AI
  - 代码审查
  - 工程实践
  - Claude Code
cover: /img/cover-code-review.jpg
---

## TL;DR

Anthropic 那张「一次改动的生命周期」图（FIG A）不是一张装饰图，它就是答案：**AI 在 PR 前、PR 中、合并后三个阶段各干各的，人只在"风险"和"方向"两个地方出场。** 个人开发者要学的不是"怎么让 AI 审代码"，而是**怎么把这套分层流程塞进自己的提交、发布、回滚里**。

![FIG A：一次改动的生命周期](/img/code-review-fig-a.jpg)

> 图 1：一次改动从作者机器到用户的完整旅程（源自原文）。绿色 = 自动化，橙色菱形 = 按风险由人决定，循环箭头 = 出错后的恢复。

这张图分四个阶段：**PR 前 → 每个 PR → 合并 → 合并后**。下面逐阶段拆。

## 一、PR 之前：AI 先自证，别等 PR

图里第一阶段叫 **"The work is verified"（工作被验证）**。意思是：在 PR 存在之前，改动已经被验证过了。

**AI 干了什么：**
- 给 Claude 一个**能跑**的东西——测试、构建、lint、跟设计稿对比的截图——要求它**展示输出**，而不是说"我完成了"。
- 然后让**子 agent 用全新上下文**再审一遍 diff。

Boris Cherny（Claude Code 作者）的说法：**让模型能验证自己的工作，大概是最重要的一件事**，能让结果好 2–3 倍。验证方式每个领域不同——可能只是跑一条 bash 命令，也可能是跑测试套件、在浏览器/模拟器里试。

**人在哪：** 几乎不参与。除非自审发现需要人判断的（比如"这个方案方向对不对"），否则人在这个阶段是缺席的。

**个人开发者能抄的：**
- 提交前，让 AI 跑 `npm test && npm run build && npm run lint`，**贴输出**，别听它说"done"。
- 让 AI 做一遍"找 bug / 简化 diff / 端到端验证"三件事，人只看结论。

## 二、每个 PR：AI 审查 + 人只按风险出场

这是图里最密集的阶段，**四个检查同时跑**：

### 1. Required CI（自动化，红就拦）
lint、类型检查、各平台测试、构建。一个典型 PR 可能在有人看之前就跑几十项。**AI 场景：纯自动化，人不参与。**

### 2. Claude code review（AI 审查）
**多组 agent 并行找 bug → 另一组投票 → 票数够才发评论。** 只涉及风格/清理的直接丢，剩下的按严重度排，标 `Important` / `Nit` / `Pre-existing`——PR 没引入的老问题不算在作者头上。

**AI 场景：这是 AI 的主场。** 读 diff 对照整个 repo 和 PR 意图，问"它解决了自己的问题吗？契合系统吗？会不会弄坏别的？"。

### 3. Security review（安全审查，能卡合并）
单独一遍。**bug 审查或安全审查只要还有未关闭的 finding，就禁止合并。** 要么修，要么写个短理由关掉。

**AI 场景：自动化安全扫描。** 人不参与。

### 4. Risk-based approval（风险分级，人出场）
这是**人唯一出场的地方**，而且不是所有人——是按风险：

| 风险 | 例子 | 需要几个真人 |
| --- | --- | --- |
| 低 | 文档、文案、纯内部功能、带 flag 的增量 | **0 人**（自动审查 + 安全绿了就过） |
| 中 | 普通产品改动；缓存、自动更新、系统提示等敏感区 | **1 人** |
| 高 | 最高风险代码 + 永远要两人的路径 | **2 人** |

分级由**变更**决定，不由作者决定。分类器读改动定档，第二个分类器判断"即使档位说不用人，这次是否还得加人"。只有可信作者能走轻路径，agent 的批准永远不算真人，**谁发起谁负责**。

**AI 场景：分类器判断风险。** **人场景：只在中/高风险出场。**

## 三、合并：merge queue 兜底

图里这一步很简单：**merge queue 对最新 main 重跑所有检查**，防止两个单独能过的 PR 合并后把 main 搞坏。

**AI 场景：无。** 纯自动化。**人：无。**

## 四、合并后：flag + 灰度 + 快速回滚

这是最后一层，也是**人重新出现**的地方：

1. **Behind a flag, used internally first**：新行为藏在 feature flag 后面，先对 Anthropic 员工上，内部重度使用往往先于用户暴露回归。
2. **Gradual release**：公开发布先走 `latest` 再走 `stable`，让少数人先踩坑。
3. **Watch, fix forward or roll back**：**作者 + on-call 观察**。flag 能**一键关**（不用发版、不用回滚代码），坏构建直接 revert。

**AI 场景：观察（监控、告警）。** **人场景：on-call 观察 + 快速决策回滚。**

## 五、人的精力到底放在哪

把上面四阶段合起来，人的精力**不再花在"逐行看 diff"上**，而是集中在六个地方：

1. **决定要不要做**——方向、品味、范围。一个团队说"审查瓶颈解决了"，但还是对跨团队的改动保留人审，因为总得有人问"我们真的要做这个吗"。
2. **高风险代码**——计费、自动更新、CI 工作流。这些错了代价大，必须人看。
3. **架构**——会被人复制的代码，定了一次就成范式，必须审。
4. **读证据**——测试输出、跑的命令和返回值、截图、AI 的 finding。**说不清"这些检查会漏什么"时，就该要求一次真审查，而不是快速点个通过。**
5. **对结果负责**——每个上线的变更都得有人担责，不管是谁敲的。
6. **观察 + 快速回滚**——出错时，人的判断比"审得多快"更重要。

一句话：**AI 把 90% 的例行错误挡在前面，人负责"该不该做、风险在哪、出错能不能收住"。**

## 六、个人开发者怎么落到自己的工作流

这套流程是大团队的，但**每个阶段都能简化搬进个人项目**。具体五步：

### 1. 提交前：让 AI 自证 + 自审
- 给 AI 能跑的命令（`npm test && npm run build && npm run lint`），要求贴输出。
- 让 AI 做"找 bug / 简化 diff / 端到端验证"，人只看结论和证据，不从头读初稿。
- **别听"done"**——要它证明。

### 2. 写一份 `CLAUDE.md`
把项目约定、目录结构、代码风格、"不要动哪些文件"写进去，让 AI 每次都读到。这是最便宜的"规范 AI"手段，也是大团队 `CLAUDE.md` / `REVIEW.md` 的个人版。

### 3. 提交时：小步、可回滚
- 一个 commit 只做一件事。
- 用 git 分支/标签让"撤掉"变成一条命令。个人项目没 flag，但"能快速回滚"这条原则一样成立。

### 4. 按风险决定自己看多少
- 文档、文案、样式改动：大胆让 AI 改，自己扫一眼。
- 认证、加密、数据迁移、部署配置：**一定人工逐行看**，这是你的"高风险档"。
- 判断标准就是那张图的橙色菱形——**只有风险处才上人**。

### 5. 上线后：能秒关 + 复盘
- 关键功能尽量用 flag 包起来，出问题不用发版就能关。
- 出事先 revert，再慢慢查。
- **每次出问题问一句"哪一步本该拦住它"**，把答案加到检查清单或 `CLAUDE.md` 里——这就是个人版的"事故变 eval"。

## 七、恢复链路（出问题怎么办）

这张图最后那个循环箭头，就是恢复链路：

{% mermaid %}
%%{init: {'theme':'base', 'themeVariables': {'fontFamily':'inherit','fontSize':'14px','minNodeSpacing':20}}}%%
graph LR
    Found([线上发现异常]):::warn --> Flag[关 feature flag]:::warn
    Flag --> Revert[revert / 快速回滚]:::warn
    Revert --> Fix([修复]):::fix
    Fix --> Review[事故复盘]:::review
    Review --> Q{哪一层本该抓住?}:::decision
    Q --> Eval[加入 eval 集]:::eval
    Eval --> Loop([流程进化]):::done

    classDef warn fill:#fee2e2,stroke:#ef4444,color:#7f1d1d;
    classDef fix fill:#fef3c7,stroke:#f59e0b,color:#78350f;
    classDef review fill:#e0e7ff,stroke:#6366f1,color:#312e81;
    classDef decision fill:#ede9fe,stroke:#8b5cf6,color:#5b21b6;
    classDef eval fill:#ccfbf1,stroke:#14b8a6,color:#115e59;
    classDef done fill:#dcfce7,stroke:#16a34a,color:#14532d;
{% endmermaid %}

**关键认知：不怕 AI 漏，怕的是没有快速下架和修复的机制。** 前两层（AI 审查 + 人按风险把关）降低出错概率，第三层（快速回滚）降低出错代价。只要第三层够快，就不必因为"AI 可能漏"而不敢用 AI。

## 常见坑

- 别让 AI 说"done"——要它**展示输出**，证明它跑过了。
- `CLAUDE.md` 要**短**，细节指到别的文档，否则每次审查都加载它反而拖慢。
- 风险分级要**自己判断**，别默认"所有改动都要人看"——那等于没省。
- 出事**先 revert 再查**，别一边查一边改导致越改越乱。
- 复盘的答案要**落进清单/`CLAUDE.md`**，不然下次 AI 还会犯同样的错。
- AI 自嗨时**停下来重新想方案**，别继续"再修一轮"。

## 参考

- [How the Claude Code team does code review（Addy Osmani / Morgan Westlee Lunt / Qing Wang）](https://claude.dev/blog/solving-code-review-at-anthropic/)
- [Addy Osmani 的推文](https://x.com/addyosmani/status/2114604912520921136)
- [The Code Nobody Reads（Addy Osmani 的延伸文章）](https://addyo.substack.com/p/the-code-nobody-reads)
