// workflows/blog-write.js
// pi 博客写作工作流 —— 调研 → 起草 → 配图 → 审查 → 修订发布
//
// 用法 A（从零调研）：
//   subagent({ workflow: "./.pi/workflows/blog-write.js", args: {
//     topic: "Hono 入门到进阶", slug: "hono-intro"
//   } })
//
// 用法 B（已有原文，直接写）：
//   subagent({ workflow: "./.pi/workflows/blog-write.js", args: {
//     topic: "Agent 状态机", slug: "agent-state-machines", source: "<原文全文>"
//   } })
//
// args:
//   topic    必填，文章主题
//   slug     可选，文件名/URL slug，默认 new-post
//   category 可选，分类，默认 "技术"
//   tags     可选，标签数组
//   source   可选，原文全文（给了就跳过调研，直接起草）
//   repo     可选，博客仓库路径，默认 D:/notes/blog-hexo（Windows 原生路径，别写 /d/...）
//
// 规则来自实际踩坑（封面两路、分类路径同步、构建验证），细节见 .pi/skills/hexo-anzhiyu-post/SKILL.md

const topic = args.topic || "未命名主题";
const slug = args.slug || "new-post";
const category = args.category || "技术";
const tags = (args.tags || []).join(", ");
const source = args.source || "";
const repo = args.repo || "D:/notes/blog-hexo";

// ── 本仓库的硬规则（都是实际踩过的坑，细节见 .pi/skills/hexo-anzhiyu-post/SKILL.md）──
const RULES = [
  "分类只能是 技术 / 笔记 / 折腾 之一；新增分类必须同时改两处：",
  "  _config.yml 的 category_map（技术→tech、笔记→notes、折腾→tinkering）",
  "  _config.anzhiyu.yml 的 home_top.category[].path（必须写映射后的英文路径，写中文就 404）",
  "frontmatter 的 date 写中午 12 点（如 2026-11-04 12:00:00）：GitHub Actions 跑在 UTC，",
  "  只写日期会被算成前一天。",
  "不碰 themes/：样式只进 source/css/custom.css，主题配置只进 _config.anzhiyu.yml。",
  "图片跟文章走：封面放 source/img/<年>/<月>/（frontmatter cover 写 /img/<年>/<月>/<slug>.jpg），",
  "  站点级图片（默认封面、banner）在 source/img/common/。",
  "代码块一律带语言标记；结尾章节统一「重点总结」+「参考」。",
  "标题自动编号：发布前跑 `python tools/number-headings.py <文章路径>` 给 ##（1.）/###（1.1）加序号（脚本幂等，改了标题重跑不会重复加号）；不要手写序号。"
].join("\n");

// ── 阶段 1：调研（有原文就跳过，直接当资料）──
let researchOutput;
if (source) {
  researchOutput = "【已提供原文，跳过调研，直接以原文为资料】\n\n" + source;
} else {
  const research = await runs.run("research", {
    label: "阶段1 调研：事实+大纲",
    agent: "scout",
    task: [
      "调研主题「" + topic + "」。",
      "收集：准确的事实、版本号、API 细节、最佳实践、常见坑。",
      "给出文章大纲（h2/h3），每个小节标注要讲什么。",
      "不要编造，不确定的地方标出来。"
    ].join("\n")
  });
  researchOutput = research.output;
}

// ── 阶段 2：起草 —— 一次 write 写完，不做增量 edit ──
const draft = await runs.run("draft", {
  label: "阶段2 起草：写文章",
  agent: "worker",
  task: [
    "在博客仓库 " + repo + " 写一篇关于「" + topic + "」的中文博客。",
    "",
    "⚠️ 硬性要求：",
    "- 用 write 工具**一次性写完整文件**。",
    "- 不要用 edit 一点点改——那样容易把 JSON 写坏、反复重试。",
    "- 文件写完后**立即返回路径就停**，不要再打磨、不要反复 edit。",
    "",
    "路径：source/_posts/<年>/<月>/" + slug + ".md（按写作年月分文件夹，年/月用今天的日期）",
    "",
    "frontmatter 必填：",
    "- title: " + topic,
    "- date: <今天日期> 12:00:00（**必须带中午 12 点**，只写日期会被 CI 的 UTC 算到前一天）",
    "- description: 一句话摘要",
    "- categories: 单个 " + category + "（只能 技术 / 笔记 / 折腾）",
    "- tags: " + (tags || "按主题补"),
    "- cover: /img/<年>/<月>/" + slug + ".jpg（和文章同目录；阶段 3 会真的生成这张图）",
    "",
    "⚠️ 本仓库规则（违反要重做）：",
    RULES,
    "",
    "正文风格：中文、h2/h3 分段、代码块、表格、易错点清单、参考链接。",
    "资料/大纲：",
    researchOutput,
    "",
    "写完返回：实际文件路径。"
  ].join("\n"),
  toolBudget: { soft: 24, hard: 40 }
});

// ── 阶段 3：配图 —— 框架/工具用 logo 合成封面，其余用混元生图（同主题配色）──
const cover = await runs.run("cover", {
  label: "阶段3 配图：封面图",
  agent: "worker",
  task: [
    "给文章 " + slug + "（" + repo + "）配封面图。先判断走哪条路：",
    "",
    "A. 文章讲的是某个框架/工具/库（有官方 logo）→ tools/make-covers.py 本地合成，不要用生图 API：",
    "  脚本: " + repo + "/tools/make-covers.py（PIL，logo 素材在 tools/logos/）",
    "  1. 先看 tools/make-covers.py 里的 COVERS 字典，判断这篇讲的是哪个框架/工具，能否复用已有 logo。",
    "  2. 在 COVERS 里加一条 <slug> 的配置：",
    "     dict(logo='<logo名>', name='<英文名>', color=<品牌色或 INK>, tag='<分类> · <技术栈>',",
    "          site='<官网域名>', sub='<一句中文副标题，<=20 字>')",
    "     配色：Express/Fastify/Prisma/Drizzle/Koa/Linux 用 INK（墨色 #1F2D3D）；",
    "     Hono #E36002、NestJS #E0234E、Zod #408AFF 用品牌色；对比/横评类文章用 logos=[...] 多 logo 横排。",
    "  3. logo 缺失时从 simple-icons 取：",
    "     https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/<name>.svg",
    "     栅格化成 tools/logos/<name>.png（同色剪影，1024 宽，透明底）。",
    "  4. 跑 `python tools/make-covers.py --only <slug>` 生成 900x675。脚本按「引用它的文章」自动落到 source/img/<年>/<月>/，文章还没写 frontmatter 时加 --dir 指定。",
    "",
    "B. 没有对应 logo（算法、AI 概念、项目拆解等）→ tools/hunyuan-covers.py 用混元生图：",
    "  1. 在 PROMPTS 里加一条 <slug> 的 prompt（英文，主题描述具体有画面感），",
    "     并在 TEXTS 里加一条小标题（如 '二分查找'）；小标题由脚本本地合成，不交给模型画，避免中文错字。",
    "  2. 跑 `python tools/hunyuan-covers.py --only <slug>`，脚本自动压到 900x675、落盘到文章的年/月目录并打印亮度/留白。",
    "  3. 按脚本输出的硬指标自检，不合格就改 prompt 只重跑该张：",
    "     - 平均亮度 ≥ 200（白底；脚本会警告「底色偏暗」）",
    "     - 内容距四边留白 ≥ 3%（脚本打印「留白 xx%」，低于 3% 会警告「构图贴边」）",
    "     - 无文字/字母/水印/乱码，无米黄或冷灰底，无 3D 写实",
    "     对症改词：底色不对 → `pure white background, no beige or warm tones`；",
    "     构图被裁 → `zoomed out wide shot, entire composition fully visible, nothing cropped`；",
    "     画风太实 → `flat vector illustration, no 3d, no photorealistic`；",
    "     冒出文字 → 明确 `no text, no letters, no numbers, no watermark`。",
    "",
    "配色硬约束（两条路必须一致）：白底 #FFFFFF，主题蓝 #425AEF，辅色青 #00c4b6，尺寸 900x675。",
    "最后把 frontmatter 的 cover 改成图片的实际路径（/img/<年>/<月>/<slug>.jpg），返回图片路径、尺寸、大小、自检结论。"
  ].join("\n"),
  toolBudget: { soft: 24, hard: 40 }
});

// ── 阶段 4：审查 —— 准确性/结构/代码 ──
const review = await runs.run("review", {
  label: "阶段4 审查：准确性+结构",
  agent: "reviewer",
  task: [
    "审查刚写的文章： " + repo + "/source/_posts/*/" + slug + ".md（按今天的年月找）。",
    "重点：",
    "1) 事实准确性（版本号、API、数字）",
    "2) 结构与排版（h2/h3、表格、代码块是否都带语言标记）",
    "3) 代码是否正确",
    "4) 是否有易错点清单、参考链接，结尾是否「重点总结」+「参考」",
    "5) frontmatter：categories 只能是 技术/笔记/折腾；date 必须带 12:00；cover 指向的文件要真实存在",
    "6) 站内链接：必须是绝对路径 /<年>/<月>/<slug>/，且目标文章真实存在",
    "给具体修改点，附文件+行号。只报确实成立的问题。",
    "只读不改，输出一份修改清单即可。"
  ].join("\n"),
  toolBudget: { soft: 20, hard: 36 }
});

// ── 阶段 5：修订 + 构建 + 发布（一次 write 改完整文件，再 shell 收尾）──
const publish = await runs.run("publish", {
  label: "阶段5 修订+发布",
  agent: "worker",
  task: [
    "根据审查意见修订文章（" + repo + " 里 " + slug + " 那篇）。",
    "",
    "⚠️ 修订时用 write 整文件重写，不要用 edit 增量改。",
    "",
    "然后发布（每一步都要看结果，不能跳过）：",
    "0) python tools/number-headings.py <本篇文章的 .md 路径> —— 自动给 ## / ### 加 1./1.1 序号（幂等，重跑安全）",
    "1) npx hexo clean && npx hexo generate —— 无报错、文章数正确",
    "2) python tools/check-links.py —— 有死链必须修掉再继续（非 0 返回码就是有）",
    "3) 若这篇用了新分类：确认 _config.yml 的 category_map 和 _config.anzhiyu.yml 的",
    "   home_top.category[].path 两处都同步了（少一处 → 首页分类卡片 404）",
    "4) 本地起 server 目测（有截图能力就截图）：首页卡片封面、文章页标题区、右侧目录应清晰无雾化、封面不变形",
    "5) git add -A / commit / push origin main",
    "6) 等 CI：GitHub API 未认证会 403 限流，改看 badge ——",
    "   https://github.com/dre4m1nd/dre4m1nd.github.io/actions/workflows/pages.yml/badge.svg 出现 passing",
    "7) 线上抽查：文章 URL 返回 200；/img/<slug>.jpg 的字节数与本地一致（防 CDN 缓存旧图）",
    "返回：最终 URL + 每条验证的实际结果。",
    "",
    "审查意见：",
    review.output
  ].join("\n"),
  toolBudget: { soft: 30, hard: 50 }
});

return {
  research: researchOutput,
  draft: draft.output,
  cover: cover.output,
  review: review.output,
  publish: publish.output
};
