---
name: hexo-anzhiyu-post
description: 在这个 Hexo 8 + anzhiyu 主题的博客仓库里写/改/发布笔记。用于新建文章、填写 anzhiyu frontmatter、插入图片和提示块、本地构建验证、排查 hexo 构建或 GitHub Pages 部署问题。
---

# Hexo + anzhiyu 写笔记

## 仓库事实（先记住这些，别乱找）

- 文章只放 `source/_posts/`，文件名就是 URL slug（`new_post_name: :title.md`，permalink `:year/:month/:day/:title/`）
- 主题在 `themes/anzhiyu/`：**不要改主题里的文件**，升级会覆盖。自定义只有三条合法路径：
  1. `_config.anzhiyu.yml`（主题配置的用户级覆盖，优先于 `themes/anzhiyu/_config.yml`）
  2. `source/css/custom.css`（已通过 `inject.head` 引入，写样式只加这里）
  3. `source/img/`（自己的图片，站内路径写 `/img/xxx.png`）
- 站点根路径是 `/`（`url: https://dre4m1nd.github.io`，仓库名 `dre4m1nd.github.io`），**不要**加 `/blog` 之类的前缀
- 部署：push `main` → `.github/workflows/pages.yml` → `npm install` → `npm run build` → 上传 `public/` 到 Pages。本地不需要 `hexo deploy`
- `public/`、`node_modules/`、`db.json` 已 gitignore；`themes/anzhiyu` 是提交进仓库的普通目录（不是 submodule）

## 写一篇新文章

```bash
npx hexo new "文章标题"          # 生成 source/_posts/文章标题.md
# 写内容，frontmatter 参考 scaffolds/post.md
npx hexo clean && npx hexo generate   # 本地验证，无报错再 push
git add -A && git commit -m "post: 文章标题" && git push
```

写完后可以 `npx hexo server` 本地预览（默认 http://localhost:4000）。

## Frontmatter（anzhiyu 实际读取的字段）

```yaml
---
title: 文章标题              # 必填
date: 2026-10-23 12:00:00
updated:                     # 留空则用 mtime（_config.yml updated_option: mtime）
description: 一句话摘要      # 首页卡片/SEO 用，index_post_content.method=2 时优先显示
cover: /img/xxx.jpg          # 封面；留空用 cover.default_cover（/img/default_cover.jpg）
top_img:                     # 文章页顶部大图；false 表示不要顶部图
categories:
  - 技术
tags:
  - Hexo
top_single:                  # 置顶单篇大卡（首页），可选
mathjax: true                # 只有需要公式时加（全局 mathjax.enable 为 false）
toc: true                    # 单篇覆盖全局目录开关
comments: true               # 单篇关评论用 false
aside: false                 # 单篇隐藏侧边栏
copyright: false             # 单篇关版权卡
highlight_shrink: true       # 代码块默认折叠
---
```

- `categories` 会生成 `/categories/分类名/` 页面；写成不存在的分类没问题，但不要写拼写错误
- 图片一律放 `source/img/`，正文写 `![](/img/a.png)`（不要用外链图床，容易挂）

## 正文可用标签（主题自带，已验证存在）

```markdown
{% note blue 'anzhiyufont anzhiyu-icon-circle-info' %}
提示块，样式可选 flat / modern / simple / disabled
{% endnote %}

{% tip %}轻量提示{% endtip %}

{% tabs test %}
<!-- tab 标题一 -->
内容
<!-- endtab -->
<!-- tab 标题二 -->
内容
<!-- endtab -->
{% endtabs %}

{% folding 折叠标题 %}
内容
{% endfolding %}

{% btn '/archives/', 按钮文字, anzhiyufont anzhiyu-icon-box-archive %}
{% label 蓝色标签 blue %}
{% kbd Ctrl %}  {% image /img/a.png, 描述, 300px %}
```

注意：`note` 内部内容按 markdown 渲染，别嵌套未闭合的代码块。

## 常见坑

- **本地 `hexo` 报 `Cannot find module './lib/parse'`**：node_modules 装坏了，跑 `npm install cross-spawn@7.0.6 --no-save` 即可（这是 `cross-spawn` 缺 `lib/parse.js`，不是 Hexo 问题）
- **时区坑（线上 URL 会和本地对不上）**：本地机器是 UTC+8，GitHub Actions 是 UTC。frontmatter 的 `date` 如果落在**凌晨 00:00–07:59（北京时间）**，CI 算出的日期会变成前一天 —— 本地是 `/2026/10/29/x/`，线上变成 `/2026/10/28/x/`。写日期时统一用 **12:00 这类中午时间**，两边就一致了。
- 仓库同时有 `package-lock.json` 和 `yarn.lock`，CI 走 `npm install`。加依赖用 npm，别用 yarn
- 构建产物残留导致页面不更新：先 `npx hexo clean`
- 改了 `_config.anzhiyu.yml` 里的颜色值必须带双引号（`"#425AEF"`），否则 YAML 解析出错
- 主题配置里 `CDN.internal_provider: local`，不要再改成外部 CDN
- `.obsidian/` 也被提交进仓库（这是 Obsidian vault），改 Obsidian 配置会产生噪音 diff，除非必要别动

## 美化改动的边界

改外观时按这个顺序，越靠前越优先：

1. `_config.anzhiyu.yml` 的开关（`h2Divider`、`table_interlaced_discoloration`、`subtitle`、`cover`…）
2. `source/css/custom.css`（只用主题已有变量：`--anzhiyu-main`、`--anzhiyu-card-bg`、`--anzhiyu-fontcolor`、`--anzhiyu-secondbg`、`--anzhiyu-secondtext`、`--anzhiyu-border-radius`、`--anzhiyu-shadow-border`、`--anzhiyu-scrollbar`；深色模式用 `[data-theme='dark']`）
3. 改完必须 `npx hexo clean && npx hexo generate` 验证通过

关掉自定义 CSS：把 `inject.head` 里那行 `<link ... custom.css>` 注释掉即可，不需要删文件。

## 改主题配置的坑（都是实际踩过的）

- **数组是按下标合并的**（Hexo 用 `hexo-util` 的 deepMerge，arrayMerge 保留 target 下标）：
  `home_top.category` 这类数组，你在 `_config.anzhiyu.yml` 写的条目数如果少于主题默认条数，剩下的 demo 项会残留。要全换就写满同样条数（3 条）。
- `peoplecanvas.enable: true` 会顶掉首页标题/副标题（渲染成粒子画布），而且它依赖一张外链图。想要标题就设 `false`。
- `wordcount.enable: true` 需要 `hexo-wordcount` 插件（已加入 `package.json`），否则构建报 `wordcount is not a function`。
- `avatar.effect: true` = 头像一直旋转。
- 作者卡 hover 时头像"下沉"其实是主题的 `#aside-content .card-info:hover .author-info-avatar { transform: scale(0) }` + `transform-origin: bottom`，已在 `custom.css` 改成头像始终可见（`opacity: 1; transform: none`）；副作用是那张绝对定位的简介（`.author-info__description`）会盖在头像上，所以同时让它 hover 保持 `opacity: 0`。
- **打赏**：`reward.enable: false` 只去掉文章页的按钮；中控台（`console.pug`）里的二维码是 `each item in theme.reward.QR_code` **无条件渲染**，而且数组按下标合并清不掉。已在 `custom.css` 用 `.console-card-group-reward { display: none }` 隐藏。
- **音乐**：两处开关 —— `aplayerInject.enable`（全局播放器资源）和 `nav_music.enable`（左下角播放器），都要关；只关一个会残留。
- 社交图标是 `social` 里的 `名称: 链接 || 图标类`，`mailto:` 链接能正常工作（`url_for` 对外部 scheme 原样返回），作者卡头像下方的图标也走同一份配置。
- 文章里有两个写死的"原创"标识，都在主题 pug 里，只能用同等选择器覆盖（`custom.css` 已改）：头部 `#post-firstinfo .meta-firstline a.post-meta-original`、底部版权卡 `#post .post-copyright__original`，做法是 `font-size: 0` + `::after { content: "AI 辅助生成" }`。
- 背景图全在 `source/img/*.svg`（手写渐变，不依赖外链图床）：`bg-banner.svg` 用于首页关于我卡片和 404 页，`cover-1/2/3.svg` 是 `cover.default_cover` 的随机封面。换图只需改这两处配置。
- `models.getAvailableOfType('image')` 目前是空的（需要 openrouter 凭证），所以想用 AI 生图得先配 `OPENROUTER_API_KEY` / `/login openrouter`。
- 首页/作者卡的 demo 内容（`home_top`、`banner`、`social`、`author_status`、`runtimeshow.publish_date`、`card_weixin` 二维码）已经换成自己的，别再抄回模板值。
- 本地 `hexo server` 不会重读配置，改完 `_config.anzhiyu.yml` 要重启 server 才看得到效果（按端口杀进程：`netstat -ano | grep :4000`）。

