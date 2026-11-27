---
title: "git rebase 还是 merge：我把同一个分支两种走法都跑了一遍"
slug: git-rebase-vs-merge
date: 2026-11-27 11:22:36
description: "同一组提交分别用 merge --no-ff 和 rebase 走一遍：merge 只解一次冲突但留下分叉，rebase 得到线性历史却要为每个触及同一区域的提交重解一次冲突，而且 hash 全被重写、已推送就得 force-push。附 rerere 实测和团队分工规则。"
categories:
  - 技术
tags:
  - 工程实践
  - Git
cover: /img/2026/11/git-rebase-vs-merge.jpg
---

> 「rebase 让历史更干净」这句话只说了收益，没说代价。代价不在审美上，在三个具体的地方：**冲突要解几次、hash 会不会变、别人的分支会不会脱节**。
>
> 这篇把同一个分支用两种走法各跑一遍。merge 保留真实分叉，冲突只在实际合并那一刻解一次；rebase 把每个提交取出来在新基底上重放，两个提交都碰同一区域，就冲突两次——第二次还是同一处。rebase 之后两个提交的 hash 全变（前后四个值一个都对不上），reflog 里能看到 `rebase (pick)` 逐条重放；已推送的分支必须 force-push，同事的本地副本立刻脱节。最后补一组 `rerere` 实测：同一个冲突第二次出现时，git 用 `Resolved 'f.txt' using previous resolution.` 自动套用了上次的解法。
>
> 环境：git 2.56.0.windows.3，Windows 11，四组独立仓库，原始输出见正文。

## 1. 先给结论

| 维度 | `merge --no-ff` | `rebase` |
| --- | --- | --- |
| 历史形状 | 保留分叉，多一个 merge commit（两个 parent） | 线性，没有 merge commit |
| 冲突次数（两个提交都改同一区域） | **1 次** | **2 次**，而且第二次是同一处 |
| 提交 hash | 不变 | **全变**（`7f73bc2` → `95939ea`） |
| 已推送之后 | 直接 `git push` | 必须 `force-push`，且要用 `--force-with-lease` |
| 回滚方式 | `git revert -m 1 <merge>` | 只能靠 `reflog` 或事先留的备份分支 |
| 适合 | 公共分支、多人协作、需要留痕的合并 | 个人功能分支、提交历史还想整理的时候 |

一句话：**merge 保留「事情是怎么发生的」，rebase 保留「结果长什么样」**。前者对协作友好，后者对阅读友好，代价是把冲突成本从「一次」摊成「每个提交一次」。

## 2. 实验怎么搭的

四组独立仓库，场景不同，避免互相污染。基础场景都一样：一个 `base` 提交，然后 master 和 feature 各自改同一区域。

```bash
# 作用：初始化一个空仓库并配好身份，后面四组实验都从这里复制
git init exp && cd exp
git config user.name tester && git config user.email t@example.com
git config commit.gpgsign false    # 免去签名弹窗，不影响结果

# 作用：base 提交，app.txt 有八行，第 5 行是冲突的落点
printf 'line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\n' > app.txt
git add app.txt && git commit -m base

# 作用：开 feature 分支，两个提交都改第 5 行（同一区域）
git checkout -b feature
sed -i 's/^line5$/feature one/' app.txt && git commit -am 'feature: one'
sed -i 's/^feature one$/feature two/' app.txt && git commit -am 'feature: two'

# 作用：回到 master，也改第 5 行，制造真实的三方冲突
git checkout master
sed -i 's/^line5$/master change/' app.txt && git commit -am 'master: unrelated'
```

冲突落点很重要：**必须是同一区域，而且 feature 的每个提交都要碰它**。只有一个提交碰它，两种走法的冲突次数就没有差别，测不出东西。

## 3. 历史形状

先看 merge，`--no-ff` 强制生成 merge commit，即使能快进也不快进：

```bash
# 作用：在 master 上合并 feature，强制留下 merge commit
git merge --no-ff feature -m 'merge feature'
# 冲突只在这里出现一次，解完 git add + git commit
git log --graph --oneline
```

```text
*   86b5dba merge feature
|\
| * aefbd07 feature: two
| * 4bf621c feature: one
* | 971061f master: unrelated
|/
* 3b90d59 base
```

图里那两条竖线就是「真实分叉」：`86b5dba` 有两个 parent，一个是 `971061f`（master 线），一个是 `aefbd07`（feature 线）。分叉的时间、谁先谁后、哪些提交是一起进来的，全都留在历史里。看主线用 `git log --first-parent`，得到的就是 `merge feature` → `master: unrelated` → `base`，feature 的提交被折叠成一个入口。

rebase 走完是另一张图，没有分叉（这里只列提交消息，hash 变化见下一节）：

```text
* feature: two
* feature: one
* master: unrelated
* base
```

两个 feature 提交依次叠在 master 最新提交之上，parent 是一条直线。看上去干净，但注意：**这两个提交已经不是原来那两个了**。它们是被重新创建的，消息一样、内容大致一样、hash 全不一样——下一节给证据。

这两张图没有优劣，只有取舍。分叉图能回答「这个改动是什么时候、基于什么合并进来的」；线性图能回答「从头到尾代码是怎么演进的」，`git log` 一屏读完，`git bisect` 也不会在 merge 点上分心。

## 4. 冲突要解几次

这是两种走法差别最实在的地方，也是最容易被「rebase 更干净」这句话盖过去的。

merge 只解一次。冲突发生在两个分支的最终状态之间，git 做一次三方合并，把结果落成一个 merge commit。中间那些提交长什么样，它根本不看。

rebase 是逐提交重放，每重放一个就要做一次三方合并。两个提交都碰第 5 行，于是（这一组的两个提交消息就叫 `feature A` / `feature B`，名字不影响结果）：

```text
$ git rebase master
Rebasing (1/2)
CONFLICT (content): Merge conflict in app.txt
# 手工解冲突，然后
$ git add app.txt && git rebase --continue
Rebasing (2/2)
CONFLICT (content): Merge conflict in app.txt
error: could not apply fc9dd29... feature B
```

**同一个区域冲突两次。** 第一次解完，`--continue` 之后第二个提交还要再打一遍补丁，而它期望的上下文已经被第一次的解法改了，于是又冲突。

机制上说清楚：

- merge 比较的是两棵**最终树**，base 是 merge-base。冲突数取决于「有多少个区域被两边同时改过」，跟中间提交数无关。
- rebase 比较的是**每个提交的 patch** 和「当前的新基底」。第一个提交重放完，新基底已经带上了你的改动，第二个提交的相对 diff 再往上叠，自然还会撞。

所以冲突次数的规律是：**rebase 的冲突次数 ≈ 触及同一区域的提交数**，merge 的冲突次数 ≈ 冲突区域数。前者可能远大于后者。

这带来一个更隐蔽的问题：**你会解两次，而且两次的解法可能不一致**。第一次你决定「保留 master 的写法 + 加自己的逻辑」，第二次面对被改过的上下文，很可能随手选了个不一样的组合。merge 只有一次决策，rebase 有 N 次，语义漂移的机会也就是 N 次。

反过来说，如果 feature 的提交分散在不同文件、不同区域，rebase 的每个重放都能干净应用，一次冲突都没有——这时候「rebase 冲突多」不成立，成本为零。

## 5. hash 与强推

rebase 改的是提交对象本身。commit 对象的内容包括 tree、parent、author、message，**parent 一变，整个对象的 hash 就变**。

```bash
# 作用：rebase 前后各记一次 hash，对比同一批提交
git log --oneline feature
git rebase master
git log --oneline feature
git reflog
```

```text
# rebase 前
7f73bc2 c2
853d99c c1

# rebase 后
95939ea c2
f33dd69 c1
```

`c1` 从 `853d99c` 变成 `f33dd69`，`c2` 从 `7f73bc2` 变成 `95939ea`。消息一样，内容是同一个改动，但对象是新的。

reflog 把过程记得很清楚：

```text
95939ea HEAD@{0}: rebase (finish): returning to refs/heads/feature
95939ea HEAD@{1}: rebase (pick): c2
f33dd69 HEAD@{2}: rebase (pick): c1
971061f HEAD@{3}: rebase (start): checkout master
```

`rebase (start)` 记下起点，`rebase (pick)` 一条一条重放，`rebase (finish)` 收尾。rebase 之前的 tip `7f73bc2` 仍然能从 reflog 里翻到，`git reset --hard 7f73bc2` 就回去了——**这是唯一的后悔药**，因为它只是一个本地日志，换机器或过了 `gc.reflogExpire` 就没了。

后果分两种情况：

- **没推送过**：无所谓，本地随便 rebase，反正没人见过旧 hash。
- **已经推送过**：远端还是旧 hash，本地是新 hash，两边对不上，普通 `git push` 会被拒。只能强推，而强推会让所有基于旧 hash 工作的人脱节——他们的本地分支指向一堆远端已经不存在的提交，`git pull` 会重新拉一遍，日志里出现两份内容相同的提交。

所以规则很硬：**公共分支永不 rebase，个人分支 rebase 前先记下原 tip**。记法有两种，任选：

```bash
# 作用：留一个备份分支，出问题直接 reset 回来
git branch backup/feature-before-rebase

# 作用：或者只记 hash，事后 git reset --hard <hash> 也能回去
git rev-parse HEAD
```

强推也要挑方式：

```bash
# 作用：只在远端仍是你上次看到的位置时才推，别人推过就失败
git push --force-with-lease

# 不要用这个：无条件覆盖，别人刚推的提交会被静默丢掉
git push --force
```

`--force-with-lease` 检查的是「远端 ref 是否还等于我本地的 remote-tracking ref」。中间有人推过，它就拒绝，把覆盖别人工作的机会挡掉。它不是万能的（`git fetch` 之后 lease 会被更新），但比 `--force` 好一个数量级。

## 6. rerere

长期分支反复 rebase，同一个冲突会遇到很多次。`rerere` 就是为这个场景做的：**reuse recorded resolution**，记住「这个冲突块上次是怎么解的」，下次自动套用。

```bash
# 作用：开启冲突解法记录，一次性配置
git config rerere.enabled true
```

第一次 rebase，冲突照常出现，手工解完：

```bash
# 作用：解冲突、标记已解决、继续 rebase
$EDITOR f.txt
git add f.txt
git rebase --continue
```

解完之后 `.git/rr-cache/` 里会多一个目录，目录名是冲突块的 hash：

```text
.git/rr-cache/0149dfc357e741472eba1cf23c12ded6b1557708
```

里面两个文件：`preimage` 是冲突时的原始块（带 `<<<<<<<` 的那些行），`postimage` 是你解完之后的样子。

现在把分支重置回 rebase 之前，再 rebase 一次同样的冲突：

```bash
# 作用：回到 rebase 前的状态，重放同一个冲突
git reset --hard backup/feature-before-rebase
git rebase master
```

```text
CONFLICT (content): Merge conflict in app.txt
Resolved 'f.txt' using previous resolution.
```

**没有让你动手。** git 认出这个冲突块和上次一样，直接把 `postimage` 写了进去。文件里已经是解好的内容，只剩 `git add` + `git rebase --continue` 两个动作。

几点必须知道：

1. **它只解决文本冲突，不解决语义冲突**。两次冲突的上下文可能已经不同，套用旧解法未必还对。所以 `rerere` 之后要 `git diff` 看一眼，别闭眼 `--continue`。
2. **它不会替你 `git add`**。默认只是把文件写成解好的样子，状态还是 `UU`，得自己标记。想让 git 顺手 stage，可以开 `git config rerere.autoupdate true`。
3. **记录是本地的**。`.git/rr-cache` 不进版本库，换机器就没了。想团队共享得自己同步这个目录。
4. **错了要清**。某个记录解错了，直接删 `.git/rr-cache/<hash>`，或者 `git rerere forget <file>` 只忘掉某个文件的记录。

它最适合的场景：一个长命的功能分支，每周 rebase 一次 main，每次都在同样的几个文件上冲突。第一次手工解，后面全自动。反过来，一次性的 rebase 开它没意义，纯属多写两个文件。

## 7. 团队怎么选

规则比工具重要。我现在的用法：

| 分支 | 允许的操作 | 理由 |
| --- | --- | --- |
| `main` / `develop` / 任何公共分支 | **只 merge，永不 rebase** | 别人都在上面工作，hash 一变全体脱节 |
| 个人功能分支（没别人用） | 可以 rebase，保持线性 | 只有自己受影响，收益是历史干净 |
| 已开 PR 且有人在 review 的分支 | 谨慎 rebase，rebase 后通知 | review 评论挂在旧提交上，rebase 后对不上 |
| 已经合并进主线的分支 | 不要再动 | 再 rebase 等于重写已发布的历史 |

两条具体流程：

```bash
# 作用：个人分支跟主线，保持线性（推荐日常用这个）
git fetch origin
git rebase origin/main
# 有冲突就解，解完 git add + git rebase --continue
git push --force-with-lease

# 作用：功能分支进主线，保留合并痕迹（推荐合并时用这个）
git checkout main
git pull --ff-only
git merge --no-ff feature/login
git push
```

还有一条容易忽略的：**拉取公共分支时用 `git pull --rebase`**，否则每次 `git pull` 都会产生一个没信息量的 merge commit（"Merge branch 'main' of ..."），历史会被这些噪音填满。这条和个人分支 rebase 是一个道理：本地的、没推送的提交，重写没有成本。

`squash` 是第三种选择，值得单独提一句：把整个 feature 压成一个提交再合并，历史最干净，但**丢掉了开发过程的粒度**，`git bisect` 和 `git blame` 都会退化。它适合「一个小功能就该是一个提交」的场景，不适合需要追溯中间决策的改动。

## 8. 常见坑

1. **在公共分支上 rebase**。最严重的一个。hash 全变，所有人的本地分支脱节，而且 `reflog` 只在你自己的机器上，救不回来。
2. **用 `--force` 而不是 `--force-with-lease`**。前者无条件覆盖，别人刚推的提交会静默消失，连报错都没有。
3. **以为 rebase 只解一次冲突**。实测两个提交碰同一区域就是两次，而且是同一处。提交越多，重复劳动越多。
4. **rebase 前没记原 tip**。`reflog` 默认只保留 90 天，且是本地的；一旦 gc 或者换机器，旧提交就真没了。养成 `git branch backup/xxx` 的习惯。
5. **rerere 自动套用后不看 diff**。旧解法套在新上下文上，可能是错的，而且不报错。`git diff` 一秒的事。
6. **rebase 完直接 `git push`**。会被拒，然后有人顺手加 `--force`——这就是第 2 条的事故路径。
7. **rebase 之后同事 `git pull`**。默认 merge 策略会把旧提交和新提交都拉下来，日志里出现两份一样的改动。正确做法是让对方 `git fetch && git reset --hard origin/<branch>`。
8. **把 merge 当成「不专业」**。merge commit 是有信息量的：它记录了「这批改动是一起合进来的」。为了图好看硬 rebase 公共分支，是拿协作成本换审美。

## 9. 重点总结

**两种走法改的是不同的东西：merge 改的是「引用指向哪」，rebase 改的是「提交本身」。**

1. **冲突成本不对称**。merge 只在实际合并那一刻解一次；rebase 每个触及同一区域的提交都要解一次。实测两个提交、同一区域，merge 一次，rebase 两次（`Rebasing (1/2)` → `Rebasing (2/2)`，第二次 `could not apply fc9dd29... feature B`）。提交越碎、改得越集中，rebase 的重复劳动越明显。
2. **rebase 重写历史，hash 必然变**。`853d99c` → `f33dd69`、`7f73bc2` → `95939ea`，reflog 里逐条 `rebase (pick)` 加一条 `rebase (finish)`，原 tip 是唯一的回滚线索。已推送的分支 rebase 之后必须 `--force-with-lease`，并且要接受同事本地副本脱节这个事实。
3. **`rerere` 把重复冲突变成一次性成本**。开启后第一次手工解，`.git/rr-cache/<hash>` 记下 preimage/postimage，同一个冲突再来时直接 `Resolved 'f.txt' using previous resolution.`。它省的是重复劳动，不是判断——套用完还是要看一眼 diff。

实践上就三句话：**公共分支只 merge，个人分支随便 rebase，rebase 之前先备份、之后用 `--force-with-lease`。**

## 10. 参考

- [`git rebase` 文档](https://git-scm.com/docs/git-rebase)（`--onto`、`--continue`、`--abort` 的完整语义）
- [`git merge` 文档](https://git-scm.com/docs/git-merge)（`--no-ff`、`--ff-only` 与三方合并的冲突判定）
- [`git rerere` 文档](https://git-scm.com/docs/git-rerere)（`rr-cache` 的 preimage/postimage 结构，`rerere.autoupdate`）
- [`git push --force-with-lease`](https://git-scm.com/docs/git-push#Documentation/git-push.txt---force-with-lease)（lease 检查的确切条件）
- [Pro Git: Rebasing](https://git-scm.com/book/zh/v2/Git-%E5%88%86%E6%94%AF-%E5%8F%98%E5%9F%BA)（「不要对已推送到公共仓库的提交执行 rebase」的原始论述）
- 同系列：`multi-agent-worktree`（worktree 隔离了什么、没隔离什么；合并冲突那一节正好是这篇的前提）
- 实测工程：git 2.56.0.windows.3 / Windows 11，四组独立仓库，`merge --no-ff` 图、rebase 冲突计数、hash 前后对比、rr-cache 落盘的原始输出见正文
