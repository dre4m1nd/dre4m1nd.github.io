---
title: Agent 记忆的组成部分（摘要）
date: 2026-11-07 12:00:00
description: Anthropic《The components of agent memory》要点摘要：记忆的定义、CL-Bench 与 Pokémon 实验、dreaming 能做什么、未解问题。
categories:
  - 笔记
tags:
  - AI
  - Agent
  - 记忆
  - Anthropic
cover: /img/2026/11/agent-memory-components.jpg
---

> Anthropic Engineering《The components of agent memory》（2026-11-06，Lance Martin）要点摘要。

## 1. 定义

agent memory = Claude 从经验获得、跨会话保留、以可读上下文存下来的知识。**不算**：权重更新、单次对话的 in-context learning、压缩上下文（compaction）。

## 2. 核心判断

- 记忆是对未来的预测：写下一条规则，就是赌以后还会用到。
- **判断"什么值得记"比"怎么记"更重要**。给强模型固定规则（如"只记失败"）反而削弱记忆收益；说清记忆是干什么的，剩下的交给它自己判断。
- 老模型要提示（答题前先读记忆、显式验证假设），新模型自己会做（Sonnet 5 的读记忆比例 9/10，Sonnet 4.6 不到一半）。

## 3. 关键实验

- **CL-Bench**：查库答题、可写记忆。Sonnet 4.6 只留下未验证的猜测；Opus 5 第一个闭环——规则 + 依据 + 旧答案 + 踩坑警告。
- **Pokémon**：只记"游戏不会告诉你的"（策略、计划、验证过的规则），别记每回合能读到的（位置、金钱）。Sonnet 3.7：413 个文件 / 225 个文件夹 → 1 枚徽章；Fable 5：9 个文件 / 2 个文件夹 + `global.md` → 4 枚徽章。
- **wiki**（Stainless 语料约 35 万文件 / 420M tokens，25 题，128 个会话）：得分 13% → 48%；search + wiki 54% → 61%（只用 search 53%）；每题省约 2 万 tokens。跨文档任务 87% vs 73%，单文档任务无增益，wiki 甚至可能长得比原文还大（博尔赫斯那个"地图和帝国一样大"的比喻）。

## 4. dreaming 能做什么

空闲时回看日志和 transcript：

- **纠错**：PokéCenter 写错 → 掉回原路 3 次、没到 Cerulean；对照 transcript 改正后进山、到城。
- **建 wiki**：把笔记连成可导航的地图。
- **提到层级顶端**：预加载进每个会话，但必须保持很小（Claude Code 只加载 `MEMORY.md` 前 200 行或 25KB）。
- **围绕目标塑形**：合同条款 41/57 → 57/57（每份合同一页、逐字引用）。
- **补会话缺口**：修 9 个死链、补 3 页。

## 5. 未解

- 何时写记忆：当下写会分心，dreaming 写又不一定立刻可用。
- 如何防漂移：dreaming 要花算力，优先盯易变信息，或按访问频率调节奏。
- transcript 搜索能否当地基；表示要花算力维护，还要防幻觉。

## 6. 参考

- [The components of agent memory](https://www.anthropic.com/research/components-of-agent-memory)（Anthropic, 2026-11-06）
</content>
