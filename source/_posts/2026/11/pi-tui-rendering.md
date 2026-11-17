---
title: Pi 源码解读（八）：终端渲染——终端里的界面工程
slug: pi-tui-rendering
date: 2026-11-17 21:00:00
description: 深入 pi-tui 源码，拆解其声明式布局、帧渲染与终端适配机制，看一个纯文本约束下的终端界面库如何做几何计算、差分绘制与跨终端兼容。
categories:
  - 技术
tags:
  - 专栏
  - Pi 源码解读
  - TypeScript
cover: /img/2026/11/pi-tui-rendering.jpg
---

在前几篇里，我们看了 Pi 的 LLM 调用、Agent 循环与工具系统。这一篇把镜头拉回到「界面」本身——Pi 里的 `pi-tui` 是一个与 Agent 完全解耦的正交终端 UI 库：它不依赖 `pi-ai`、不依赖 `pi-agent-core`，运行时依赖只有 `marked`、`marked-cjk-friendly`（Markdown 解析与 CJK 兼容处理）和 `get-east-asian-width`（东亚字符宽度计算，见 `packages/tui/package.json` 的 `dependencies`）。`pi-coding-agent` 把它当作一个普通工具包引入，通过 `@earendil-works/pi-tui` 别名解析到 `tui/dist/index.js`，在其上搭建对话界面。这种「零 Agent 依赖」的定位，是它能够被任意文本应用复用的前提。

## 一、基础与进阶用法

pi-tui 的核心抽象是**组件（Component）**。一个组件只需要实现 `render(width)`，返回当前视口宽度下的字符串行数组（见 `tui.ts:124-155`）：

```typescript
export interface Component {
  render(width: number): string[]; // 作用：给定视口宽度，返回该组件要绘制的文本行
  handleInput?(data: string): void; // 作用：获得焦点时处理键盘输入
  handleMouse?(event: TuiMouseEvent): TuiMouseEventResult | undefined; // 作用：处理归一化后的鼠标事件
  wantsKeyRelease?: boolean; // 作用：是否接收按键释放事件（Kitty 协议）
  capturesViewportInput?: boolean; // 作用：是否拦截全屏视口按键
  invalidate(): void; // 作用：主题变化或需要重绘时清空缓存
}
```

最基础的用法是组装布局。`VStack` / `HStack` 是声明式的堆叠容器，`ScrollView` 提供可滚动区域，`Text` / `Input` / `Editor` / `Markdown` 等是内置组件（导出清单见 `index.ts`）。进阶用法则涉及三件事：**布局、渲染、终端适配**。布局由 `LayoutNode` 声明（见下文）；渲染由 `renderLayoutFrame` 把布局帧绘制成屏幕行；终端适配由 `Terminal` 接口抽象，屏蔽不同终端的转义序列差异。理解这三者的分层，是读懂 pi-tui 的关键。

## 二、源码逐段拆解

### 2.1 布局节点：声明式结构

`layout-node.ts` 定义了布局的**声明式描述**，与几何计算完全分离。`LayoutNode` 只有两种形态：`vstack`/`hstack` 的堆叠节点，和 `scroll` 滚动节点（`layout-node.ts:14-42`）：

```typescript
export interface StackLayoutNode {
  type: "vstack" | "hstack"; // 作用：区分垂直或水平堆叠
  entries: readonly StackLayoutEntry[]; // 作用：子项列表，每项含组件与尺寸约束
  gap: number; // 作用：子项之间的间距
  align: "stretch" | "start" | "center" | "end"; // 作用：交叉轴对齐方式
}

export interface ScrollLayoutNode {
  type: "scroll"; // 作用：标记这是一个滚动视图节点
  component: Component; // 作用：被滚动的子组件
  state: ScrollLayoutState; // 作用：承载滚动位置与视口状态
}

export type LayoutNode = StackLayoutNode | ScrollLayoutNode; // 作用：布局节点的联合类型
```

组件若想参与布局，只需实现 `LayoutComponent`，通过一个 Symbol 方法暴露自己的布局节点（`layout-node.ts:44-51`）：

```typescript
export interface LayoutComponent extends Component {
  [LAYOUT_NODE](): LayoutNode; // 作用：返回该组件声明的布局节点
}

export function getLayoutNode(component: Component): LayoutNode | undefined {
  const candidate = component as Partial<LayoutComponent>;
  return typeof candidate[LAYOUT_NODE] === "function" ? candidate[LAYOUT_NODE]() : undefined; // 作用：安全地取出布局节点，非布局组件返回 undefined
}
```

这种设计让「普通组件」和「布局容器」用同一套 `Component` 接口，布局能力是可选叠加，而非强制约束。

### 2.2 几何计算：LayoutBox 与 LayoutFrame

`layout.ts` 负责把声明式布局**算成具体几何**。核心数据结构是 `LayoutBox`（一个组件的矩形区域、裁剪区、子节点、渲染行）和 `LayoutFrame`（整屏帧，`layout.ts:23-42`）：

```typescript
export interface LayoutBox {
  component: Component; // 作用：该盒子对应的组件
  rect: LayoutRect; // 作用：盒子在屏幕上的矩形位置与尺寸
  clip: LayoutRect; // 作用：裁剪区，超出部分不绘制
  children: LayoutBox[]; // 作用：子盒子列表
  parent?: LayoutBox; // 作用：父盒子，用于回溯
  lines?: readonly string[]; // 作用：组件渲染出的文本行
  lineOffset?: number; // 作用：内容被裁剪时起始行的偏移
  scrollView?: ScrollView; // 作用：若为滚动视图，指向其状态对象
  scrollContentLines?: readonly string[]; // 作用：滚动内容全量行，用于命中测试
  layer: number; // 作用：层级，用于命中测试时排序
}
```

布局的核心递归函数是 `layoutComponent`（`layout.ts:106-247`）。对普通组件，它直接取缓存行并分配高度；对 `vstack`，它先测量每个子项的固有高度，再通过 `allocateStackSizes` 分配可用空间并累加间距（`layout.ts:172-197`）：

```typescript
const intrinsicHeights = entries.map((entry) =>
  typeof entry.basis === "number" ? entry.basis : measureHeight(context, entry.component, safeWidth), // 作用：测量每个子项的固有高度，basis 显式指定时直接用
);
const sizes = allocateStackSizes(entries, intrinsicHeights, height, node.gap); // 作用：按 grow/shrink/minSize/maxSize 分配可用高度
const naturalHeight = sizes.reduce((sum, size) => sum + size, 0) + gapTotal; // 作用：计算自然高度（含间距）
const allocatedHeight = height === undefined ? naturalHeight : Math.max(0, Math.floor(height)); // 作用：若外部给定高度则取之，否则用自然高度
```

测量依赖一个**按宽度缓存的渲染缓存** `renderCached`（`layout.ts:68-81`），同一组件在同一宽度下只渲染一次，避免重复计算。

### 2.3 滚动条几何：纯计算

滚动条没有独立组件，而是由 `getScrollbarGeometry` 从 `LayoutBox` **纯计算**得出（`layout.ts:280-307`）：

```typescript
export function getScrollbarGeometry(box: LayoutBox, includeHiddenAuto = false): ScrollbarGeometry | undefined {
  if (!box.scrollView || box.rect.width <= 0 || box.rect.height <= 0) return undefined; // 作用：非滚动盒或尺寸非法时直接返回
  const contentHeight = box.children[0]?.rect.height ?? box.scrollContentLines?.length ?? 0; // 作用：取内容总高度
  const trackHeight = box.rect.height; // 作用：轨道高度即视口高度
  const canRevealHiddenAuto = includeHiddenAuto && box.scrollView.scrollbar === "auto" && contentHeight > trackHeight; // 作用：判断自动滚动条是否应显现
  if (!box.scrollView.isScrollbarVisible && !canRevealHiddenAuto) return undefined; // 作用：不可见且无强制显现时返回
  const minThumbHeight = Math.min(2, trackHeight); // 作用：滑块最小高度，至少 2 行
  const thumbHeight = Math.max(
    minThumbHeight,
    Math.min(trackHeight, Math.round((trackHeight * trackHeight) / contentHeight)), // 作用：滑块高度按视口/内容比例缩放
  );
  const maxScrollTop = Math.max(0, contentHeight - trackHeight); // 作用：最大可滚动距离
  const maxThumbTop = trackHeight - thumbHeight; // 作用：滑块可移动的最大偏移
  const thumbOffset = maxScrollTop === 0 ? 0 : Math.round((box.scrollView.scrollTop / maxScrollTop) * maxThumbTop); // 作用：按滚动比例换算滑块位置
  const column = box.rect.x + box.rect.width - 1; // 作用：滚动条所在列（盒子最右一列）
  if (column < box.clip.x || column >= box.clip.x + box.clip.width) return undefined; // 作用：列被裁剪则不绘制
  return { column, trackTop: box.rect.y, trackHeight, thumbTop: box.rect.y + thumbOffset, thumbHeight, maxScrollTop }; // 作用：返回完整滚动条几何
}
```

滑块高度按「视口高度²/内容高度」缩放、位置按滚动比例换算——整套滚动条是**纯算术**，不涉及任何绘制 API。

### 2.4 帧渲染：布局到屏幕

`renderLayoutFrame` 是渲染入口（`layout.ts:383-412`）：先递归布局出 `rootBox`，再初始化一张全空屏幕数组，最后 `paintBox` 递归地把每个盒子的行**合成**到屏幕上：

```typescript
export function renderLayoutFrame(
  root: Component,
  width: number,
  height: number,
  requestRender: () => void,
): LayoutFrame {
  const safeWidth = Math.max(1, Math.floor(width)); // 作用：钳制宽度到至少 1
  const safeHeight = Math.max(1, Math.floor(height)); // 作用：钳制高度到至少 1
  const context: LayoutContext = { // 作用：构造布局上下文，含视口、渲染缓存、重绘回调
    viewport: { width: safeWidth, height: safeHeight },
    renderCache: new Map(),
    requestRender,
    primaryScrollView: undefined,
  };
  const rootBox = layoutComponent(context, root, 0, 0, safeWidth, safeHeight, { x: 0, y: 0, width: safeWidth, height: safeHeight }); // 作用：从根组件开始递归布局
  const lines = Array.from({ length: safeHeight }, () => ""); // 作用：初始化全空屏幕行
  paintBox(rootBox, lines, safeWidth); // 作用：递归把各盒子内容绘制进屏幕
  return { root: rootBox, width: safeWidth, height: safeHeight, lines, ...(context.primaryScrollView === undefined ? {} : { primaryScrollView: context.primaryScrollView }) }; // 作用：返回整帧
}
```

`paintBox`（`layout.ts:330-381`）负责把盒子的行写进屏幕。它有两条路径：当盒子铺满整行且该行未被占用时走**快速路径**直接引用源行；否则用 `compositeTuiLine` 把组件行**合成**到已有行上，处理 ANSI 转义与东亚字符宽度。滚动条则在 `paintScrollbar`（`layout.ts:309-328`）中通过 `replaceScrollbarCell` 逐格替换屏幕字符，保留目标背景色。

### 2.5 命中测试

鼠标交互需要知道「点击的是哪个组件」。`getLayoutBoxesAt` 从根向下递归，收集包含该坐标的所有盒子，并按层级与深度排序，返回从最深到最浅的命中路径（`layout.ts:419-429`）：

```typescript
export function getLayoutBoxesAt(frame: LayoutFrame, x: number, y: number): LayoutBox[] {
  const result: Array<{ box: LayoutBox; depth: number }> = []; // 作用：暂存命中的盒子及其深度
  const visit = (box: LayoutBox, depth: number): void => {
    if (!containsPoint(box.clip, x, y)) return; // 作用：坐标不在裁剪区内则跳过
    result.push({ box, depth }); // 作用：记录命中盒子
    for (const child of box.children) visit(child, depth + 1); // 作用：递归子节点
  };
  visit(frame.root, 0); // 作用：从根开始遍历
  result.sort((a, b) => b.box.layer - a.box.layer || b.depth - a.depth); // 作用：先按层级、再按深度排序，越靠前越在视觉上层
  return result.map(({ box }) => box); // 作用：返回排序后的盒子路径
}
```

`getScrollViewBox` 与 `getScrollViewsAt`（`layout.ts:431-453`）则用于按滚动视图定位盒子、或查找某坐标下的所有滚动视图，支撑滚轮事件的分发。

### 2.6 终端适配：Terminal 接口

`terminal.ts` 把「终端」抽象成一个 `Terminal` 接口（`terminal.ts:86-140`），上层只依赖接口，不关心具体终端：

```typescript
export interface Terminal {
  start(onInput: (data: string) => void, onResize: () => void): void; // 作用：启动终端，注册输入与尺寸变化回调
  stop(): void; // 作用：停止并恢复终端状态
  write(data: string): void; // 作用：向终端写原始输出
  get columns(): number; // 作用：获取终端列数
  get rows(): number; // 作用：获取终端行数
  moveBy(lines: number): void; // 作用：相对移动光标
  hideCursor(): void; // 作用：隐藏光标
  showCursor(): void; // 作用：显示光标
  clearLine(): void; // 作用：清空当前行
  setTitle(title: string): void; // 作用：设置窗口标题
  setProgress(active: boolean): void; // 作用：设置进度指示（OSC 9;4）
  // … 节选：还有 restoreOnExit / drainInput / kittyProtocolActive / clearFromCursor / clearScreen / setProgramStatus
}
```

`ProcessTerminal` 是真实实现，直接读写 `process.stdin/stdout`。终端尺寸通过 `refreshTerminalDimensions` 在 POSIX 上发送 `SIGWINCH` 触发刷新（`terminal.ts:54-61`）：

```typescript
export function refreshTerminalDimensions(): void {
  if (process.platform === "win32" || process.pid <= 0) return; // 作用：Windows 与无 PID 环境跳过
  try {
    process.kill(process.pid, "SIGWINCH"); // 作用：向自身发 SIGWINCH，触发 resize 回调
  } catch {
    // Signal delivery not permitted in this environment; ignore.
  }
}
```

### 2.7 键盘协议协商

不同终端对修饰键的编码不一致，pi-tui 在启动时**主动协商** Kitty 键盘协议。`parseKeyboardProtocolNegotiationSequence` 解析终端的应答（`terminal.ts:28-39`）：

```typescript
export function parseKeyboardProtocolNegotiationSequence(
  sequence: string,
): KeyboardProtocolNegotiationSequence | undefined {
  const kittyFlags = sequence.match(/^\x1b\[\?(\d+)u$/); // 作用：匹配 Kitty 协议标志应答
  if (kittyFlags) {
    return { type: "kitty-flags", flags: Number.parseInt(kittyFlags[1]!, 10) }; // 作用：解析出已支持的标志位
  }
  if (/^\x1b\[\?[\d;]*c$/.test(sequence)) {
    return { type: "device-attributes" }; // 作用：匹配设备属性（DA1）应答，作为协议协商的哨兵
  }
  return undefined; // 作用：非协商应答返回 undefined
}
```

`ProcessTerminal` 启动时发出查询序列，若终端回复非零标志则启用 Kitty 协议，否则回退到 `modifyOtherKeys`（`terminal.ts:302-344`）。这种「渐进增强 + 哨兵回退」让协议协商无需等待固定超时。

### 2.8 Apple 终端输入归一化

Apple Terminal 会把 Shift+Enter 发成 ESC+CR，pi-tui 用 `normalizeAppleTerminalInput` 归一化（`terminal.ts:79-81`）：

```typescript
export function normalizeAppleTerminalInput(data: string, isAppleTerminal: boolean, isShiftPressed: boolean): string {
  return normalizeNativeShiftEnterInput(data, isAppleTerminal, isShiftPressed); // 作用：委托给原生 Shift+Enter 归一化
}
```

当检测到 Apple 终端且 Shift 按下、输入为 `\r` 或 `\x1b\r` 时，统一替换为标准 `NATIVE_SHIFT_ENTER_SEQUENCE`，消除平台差异。

### 2.9 交互细节：自动补全与模糊匹配

`autocomplete.ts` 定义了可插拔的补全提供者接口，`CombinedAutocompleteProvider` 合并斜杠命令与文件路径（`autocomplete.ts:268-293`）：

```typescript
export interface AutocompleteProvider {
  triggerCharacters?: string[]; // 作用：在 token 边界自然触发该提供者的字符
  getSuggestions(
    lines: string[],
    cursorLine: number,
    cursorCol: number,
    options: { signal: AbortSignal; force?: boolean },
  ): Promise<AutocompleteSuggestions | null>; // 作用：按光标位置异步返回补全建议
  applyCompletion(
    lines: string[],
    cursorLine: number,
    cursorCol: number,
    item: AutocompleteItem,
    prefix: string,
  ): { lines: string[]; cursorLine: number; cursorCol: number }; // 作用：应用选中项，返回新文本与光标位置
}
```

补全建议的排序依赖 `fuzzy.ts` 的模糊匹配。`fuzzyMatch` 用贪心对齐逐字符匹配，并综合「连续匹配奖励、间隔惩罚、词边界奖励、位置惩罚」打分（`fuzzy.ts:12-42`）：

```typescript
function scorePositions(textLower: string, positions: readonly number[]): number {
  let score = 0;
  let lastMatchIndex = -1;
  let consecutiveMatches = 0;
  for (const i of positions) {
    if (lastMatchIndex === i - 1) { // 作用：与上一匹配相邻，视为连续匹配
      consecutiveMatches++;
      score -= consecutiveMatches * 5; // 作用：连续匹配奖励，越长减分越多
    } else {
      consecutiveMatches = 0;
      if (lastMatchIndex >= 0) {
        score += (i - lastMatchIndex - 1) * 2; // 作用：匹配间隔惩罚
      }
    }
    if (i === 0 || /[\s\-_./:]/.test(textLower[i - 1]!)) {
      score -= 10; // 作用：词边界匹配奖励
    }
    score += i * 0.1; // 作用：匹配位置越靠后略微惩罚
    lastMatchIndex = i;
  }
  return score; // 作用：分数越低表示匹配越好
}
```

`fuzzyFilter` 支持空格/斜杠分词，所有 token 都需匹配后按总分升序排序（`fuzzy.ts:121-159`）。

### 2.10 按键处理

`keys.ts` 把原始转义序列解析为**逻辑按键 ID**。`parseKey` 优先走 Kitty 协议，其次 `modifyOtherKeys`，最后回退到传统序列（`keys.ts:1344-1389`）：

```typescript
export function parseKey(data: string): string | undefined {
  const kitty = parseKittySequence(data); // 作用：尝试按 Kitty 协议解析
  if (kitty) {
    const logicalShiftedSymbol = getLogicalShiftedSymbolCandidate(kitty.shiftedKey, kitty.modifier, SYMBOL_KEYS);
    return formatParsedKey(
      logicalShiftedSymbol?.codepoint ?? kitty.codepoint, // 作用：取逻辑移位符号或原码点
      logicalShiftedSymbol?.modifier ?? kitty.modifier,
      kitty.baseLayoutKey,
    );
  }
  const modifyOtherKeys = parseModifyOtherKeysSequence(data); // 作用：回退到 modifyOtherKeys 解析
  if (modifyOtherKeys) {
    // ... 类似处理
  }
  if (_kittyProtocolActive) {
    if (data === "\x1b\r" || data === "\n") return "shift+enter"; // 作用：Kitty 激活时把歧义序列解释为 Shift+Enter
  }
  const legacySequenceKeyId = LEGACY_SEQUENCE_KEY_IDS[data]; // 作用：查传统序列映射表
  if (legacySequenceKeyId) return legacySequenceKeyId;
  if (data === "\x1b") return "escape"; // 作用：裸 ESC 即 Esc 键
  if (data === "\t") return "tab"; // 作用：Tab 键
  if (data === "\r" || (!_kittyProtocolActive && data === "\n") || data === "\x1bOM") return "enter"; // 作用：回车键
  // ... 更多传统序列
}
```

`matchesKey` 则把输入序列与逻辑按键 ID（如 `ctrl+shift+d`）比对，供上层做按键绑定。`Key` 常量对象（`keys.ts:163`）用类型安全的工厂函数构造复合按键，避免字符串拼写错误。

## 三、设计思想与可迁移要点

**1. 声明式布局 + 帧渲染，布局与绘制分离。** `LayoutNode` 只描述「谁在哪、占多大」，`layoutComponent` 只算几何，`paintBox` 只负责把行画到屏幕。三者解耦后，布局可以独立测试、渲染可以独立优化（如 `renderCached` 的按宽度缓存）。这种「结构—几何—像素」的三段式，是纯文本 UI 也能获得可维护性的关键。

**2. 纯文本约束下的界面抽象。** 没有 DOM，没有浏览器布局引擎，pi-tui 自己算几何：字符宽度用 `get-east-asian-width` 处理全角/半角，滚动条用纯算术，裁剪用矩形求交，命中测试用深度遍历。它把「终端」当成一个**受限的、可编程的画布**，用计算弥补没有原生布局的短板。

**3. 零 Agent 依赖的可复用性。** pi-tui 不引用 `pi-ai` / `pi-agent-core`，运行时依赖仅 `marked`、`marked-cjk-friendly` 与东亚宽度库。正因如此，任何需要终端界面的工具都能直接复用，`pi-coding-agent` 也只是把它当普通工具包引入。**依赖方向的单向性**是可复用性的根基——UI 层不应反向依赖业务层。

**4. 滚动视图与滚动条的纯计算实现。** 滚动位置、滑块几何、命中测试全部是确定性的纯函数，不触碰任何绘制 API。这意味着滚动行为可以脱离渲染独立推理、独立测试，也方便在不同渲染后端间移植。

**5. 接口抽象屏蔽终端差异。** `Terminal` 接口把转义序列、尺寸查询、协议协商收拢到一处；键盘协议用「查询 + 哨兵回退」渐进增强；平台特例（Apple Terminal 的 Shift+Enter、Windows 的 VT 输入）集中归一化。上层组件面对的是一个稳定的、逻辑化的终端，而非千奇百怪的终端实现。

## 重点总结

- pi-tui 是与 Agent 解耦的正交终端 UI 库，运行时依赖仅 `marked`、`marked-cjk-friendly` 与 `get-east-asian-width`，被 `pi-coding-agent` 当工具包复用。
- 布局分三层：`LayoutNode` 声明结构、`layoutComponent` 算几何、`paintBox` 绘制，`renderLayoutFrame` 串联成整帧。
- 滚动条、命中测试、滚动视图定位都是**纯计算**，不依赖绘制 API，可独立推理与测试。
- `Terminal` 接口抽象终端差异，键盘协议用渐进增强协商，平台输入用归一化函数收敛。
- 模糊匹配与自动补全构成交互底座：`fuzzyMatch` 综合连续/边界/位置打分，`AutocompleteProvider` 可插拔。
- 核心设计思想：声明式布局 + 帧渲染、纯文本下的界面抽象、零 Agent 依赖的可复用性、纯计算的滚动实现、接口屏蔽终端差异。

## 参考
> 注：本文代码基于 v0.80.2 快照，GitHub `main` 分支可能已有微小差异。

- [pi/packages/tui/src/layout.ts](https://github.com/earendil-works/pi/blob/main/packages/tui/src/layout.ts) — 布局几何与帧渲染
- [pi/packages/tui/src/layout-node.ts](https://github.com/earendil-works/pi/blob/main/packages/tui/src/layout-node.ts) — 声明式布局节点
- [pi/packages/tui/src/terminal.ts](https://github.com/earendil-works/pi/blob/main/packages/tui/src/terminal.ts) — Terminal 接口与协议协商
- [pi/packages/tui/src/tui.ts](https://github.com/earendil-works/pi/blob/main/packages/tui/src/tui.ts) — Component、Container 与差分渲染
- [pi/packages/tui/src/autocomplete.ts](https://github.com/earendil-works/pi/blob/main/packages/tui/src/autocomplete.ts) — 自动补全
- [pi/packages/tui/src/fuzzy.ts](https://github.com/earendil-works/pi/blob/main/packages/tui/src/fuzzy.ts) — 模糊匹配
- [pi/packages/tui/src/keys.ts](https://github.com/earendil-works/pi/blob/main/packages/tui/src/keys.ts) — 按键解析
- [pi/packages/tui/src/index.ts](https://github.com/earendil-works/pi/blob/main/packages/tui/src/index.ts) — 组件导出清单
- [pi/packages/tui/package.json](https://github.com/earendil-works/pi/blob/main/packages/tui/package.json) — 依赖声明
- [pi/packages/coding-agent/package.json](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/package.json) — pi-coding-agent 引入 pi-tui 的依赖声明
