// workflows/blog-write.js
// pi 博客写作工作流 —— 调研 → 起草 → 配图 → 审查 → 修订发布
//
// 用法 A（从零调研）：
//   subagent({ workflow: "./workflows/blog-write.js", args: {
//     topic: "Hono 入门到进阶", slug: "hono-intro"
//   } })
//
// 用法 B（已有原文，直接写）：
//   subagent({ workflow: "./workflows/blog-write.js", args: {
//     topic: "Agent 状态机", slug: "agent-state-machines", source: "<原文全文>"
//   } })
//
// args:
//   topic    必填，文章主题
//   slug     可选，文件名/URL slug，默认 new-post
//   category 可选，分类，默认 "技术"
//   tags     可选，标签数组
//   source   可选，原文全文（给了就跳过调研，直接起草）
//   repo     可选，博客仓库路径，默认 /d/notes/blog-hexo

const topic = args.topic || "未命名主题";
const slug = args.slug || "new-post";
const category = args.category || "技术";
const tags = (args.tags || []).join("、");
const source = args.source || "";
const repo = args.repo || "/d/notes/blog-hexo";

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
    "- date: 只写日期（如 2026-11-04），不要带时间",
    "- description: 一句话摘要",
    "- categories: 单个 " + category,
    "- tags: " + (tags || "按主题补"),
    "- cover: /img/" + slug + ".jpg",
    "",
    "正文风格：中文、h2/h3 分段、代码块、表格、易错点清单、参考链接。",
    "资料/大纲：",
    researchOutput,
    "",
    "写完返回：实际文件路径。"
  ].join("\n"),
  toolBudget: { soft: 24, hard: 40 }
});

// ── 阶段 3：配图 —— 用腾讯混元 TokenHub 生成封面 ──
const cover = await runs.run("cover", {
  label: "阶段3 配图：封面图",
  agent: "worker",
  task: [
    "给文章 " + slug + "（" + repo + "）配封面图。",
    "",
    "用腾讯混元 TokenHub API 生成（环境变量 HUNYUAN_API_KEY 里有 key）：",
    "  端点: https://tokenhub.tencentmaas.com/v1/wand/hunyuan-image/v35-generation",
    "  模型: hy-image-v3.5-preview",
    "  鉴权: Authorization: Bearer $HUNYUAN_API_KEY",
    "  参数: {\"model\":\"hy-image-v3.5-preview\",\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":<prompt>}]}],\"size\":\"1280x960\"}",
    "",
    "prompt 风格（务必遵守，保证全站统一）：",
    "  格式: 'abstract illustration of <主题描述>, dark navy background, violet and teal gradient, <风格关键词>, no text'",
    "  主题描述要具体有画面感（例：'glowing concentric onion layers with arrows spiraling' 而不是 'a picture of koa'）",
    "  风格关键词可选：clean modern tech aesthetic / cinematic depth / minimalist / no text",
    "",
    "生成后：",
    "  1. 保存到 " + repo + "/source/img/" + slug + ".jpg",
    "  2. 用 PIL 压到 900 宽（quality 85）",
    "  3. 确保 frontmatter 的 cover 字段是 /img/" + slug + ".jpg",
    "  4. 返回图片路径和大小。"
  ].join("\n"),
  toolBudget: { soft: 20, hard: 36 }
});

// ── 阶段 4：审查 —— 准确性/结构/代码 ──
const review = await runs.run("review", {
  label: "阶段4 审查：准确性+结构",
  agent: "reviewer",
  task: [
    "审查刚写的文章： " + repo + "/source/_posts/*/" + slug + ".md（按今天的年月找）。",
    "重点：",
    "1) 事实准确性（版本号、API、数字）",
    "2) 结构与排版（h2/h3、表格、代码块）",
    "3) 代码是否正确",
    "4) 是否有易错点清单、参考链接",
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
    "然后发布：",
    "1) npx hexo clean && npx hexo generate，确认无报错",
    "2) git add / commit / push origin main",
    "3) 等 CI 后确认线上 URL 可访问（/年/月/" + slug + "/），返回最终 URL",
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
