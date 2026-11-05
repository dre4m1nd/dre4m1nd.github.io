// workflows/blog-normalize.js
// pi 博客整理工作流 —— 扫描 → 定规范 → 分批整理 → 校验 → 发布
//
// 用法：
//   subagent({ workflow: "./.pi/workflows/blog-normalize.js", args: {
//     repo: "D:/notes/blog-hexo",
//     batchSize: 5
//   } })
//
// 做的事（对全站笔记统一）：
//   1. date 只写日期，不带时间
//   2. 结尾章节统一：常见坑 → 重点总结；易错点 → 重点总结
//   3. 缺结尾章节的补上「重点总结」
//   4. 统一 markdown 风格：代码块语言标记、表格、h2/h3 层级
//   5. 修死链、检查 frontmatter 完整性

const repo = args.repo || "D:/notes/blog-hexo";
const batchSize = args.batchSize || 5;

// ── 阶段 1：扫描 —— 出问题清单 ──
const scan = await runs.run("scan", {
  label: "阶段1 扫描：全站笔记体检",
  agent: "scout",
  task: [
    "扫描 " + repo + "/source/_posts 下所有 .md 笔记，输出问题清单：",
    "",
    "1) frontmatter 问题：",
    "   - date 是否带时间（应为纯日期 YYYY-MM-DD）",
    "   - 缺 title/description/categories/tags/cover 的",
    "   - date 与所在文件夹的年月是否一致",
    "2) 结尾章节不统一：列出每篇用了哪种（常见坑 / 常见坑清单 / 易错点 / 易错点清单 / 重点总结 / 无）",
    "3) markdown 问题：",
    "   - 代码块没写语言标记",
    "   - 标题层级跳级（h2 直接到 h4）",
    "   - 表格格式坏掉的",
    "4) 内容问题：",
    "   - 站内链接指向不存在的路径",
    "   - 明显重复的段落",
    "",
    "输出：按文件分组的清单，每项标注具体位置。不要改文件，只诊断。"
  ].join("\n"),
  toolBudget: { soft: 30, hard: 50 }
});

// ── 阶段 2：定规范 —— 写一份整理标准 ──
const spec = await runs.run("spec", {
  label: "阶段2 定规范：统一标准",
  agent: "scout",
  task: [
    "根据下面这份体检清单，写一份「整理规范」，明确：",
    "",
    "1) frontmatter 标准格式（date 纯日期、必填字段）",
    "2) 结尾章节标准：统一用「重点总结」",
    "   - 原来叫「常见坑」/「常见坑清单」/「易错点」/「易错点清单」的，改名为「重点总结」",
    "   - 内容从「罗列坑」改写为「提炼全文重点」（一句话结论 + 关键点 + 容易忽略的地方）",
    "   - 原本没有结尾章节的，补一个「重点总结」",
    "3) markdown 标准：代码块必须带语言标记、标题不跳级",
    "",
    "输出：一份可直接执行的规范文档。",
    "",
    "体检清单：",
    scan.output
  ].join("\n"),
  toolBudget: { soft: 20, hard: 36 }
});

// ── 阶段 3：分批整理（每批一个 worker，避免单次上下文过大）──
// 先让 scout 给出文件分组
const groups = await runs.run("groups", {
  label: "阶段3a 分组：把笔记切成批次",
  agent: "scout",
  task: [
    "把 " + repo + "/source/_posts 下所有 .md 笔记按 " + batchSize + " 篇一批分组。",
    "输出 JSON：{ batches: [ { id: 1, files: [\"相对路径\", ...] }, ... ] }",
    "只输出 JSON，不要别的。"
  ].join("\n"),
  outputSchema: {
    type: "object",
    properties: {
      batches: {
        type: "array",
        maxItems: 8,
        items: {
          type: "object",
          properties: {
            id: { type: "number" },
            files: { type: "array", items: { type: "string" } }
          },
          required: ["id", "files"],
          additionalProperties: false
        }
      }
    },
    required: ["batches"],
    additionalProperties: false
  },
  toolBudget: { soft: 12, hard: 24 }
});

const batchList = groups.structuredOutput.batches.slice(0, 8);

// 每个批次并行整理
const normalized = await runs.all(
  batchList.map(function (batch) {
    return {
      key: "batch-" + batch.id,
      label: "阶段3b 整理第 " + batch.id + " 批（" + batch.files.length + " 篇）",
      agent: "worker",
      task: [
        "按整理规范，整理下面这些笔记（仓库 " + repo + "）：",
        batch.files.join("\n"),
        "",
        "⚠️ 硬性要求：",
        "- 用 write 一次性重写整个文件，不要用 edit 一点点改。",
        "- 只改格式和结尾章节，不要改正文内容的意思。",
        "- 保持原有的代码块、表格、链接不变。",
        "",
        "整理规范：",
        spec.output
      ].join("\n"),
      toolBudget: { soft: 40, hard: 60 }
    };
  })
);

// ── 阶段 4：校验 ──
const check = await runs.run("check", {
  label: "阶段4 校验：整理后复查",
  agent: "reviewer",
  task: [
    "复查 " + repo + "/source/_posts 下所有笔记，确认整理是否到位：",
    "1) 所有 date 都是纯日期（无时间）",
    "2) 所有笔记结尾都是「重点总结」+「参考」",
    "3) 代码块都有语言标记",
    "4) 没有内容被误删（对比 git diff）",
    "5) 站内链接都是绝对路径 /<年>/<月>/<slug>/，且指向真实存在的文章",
    "6) categories 都在 _config.yml 的 category_map 里（技术/笔记/折腾）",
    "",
    "用 git diff --stat 看改动范围，如果某篇改动过大（超过原文 50%），标出来人工复核。",
    "输出：通过/未通过的项目清单。",
  ].join("\n"),
});

// ── 阶段 5：构建 + 发布 ──
const publish = await runs.run("publish", {
  label: "阶段5 构建+发布",
  agent: "worker",
  task: [
    "在 " + repo + " 构建并发布（每步看结果，不许跳过）：",
    "1) npx hexo clean && npx hexo generate —— 无报错、文章数正确",
    "2) python tools/check-links.py —— 有死链必须修掉再继续（非 0 返回码就是有）",
    "3) 若这批改了分类：确认 _config.yml 的 category_map 和 _config.anzhiyu.yml 的 home_top.category[].path 两处同步",
    "4) 本地起 server 目测：首页卡片封面、文章页章节/代码块、右侧目录应清晰无雾化",
    "5) git add -A && git commit && git push origin main",
    "6) 等 CI（GitHub API 未认证会 403 限流，看 badge：pages.yml badge.svg 出现 passing），线上抽查 2-3 篇 200",
    "返回：最终状态 + 每条验证的实际结果。",
    "校验结果：",
    check.output
  ].join("\n"),
  toolBudget: { soft: 30, hard: 50 }
});

return {
  scan: scan.output,
  spec: spec.output,
  batches: batchList.length,
  normalized: normalized.map(function (r) { return r.output; }),
  check: check.output,
  publish: publish.output
};
