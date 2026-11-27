---
title: "两个 Agent 同时改一个仓库：git worktree 隔离了什么，没隔离什么"
slug: multi-agent-worktree
date: 2026-11-26 11:31:55
description: "会话文件的分叉问题解决之后，下一个冲突点是工作区。用 git worktree 给两个 agent 各开一个检出，实测它的隔离边界：工作区、HEAD、索引锁是各自独立的，对象库和 refs 是共享的；同一分支不能同时 checkout，这是天然的写者互斥；而合并冲突一点没少。"
categories:
  - 架构
tags:
  - git worktree
cover: /img/2026/11/multi-agent-worktree.jpg
---

> 多 agent 协作最难的不是「怎么让它们并行」，是「怎么让它们的写操作不互相踩」。会话层已经用分叉文件解决了，工作区层没有——两个 agent 在同一个 checkout 里改代码，`index.lock` 会打架，未提交改动会串台，`git checkout` 会把对方的工作一起带走。
>
> 这篇用 `git worktree` 给两个 agent 各开一个检出，把隔离边界一条条测出来：什么真的隔离了，什么只是看起来隔离了，以及为什么「同一分支不能同时 checkout」这条限制恰好是你需要的写者互斥。

## 1. 先给结论

| 资源 | worktree 之间 | 证据 |
| --- | --- | --- |
| 工作区文件 | **隔离** | A 的 `dirty.txt` 在 B 的 `git status` 里看不到 |
| HEAD / 当前分支 | **隔离** | 各自在 `agent-a`、`agent-b` 上 |
| 索引（`index`）与 `index.lock` | **隔离** | A 的锁不影响 B，锁文件路径在各自目录下 |
| 对象库（`.git/objects`） | **共享** | B 里能直接 `git cat-file` 出 A 刚提交的对象 |
| refs（分支、标签） | **共享** | A 提交后 B 立刻能 `git log agent-a` |
| 同一分支 | **互斥** | 第二个 checkout 被拒 |
| 合并冲突 | **不解决** | 合并照样 `CONFLICT (content)` |

一句话：**worktree 隔离的是「工作区 + HEAD + 索引」，共享的是「对象库 + refs」**。前者正好是 agent 会弄脏的东西，后者正好是可以共享的。

## 2. 为什么需要这一层

上一篇（`agent-session-concurrency`）解决的是会话文件的并发写：两个终端开同一个会话，会话文件会分叉。方案是给每个终端一条独立的分支链，最后合并。

但会话只是记录，**真正会互相破坏的是工作区**。两个 agent 在同一个 checkout 里干活，会遇到这些事：

- 同时 `git add` → `index.lock` 冲突；
- A 改了 `f.txt` 还没提交，B 跑 `git checkout` → A 的改动被覆盖或者被带走；
- A 跑 `git commit -a` → 把 B 未提交的改动一起提交了；
- 构建产物（`node_modules`、`target`）互相覆盖，A 跑测试时用的是 B 刚改过的代码。

这些都是「同一份工作区」的固有问题，跟 agent 智能不智能没关系。所以需要一个物理隔离层。

## 3. 建立两个 worktree

```bash
# 作用：主仓库 + 两个独立检出，各挂一个分支
git init repo && cd repo
git commit --allow-empty -m init
git worktree add ../wt-a -b agent-a
git worktree add ../wt-b -b agent-b
```

```text
D:/notes/blog-hexo/.tmp-check/exp/wt4/repo  208b248 [master]
D:/notes/blog-hexo/.tmp-check/exp/wt4/wt-a  208b248 [agent-a]
D:/notes/blog-hexo/.tmp-check/exp/wt4/wt-b  208b248 [agent-b]
```

三个目录，同一个仓库。`wt-a` 和 `wt-b` 里的 `.git` **不是目录，是一个文件**：

```text
$ cat wt-a/.git
gitdir: D:/notes/blog-hexo/.tmp-check/exp/wt4/repo/.git/worktrees/wt-a
```

```text
$ du -sh repo/.git wt-a/.git
237K    repo/.git
1.0K    wt-a/.git
```

**对象库只有一份**。每个 worktree 只多了一个 1KB 的指针文件，以及主仓库 `.git/worktrees/<name>/` 下的元数据（HEAD、index、锁）。这是 worktree 相比「clone 两份」的核心优势：不重复占用对象存储。

## 4. 什么真的隔离了

### 4.1. 未提交改动不串台

```bash
# 作用：在 A 里留一个未跟踪文件，看 B 是否可见
echo dirty > wt-a/dirty.txt
cd wt-b && git status --short
```

输出为空。B 完全看不到 A 的未提交内容。

这条比看起来重要：它意味着 A 的中间状态（改了一半的代码、临时文件、构建产物）不会污染 B 的判断。B 跑 `git status`、`git diff` 看到的永远只是自己的东西。

### 4.2. 索引锁是各自的

手动占住 A 的 `index.lock`，再在 A 里 `git add`：

```text
fatal: Unable to create 'D:/notes/blog-hexo/.tmp-check/exp/wt4/repo/.git/worktrees/wt-a/index.lock': File exists.
```

注意路径：`.git/worktrees/wt-a/index.lock`，**在 `wt-a` 自己的元数据目录下**。而 B 的锁在 `.git/worktrees/wt-b/index.lock`，两者互不影响。

这解决了一个很实际的问题：以前两个 agent 同时 `git add` 必然有一个拿到 `index.lock` 冲突，现在各写各的索引，互不阻塞。

### 4.3. HEAD 各自独立

A 在 `agent-a`，B 在 `agent-b`。A 做 `git checkout`、`git reset`、`git commit`，B 的 HEAD 一动不动。这是「每个 agent 有自己的分支」这件事的物理保证——不是靠约定，是靠文件系统。

## 5. 什么没有隔离

### 5.1. 对象库共享

在 A 里提交，然后**在 B 里**读那个对象：

```bash
cd wt-b
git cat-file -t c4f8ce4     # → commit
git log --oneline agent-a   # → 能看到 A 的全部提交
```

**B 直接就能看到 A 的提交。** 因为对象库只有一份，`git log agent-a` 不需要 fetch、不需要网络、不需要任何同步动作。

这既是优点也是风险：

- 优点：合并是纯本地的，`git merge agent-a` 立刻可用，没有「推上去再拉下来」的往返；
- 风险：**A 一旦提交，内容就进了共享对象库，删不掉了**（只能靠 gc）。如果 agent 提交了敏感信息（密钥、token），`git reset` 只是移动 ref，对象还在。

所以「agent 提交前先过一遍 secret 扫描」这件事，在 worktree 模式下比单工作区更重要——因为污染范围是共享的。

### 5.2. refs 共享

分支、标签、`refs/remotes` 全部共享。A 建一个分支，B 立刻能看到；A 删一个分支，B 那边的引用也没了。

这意味着**分支命名必须带 agent 前缀**（`agent-a/feature-x`），否则两个 agent 撞名时会互相覆盖。实测里我用 `agent-a` / `agent-b` 这种顶层名字，够用但不适合长期；真实场景建议 `agent/<id>/<task>`。

### 5.3. 合并冲突照旧

A 和 B 都改 `f.txt` 的同一行，然后合并：

```text
$ git merge agent-a
Auto-merging f.txt
CONFLICT (content): Merge conflict in f.txt
Automatic merge failed; fix conflicts and then commit the result.

$ git status --short
UU f.txt
```

**worktree 不是冲突解决方案。** 它只是让冲突「延后到合并时」而不是「发生在写入时」。这其实是好事——写入时的冲突是数据损坏，合并时的冲突是可以人工处理的。

## 6. 同一分支不能同时 checkout

```bash
$ git worktree add ../wt-c agent-a
Preparing worktree (checking out 'agent-a')
fatal: 'agent-a' is already used by worktree at '.../wt-a'
```

这条限制经常被当成不便，实际上是**免费的写者互斥**：

- 一个分支在任何时刻只可能有一个工作区在改它；
- 想并行改同一个分支？做不到，必须开新分支；
- 于是「两个 agent 改同一个分支导致 HEAD 互相覆盖」这类问题从根上不存在。

换句话说，worktree 用「一个分支一个检出」的硬约束，换掉了「分支级锁」这个需要自己实现的机制。你想让两个 agent 协作，就得让它们在不同分支上工作——这个约束本身就是协作协议。

## 7. 并发写入的实测

### 7.1. 同一 worktree 里并发提交

在**一个** worktree 里起 8 个并发的 `git add` + `git commit`：

```text
1  fatal: cannot lock ref 'HEAD': is at 10ab6fc... but expected 567b02a...
1  fatal: Unable to create '.../worktrees/wt-a/index.lock': File exists.
4  nothing to commit, working tree clean
```

**`cannot lock ref 'HEAD'`** 这条是新发现：即使索引锁拿到了，两个进程同时更新 HEAD 引用也会撞。这说明「同一个 worktree 内的并发 git 操作」根本不该做，无论有没有 worktree。

### 7.2. 两个 worktree 各自并发

A 和 B 各自串行提交 20 次，两个循环同时跑：

```text
a=21 b=21 total=41
```

**零失败。** 41 个提交（1 个初始 + 20 + 20）全部落盘，两个分支各自完整。

对比 7.1：同一个 worktree 里并发 → 大面积失败；两个 worktree 各自串行 → 完全干净。这就是隔离层的价值。

### 7.3. 但「两个 worktree 里同时提交」也会撞

我一开始写的是「两个 worktree 同时并发提交」，结果出现了一批 `A1 FAILED` / `B1 FAILED`。排查发现不是 worktree 的问题，是**测试脚本的问题**：并发的是同一个目录里的多个 git 进程，等于在各自 worktree 内制造了 7.1 的场景。

修掉之后（每个 worktree 内部串行、两个 worktree 之间并发）就干净了。这个坑值得记下来：**worktree 隔离的是不同 worktree 之间，不隔离同一个 worktree 内部的并发。**

## 8. 残留与清理

直接 `rm -rf` 删掉一个 worktree 目录：

```text
$ git worktree list
.../repo  208b248 [master]
.../wt-a  c4f8ce4 [agent-a]
.../wt-b  380d8aa [agent-b] prunable
```

标记成 `prunable`，但记录还在。再想在同一路径建 worktree：

```text
fatal: '.../wt-b' is a missing but already registered worktree;
```

必须先 `git worktree prune`：

```text
$ git worktree prune -v
Removing worktrees/wt-b: gitdir file points to non-existent location
```

**agent 崩溃或被强杀时，这一步必须做**，否则下次启动会撞上「已注册但目录不存在」。这是自动化里最容易漏的一步，建议在 agent 的清理钩子里无条件跑 `git worktree prune`。

## 9. 构建产物怎么办

worktree 共享对象库，但**不共享工作区文件**——`node_modules`、`target`、`.venv`、`dist` 每个 worktree 各一份。

实测里两个 worktree 的 `.git` 一个 237KB、一个 1KB，但工作区文件是完整复制的。对 Node 项目来说，两个 worktree 就是两份 `node_modules`（几百 MB 到 1GB+）。

三种处理方式：

1. **能接受就接受**。现代磁盘空间便宜，两份 `node_modules` 换来的隔离是值得的。
2. **共享只读依赖**。`pnpm` 的 store、`yarn` 的 cache 本来就是全局的，只有 `node_modules` 的符号链接层重复，体积远小于 npm。
3. **构建产物放 worktree 外面**。`target/`、`dist/` 通过配置指到共享目录——但**只在两个 agent 不跑同一个构建时才安全**，否则又变成并发写。

对 Java 的 `target/`，Maven 支持 `-Dmaven.build.dir=...`；对 Node 的 `dist/`，改 `vite build --outDir`。但这类共享引入的耦合往往比省下的磁盘更贵，我倾向于第 1 种。

## 10. 一套可用的多 agent 工作流

把上面所有实测拼起来，一个能用的流程是：

```bash
# 作用：为每个 agent 开独立检出，分支带 agent 前缀
git worktree add ../wt-$AGENT_ID -b agent/$AGENT_ID/$TASK
cd ../wt-$AGENT_ID
# agent 在这里干活，提交到自己的分支

# 收尾：回到主仓库合并
cd ../repo
git merge agent/$AGENT_ID/$TASK
git worktree remove ../wt-$AGENT_ID
git worktree prune
```

几条必须遵守的：

1. **分支命名带 agent 前缀**，避免 refs 撞名（refs 是共享的）。
2. **每个 worktree 内部严格串行**，不要在同一个 worktree 里并发跑 git 命令（实测会撞 `HEAD` ref 锁）。
3. **agent 异常退出后无条件 `git worktree prune`**，否则残留记录会挡住下次启动。
4. **提交前扫密钥**，因为对象库共享，提交即污染。
5. **接受合并冲突**，worktree 不解决它，只把它推迟到可控的时机。

## 11. 常见坑

1. **以为 worktree 隔离了一切**。对象库和 refs 是共享的，A 的提交 B 立刻可见，删不掉。
2. **在同一个 worktree 里并发跑 git**。实测撞 `cannot lock ref 'HEAD'` 和 `index.lock`，8 个并发里 6 个失败。
3. **手删 worktree 目录不 prune**。留下 `prunable` 记录，下次 `worktree add` 直接报 `missing but already registered`。
4. **指望 worktree 解决冲突**。实测合并照样 `CONFLICT (content)`，`UU f.txt`。
5. **两个 agent 抢同一个分支**。被 git 硬拒（`already used by worktree`）——这是保护，不是障碍。
6. **忘了构建产物是各一份**。两个 Node 项目 worktree 就是两份 `node_modules`。
7. **agent 提交了密钥**。对象库共享，`git reset` 移不走对象，得靠 `filter-repo` 或直接弃库。

## 12. 重点总结

**worktree 的隔离边界，正好切在「会弄脏的东西」和「可以共享的东西」之间：**

- 隔离：工作区文件、HEAD、索引与索引锁；
- 共享：对象库、refs；
- 互斥：同一分支只能一个检出。

**实测出来的三条硬结论：**

1. **两个 worktree 各自串行提交，完全无冲突**（20+20 次全成功）；同一个 worktree 内并发提交，8 个里 6 个失败（`cannot lock ref 'HEAD'`、`index.lock`）。隔离层有效，但它只隔离**不同 worktree 之间**。
2. **对象库共享意味着提交即公开**。B 能直接 `git cat-file` 出 A 的对象，不需要任何同步动作——这让合并变简单，也让密钥泄露变严重。
3. **worktree 不解决合并冲突**，只把冲突从「写入时损坏」推迟到「合并时可处理」。同一分支不能双检出这条硬限制，顺带提供了免费的写者互斥。

用 worktree 做多 agent 隔离，本质是**用文件系统级的物理隔离，换掉应用层的锁和约定**。代价是每个 agent 一份工作区（构建产物翻倍），收益是 `index.lock` 打架、未提交改动串台、`checkout` 带走别人工作这三类问题从根上消失。

## 13. 参考

- [`git worktree` 文档](https://git-scm.com/docs/git-worktree)（`add` / `list` / `remove` / `prune` 的完整语义）
- [`git worktree prune`](https://git-scm.com/docs/git-worktree#Documentation/git-worktree.txt-prune)（残留记录清理）
- 同系列：`agent-session-concurrency`（会话文件层的并发写方案）
- 实测工程：git 2.x + Windows，主仓库 + 两个 worktree，并发提交与锁冲突的原始输出见正文
