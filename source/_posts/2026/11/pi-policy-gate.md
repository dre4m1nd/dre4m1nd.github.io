---
title: "Pi 扩展拆解：pi-policy-gate——给编码代理一道可审计的闸门"
slug: pi-policy-gate
date: 2026-11-23 14:00:00
description: "拆解 pi-policy-gate：四层配置与 trusted floor、cmd: 子命令规则、内容哈希版本化、JSONL 审计账本与离线仿真，以及它如何接进 Pi 的 tool_call、工具注入和子代理权限转发。"
categories:
  - 技术
tags:
  - pi-policy-gate
cover: /img/2026/11/pi-policy-gate.jpg
---

> 编码代理以用户的完整权限运行。一次提示注入、一次模型跑偏、一条写错的规则，都可能删掉仓库、推错分支或外泄凭证。常见做法是在每次工具调用前加一道权限闸门——但**一道你无法观测的闸门，就是一道你无法信任的闸门**。
>
> `pi-policy-gate`（v0.9.0，源码在本地 `D:\dev-environment\odd-jobs\pi-policy-gate`）想解决的就是这个问题：把权限策略从「只在运行时生效的开关」，变成**可版本化、可审计、可离线回归**的东西。它的求值内核派生自 `pi-permission-system`，本项目的增量集中在治理层与 Pi 接线层。本文按「内核 → 治理 → 接线」的顺序，按代码实际读出来的内容拆一遍。

## 1. 一、问题：权限闸门的三个盲区

一个朴素的权限系统通常长这样：读配置、匹配规则、返回 `allow` / `deny` / `ask`。它能跑，但回答不了三个问题：

1. **这个决策是哪条策略产生的？** 规则改过之后，历史决策无法追溯。
2. **策略真的按预期在工作吗？** 没有离线验证手段，只能等线上出事。
3. **日志能不能作为证据？** 记录缺失时，你分不清是「没发生决策」还是「日志被跳过了」。

对应的三个答案是：**版本化、仿真、审计**。下面先从架构看它们各自落在哪一层。

## 2. 二、整体架构

{% mermaid %}
%%{init: {'theme':'base', 'themeVariables': {'fontFamily':'inherit','fontSize':'14px','minNodeSpacing':20}}}%%
flowchart LR
    subgraph ext["接线层 extension/"]
        TC["tool_call 事件"]
        BE["before_agent_start 工具注入"]
        CMDS["/audit · /permission-system"]
    end
    subgraph gov["治理层 governance/"]
        PL["policy-pipeline 纯管线"]
        PV["policy-version 内容哈希"]
        AL["audit-ledger JSONL 账本"]
        PS["policy-simulator 离线仿真"]
    end
    subgraph core["求值内核 core/"]
        PM["PermissionManager 分层合并"]
        WM["wildcard-matcher 通配编译"]
        BC["bash-command cmd: 规则"]
    end
    TC --> PL
    TC --> AL
    CMDS --> AL
    PS --> PL
    PL --> PV
    PL --> PM
    BE --> PM
    PM --> WM
    PM --> BC
{% endmermaid %}

三层职责很清晰：

- **`core`**：纯求值，做匹配、分层、决策，不涉及运行时；
- **`governance`**：让决策可观测、可验证——版本化、审计、仿真；
- **`extension`**：和 Pi 运行时接线——事件、UI、日志、权限转发。

## 3. 三、求值内核

### 3.1. 通配匹配与 last-match-wins

规则匹配的起点，是把配置里的通配模式编译成正则。核心只有十几行，但细节不少：

```ts
// src/core/wildcard-matcher.ts:28
let escaped = pattern
  .replaceAll("\\", "/")
  .replace(/[.+^${}()|[\]\\]/g, "\\$&")
  .replace(/\*/g, ".*")
  .replace(/\?/g, ".");

if (escaped.endsWith(" .*")) {
  escaped = `${escaped.slice(0, -3)}( .*)?`;
}

return {
  pattern,
  state,
  regex: new RegExp(`^${escaped}$`, process.platform === "win32" ? "si" : "s"),
};
```

三个值得注意的点：

- **长度上限 500 字符**（`MAX_WILDCARD_PATTERN_LENGTH`）。超长模式直接编译成永不匹配的 `/$^/`。配置里的模式是用户可控的，不设限等于把正则引擎暴露给不受信任的输入。
- **结尾 `*` 编译成 `( .*)?`**，所以 `"git *"` 也能匹配 `"git"` 本身，符合直觉。
- **统一用 `s` flag，Windows 额外加 `i`**，让多行命令和大小写行为跨平台一致。

匹配本身是 **last-match-wins**：从编译数组末尾往前扫，第一个命中即返回（`findCompiledWildcardMatch`，`wildcard-matcher.ts:62`）。新规则覆盖旧规则，整个系统的排序语义都建立在这上面。

### 3.2. `cmd:` 子命令规则

精确模式仍然是精确匹配：`"git status"` 只匹配 `git status`。但真实场景里，你想对「某个子命令」设卡，而不是对某一条完整命令行设卡。于是有了 `cmd:` 前缀：

```jsonc
{
  "bash": {
    "git *": "ask",
    "cmd:git push": "deny",
    "cmd:git status": "allow"
  }
}
```

`cmd:git push` 会被编译成（`bash-command.ts:63`）：

```
^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*
(?:[^\s;|&]*[\\/])?
git(?:\.exe)?
\s+push
(?=\s|$|[;&|])
```

这段正则允许三类前缀变化：

- 前置环境变量赋值，如 `FOO=bar git push`；
- 可执行文件的路径前缀，如 `/usr/bin/git push`；
- Windows 的 `.exe` 后缀，如 `git.exe push`。

末尾的**词边界前瞻** `(?=\s|$|[;&|])` 保证 `cmd:git push` 不匹配 `git pushx`，也不会误伤 `echo git push`。它只匹配命令前缀、不关心参数，这正是子命令规则想要的行为。

`cmd:` 规则没有独立优先级，它和其他 bash 规则进同一个数组，参与同一套 last-match-wins 排序。所以顺序很重要：**先写宽泛的通配规则，后写具体的 `cmd:` 规则**，否则前者会把后者盖掉。

### 3.3. 四层配置与 trusted floor

权限配置分四层，按优先级从低到高：

| 层 | 位置 | trusted |
| --- | --- | --- |
| `global` | `~/.pi/agent/pi-permissions.jsonc` | ✅ |
| `project` | `<cwd>/.pi/agent/pi-permissions.jsonc` | ❌ |
| `agent` | `~/.pi/agent/agents/<name>.md` 的 frontmatter | ✅ |
| `projectAgent` | `<cwd>/.pi/agent/agents/<name>.md` 的 frontmatter | ❌ |

合并规则很朴素：后写覆盖先写。问题在于，项目级配置通常放在仓库里，而仓库内容是不可信的（可能来自第三方 PR）。如果项目配置能随意 `allow` 一切，这道闸门就形同虚设。

于是有了 **trusted 标记**：全局与代理配置可信，项目与项目-代理配置不可信。规则编译时保留每条的信任标记，匹配时执行一条「信任地板」逻辑：

```ts
// src/core/permission-manager.ts:442
if (match.state.state !== "deny" && !match.state.trusted) {
  const trustedFloor = findLatestTrustedPermissionMatch(patterns, name);
  if (trustedFloor?.state === "deny") {
    return trustedFloor;
  }
}
```

把结果列成表更直观：

| 可信层 | 不可信层 | 结果 |
| --- | --- | --- |
| deny | allow | **deny**（不可信层不能放宽） |
| deny | ask | **deny** |
| allow | deny | deny（收紧永远生效） |
| 无规则 | allow | allow |

项目配置可以**收紧**策略，但不能**放宽**可信层已经禁止的东西。`defaultPolicy` 的求值也保持同一语义（`resolveLayeredPermissionValue`，`permission-manager.ts:543`）。这条规则不复杂，但它体现了权限系统的核心直觉：**信任是分级的，宽严是不对称的**。

### 3.4. fail-closed 与 mtime 缓存

配套的还有两处 fail-closed 设计：

- **全局配置解析失败**（JSONC 语法错误等）时，回退为全 `ask` 的 `EMPTY_GLOBAL_CONFIG`，而不是放行（`permission-manager.ts:664`）。
- **项目配置解析失败**时，忽略项目覆盖，只保留可信层（`permission-manager.ts:696`）。

两者都没有把坏配置当成「无规则」去放行。每个配置源按文件 `mtimeMs` 做 stamp 缓存，`getPolicyCacheStamp()` 把所有路径的 stamp 拼起来；策略文件一改，缓存自动失效。解析失败的版本也会被缓存并告警，不会每次调用都重复报错。

## 4. 四、治理层：让决策可验证

### 4.1. 一条纯管线，线上与离线共用

线上闸门、离线仿真器和单元测试，最容易各自实现一套逻辑，然后在某个边角情况下悄悄分叉。`pi-policy-gate` 的做法是把决策抽成纯函数：

```ts
// src/governance/policy-pipeline.ts:42
export function evaluateToolCall(
  manager: PermissionManager,
  toolName: string,
  input: unknown,
  agentName?: string,
): PipelineDecision {
  const check = manager.checkPermission(toolName, input, agentName);
  const policyVersion = computePolicyVersion(manager.getEffectivePolicy(agentName));
  return { ...check, decision: check.state, policyVersion };
}
```

它不提示、不拦截、不修改状态，只返回「如果现在执行，闸门会怎么判」。调用方（`tool_call` 处理器、仿真器、测试）各自决定如何处置。

这个设计的经济价值在于：**仿真器的通过率就是对线上行为的承诺**。仿真通过，意味着线上闸门在同样的输入下会给出同样的决策。后面所有治理能力都建立在这个前提上。

### 4.2. 策略版本化

版本号不是来自配置文件的修改时间，而是来自**有效策略的内容哈希**。

计算前先做规范形式化：只保留合法的状态值，每个规则映射按键排序，再稳定地序列化（`policy-version.ts:25-71`）。于是同一套规则，无论写在哪个文件、键顺序如何、用什么格式，都得到同一个哈希。版本号形如 `v1-4bf3693a1ca9711b`。

```ts
// src/governance/policy-version.ts:80
export function computePolicyVersion(policy: GlobalPermissionConfig): string {
  const canonical = toCanonicalPolicy(policy);
  const digest = createHash("sha256").update(stableStringify(canonical)).digest("hex");
  return `v1-${digest.slice(0, 16)}`;
}
```

这带来两个能力：

- 每条审计记录都带产生它的版本，历史决策可以追溯到确切的策略内容；
- `diffPolicies()` 可以生成两个版本之间的人类可读差异，解释「决策为什么变了」。

关键是**哈希的是合并后的有效策略**，而不是单个文件。分层配置下，最终生效的规则集合才是决策的真正来源。

### 4.3. 审计决策账本

每个终态决策追加一行 JSONL 到 `~/.pi/agent/audit/decisions-<日期>.jsonl`（可用 `PI_POLICY_GATE_AUDIT_DIR` 覆盖目录），再由 `readRecent()` 汇总给 `/audit` 命令。

设计上有一条硬规则：**账本是纯副作用**。写入失败被完整吞掉：

```ts
// src/governance/audit-ledger.ts:94
append(entry): void {
  try {
    mkdirSync(this.dir, { recursive: true });
    appendFileSync(auditFilePathForDate(this.dir), `${JSON.stringify(full)}\n`, "utf-8");
  } catch {
    // Audit is a side effect. A failed write must not change the decision.
  }
}
```

这条规则的正确性在于：权限闸门不能因为日志磁盘满了而被绕过；同时「缺少记录」的语义保持诚实——它只意味着决策路径没走到账本，而不是日志被静默跳过。

写入前，主体（命令或资源）会过一遍保守脱敏（`audit-ledger.ts:56`）：厂商密钥形态（`sk-`、`ghp_`、`xoxb-` 等）、`Bearer` token、`key=value` 形式的秘密，以及 32 位以上的不透明令牌。普通命令和路径保持不变——脱敏过猛会让审计失去价值。

一个需要知道的边界：审计挂在 `tool_call` 主检查的终态上。技能文件读取这类前置分支，在 `allow` 时会直接放行，不经过账本。把 JSONL 当完整决策日志用之前，得先接受这个覆盖范围。

`/audit` 默认展示最近 20 条决策并按 `allow` / `deny` / `ask` 计数，`/audit export <path>` 把记录写成 JSONL，交给 CI 或事后审查。

### 4.4. 离线仿真

仿真器用一份固定语料（`samples/policy-corpus.json`）跑有效策略，输出四类信息：

- **决策矩阵**：每个样本的预期决策 vs 实际决策；
- **规则覆盖率**：每条规则被触发了多少次；
- **死规则**：从未匹配任何样本的规则（`defaultPolicy` 兜底项除外）；
- **决策 diff**：两个策略版本之间哪些样本翻转了决策。

它和线上闸门共用 `evaluateToolCall`，配置也通过同一个 `PermissionManager` 加载。跑一次：

```bash
$ bun scripts/policy-simulator.ts
=== SIMULATION (policy v1-4bf3693a1ca9711b) ===
...
Summary: 19/19 passed, coverage 1

RESULT: PASS — all samples match expected decisions.
```

死规则检测是这里面最实用的一个：写了一条规则却永远不生效，是权限配置里最常见的隐性 bug。而 `--base <policy-dir>` 的决策 diff，让「改策略」从拍脑袋变成有回归保障的操作。

## 5. 五、接进 Pi 运行时

`tool_call` 处理器是真正的闸门。它的决策链比想象中长：

{% mermaid %}
%%{init: {'theme':'base', 'themeVariables': {'fontFamily':'inherit','fontSize':'14px','minNodeSpacing':20}}}%%
flowchart TD
    A["tool_call"] --> B{"工具已注册?"}
    B -- "否" --> X["block"]
    B -- "是" --> C{"读技能文件?"}
    C -- "是" --> D{"skill 权限"}
    D -- "deny / 无法确认" --> X
    C -- "否" --> G{"路径在 cwd 外?"}
    G -- "是" --> H{"external_directory"}
    H -- "deny / 无法确认" --> X
    G -- "否" --> F["主检查 + 会话审批"]
    F --> K{"state"}
    K -- "deny" --> X
    K -- "ask" --> L{"能弹窗?"}
    L -- "否" --> X
    L -- "是" --> M["Once / Always<br/>Reject"]
    M -- "拒绝" --> X
    M -- "批准" --> Q["放行并记账"]
    K -- "allow" --> Q
{% endmermaid %}

几个细节：

- **工具注入在更早发生**：`before_agent_start` 阶段就把被 `deny` 的工具从可用工具列表里摘掉（`shouldExposeTool` + `pi.setActiveTools`）。代理根本看不到它——这比「调用时再拦」更干净。`read` 有个例外：如果代理显式允许了技能，`read` 会保留，但 `tool_call` 会把读取范围限制在技能文件内。
- **技能文件读取**走独立的 `skill` 权限；用户显式 `/skill:xxx` 请求时记入白名单，不再拦截。
- **工作目录外访问**走 `external_directory` 特殊权限。这是防止代理乱翻文件系统的关键。
- **「始终允许」**写入会话级审批表（`SessionApprovalStore`）。它作用在策略结果之上，但不会覆盖 `deny`——`applyPatternApprovalState` 看到 `deny` 直接返回。
- **无法确认时一律拒绝**：没有交互 UI、又不是子代理，就直接 block。`ask` 分支里没有 UI 时还会先记一条 `deny` 审计：

```ts
// src/extension/index.ts:2222
if (!canRequestPermissionConfirmation(ctx)) {
  writeReviewEntry("permission_request.blocked", {
    /* ... */
  });
  recordAudit("deny", false);
  return { block: true, reason: unavailableReason };
}
```

### 5.1. 子代理的权限转发

子代理没有 UI，遇到 `ask` 时只能把请求**转发给父会话**。实现方式是一套基于文件系统的协议：

- 子代理把请求写入当前会话的 `requests/` 目录，带 `id`、`responseNonce`、请求方/目标会话 ID；
- 父会话用 `fs.watch` 监听目录，并保留 2 秒一次的轮询兜底；
- 用户确认后，响应写入 `responses/`；
- 响应必须匹配请求 ID 与 32 字节随机 nonce（`timingSafeEqual` 常时比较），且来自目标会话；
- 十分钟超时自动拒绝。

Windows 下 `fs.watch` 可能漏掉原子重命名事件，所以即使 watch 正常也保留轮询：

```ts
// src/extension/index.ts:1715
permissionForwardingFallbackTimer = setInterval(
  queueForwardedPermissionRequestScan,
  PERMISSION_FORWARDING_POLL_INTERVAL_MS,
);
```

还有一个容易被忽略的细节：调试日志里**不记录敏感原文**。命令、提示语、拒绝原因只记录 `{present, length, sha256}` 元数据（`createSensitiveLogMetadata`，`index.ts:373`）。调试线索保留了，敏感数据没有落盘。

## 6. 六、工程取舍

把散落的决策汇总一下：

| 问题 | 取舍 | 理由 |
| --- | --- | --- |
| 全局配置解析失败 | fail-closed，回退全 `ask` | 坏策略不能悄悄放行一切 |
| 项目配置解析失败 | 忽略项目覆盖 | 不可信层出错时只保留可信层 |
| 规则冲突 | last-match-wins | 语义简单可预测，仿真器能暴露覆盖情形 |
| 审计写入失败 | 不影响决策 | 闸门不能因日志不可用而被绕过 |
| 不可信层配置 | 只能收紧不能放宽 | 仓库里的配置不可信 |
| 正则输入 | 长度上限 + 转义 | 防灾难性回溯 |
| 死规则检测 | 排除 `defaultPolicy` | 兜底默认值不是需要被触发的规则 |
| `ask` 但无 UI | 直接拒绝 | fail-closed 贯穿始终 |
| 子代理 `ask` | 文件协议转发 + 轮询兜底 | 子代理没有 UI，跨平台 watch 不可靠 |
| 脱敏 | 保守、定向 | 移除凭证形态而不破坏命令与路径 |

## 7. 七、结语

`pi-policy-gate` 的代码量不大，但它在权限系统上补的三件事——**版本化、仿真、审计**——恰好对应了「让闸门可信」的三个必要条件：**知道它是谁（版本）、验证它会怎么做（仿真）、留下它做过什么（审计）**。

对写权限系统的人来说，最值得借鉴的可能不是任何一个具体实现，而是两个思路：

1. **把决策做成纯函数**，让线上、离线、测试共享一条路径——这是所有可验证性的前提。
2. **信任分级且宽严不对称**——不可信来源可以收紧安全边界，但永远不能放宽。

前者是工程约束，后者是安全直觉。两者加起来，才是一道可以被信任的闸门。
