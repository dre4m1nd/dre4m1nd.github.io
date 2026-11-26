---
name: hexo-anzhiyu-post
description: 在这个 Hexo 8 + anzhiyu 主题的博客仓库里写/改/发布笔记。用于新建文章、填写 anzhiyu frontmatter、插入图片和提示块、本地构建验证、排查 hexo 构建或 GitHub Pages 部署问题。
---

# Hexo + anzhiyu 写笔记

## 仓库事实（先记住这些，别乱找）

- 文章放 `source/_posts/<年>/<月>/`，**按写作年月分文件夹**（不是按主题分类），文件名就是 URL slug
  - 例：`source/_posts/2026/10/koa-intro.md` → URL `/2026/10/koa-intro/`
  - permalink 已改成 `:title/`（即文件相对路径），所以文件夹年月会直接成为 URL 的一部分；**不要再改回 `:year/:month/:day/:title/`**，否则会变成 `/2026/10/29/2026/10/xxx/` 重复日期
  - 跨文件夹/跨文章链接写绝对路径 `/2026/10/<slug>/`，移动文章后要同步改链接
- 主题在 `themes/anzhiyu/`：**不要改主题里的文件**，升级会覆盖。自定义只有三条合法路径：
  1. `_config.anzhiyu.yml`（主题配置的用户级覆盖，优先于 `themes/anzhiyu/_config.yml`）
  2. `source/css/custom.css`（已通过 `inject.head` 引入，写样式只加这里）
  3. `source/img/`（自己的图片，站内路径写 `/img/xxx.png`）
- 站点根路径是 `/`（`url: https://dre4m1nd.github.io`，仓库名 `dre4m1nd.github.io`），**不要**加 `/blog` 之类的前缀
- 部署：push `main` → `.github/workflows/pages.yml` → `check-frontmatter` → `npm ci` → 按 git 历史还原 mtime → `npm run build` → `check-links.py` → 上传 `public/` 到 Pages。本地不需要 `hexo deploy`
- **CI 是闸门，不是流水线**：frontmatter 校验或死链检查不过就直接失败、不发布（旧版本继续在线）；同一分支的连续 push 会取消前一次未完成的运行。所以本地不必反复全量验证，但推送后要看 Actions 是否绿
- **草稿**：frontmatter 加 `published: false` 即可 push 同步但不上线（Hexo 生成时跳过）；CI 会打印当前草稿数量作提醒。发布时删掉该行
- `public/`、`node_modules/`、`db.json` 已 gitignore；`themes/anzhiyu` 是提交进仓库的普通目录（不是 submodule）

## 写一篇新文章

```bash
npx hexo new "文章标题"          # 默认生成 source/_posts/文章标题.md
# 挪到写作年月文件夹，如 source/_posts/2026/10/文章标题.md → URL /2026/10/文章标题/
# 写内容，frontmatter 参考 scaffolds/post.md
npx hexo clean && npx hexo generate   # 本地验证，无报错再 push
git add -A && git commit -m "post: 文章标题" && git push
```

写完后可以 `npx hexo server` 本地预览（默认 http://localhost:4000）。

**在 Pad / Obsidian 上写（没有 node）**：frontmatter 模板在 `templates/post.md`，Obsidian 的 Templates 核心插件已开启并指向 `templates/`，插模板即可，不用手敲 YAML。`scaffolds/post.md` 只服务 `npx hexo new`。

## Frontmatter（anzhiyu 实际读取的字段）

```yaml
---
title: 文章标题              # 必填
date: 2026-10-23 20:30:24      # 真实落笔时刻，同日多篇各不相同
updated:                     # 留空则用 mtime（_config.yml updated_option: mtime）
description: 一句话摘要      # 首页卡片/SEO 用，index_post_content.method=2 时优先显示
cover: /img/xxx.jpg          # 封面；留空用 cover.default_cover（/img/default_cover.jpg）
top_img:                     # 文章页顶部大图；false 表示不要顶部图
categories:
  - 技术                    # 只能五选一：技术 / 笔记 / 架构 / 概念 / 实践
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

- `categories` 只能取 **技术 / 笔记 / 架构 / 概念 / 实践** 五选一（`_config.yml` 的 `category_map` 只映射这五个）。写五类以外的词不会报错，但会生成一个 `/categories/工程实践/` 这样的野分类页，既不在导航条里、也和映射后的英文路径分裂成两份。
- `date` 写**真实时刻** `YYYY-MM-DD HH:MM:SS`，不要只写日期、也不要写死 `12:00:00`：首页/归档/atom 全按 `date` 降序排，只写日期或写死 12:00 会让同一天多篇的顺序由文件遍历决定、不可预测。`tools/check-frontmatter.py` 会把「date 缺时间」和「同日同一秒」都判成 ERROR（URL 年月来自**文件夹**，不是 date）
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
- **时区不是坑（已实测，别再照旧说法改）**：`permalink: :title/`，URL 里的年月来自**文件所在文件夹**，不来自 `date`。用 `TZ=UTC`、`TZ=Asia/Shanghai`、以及删掉 `timezone` 三种方式构建，路径与页面显示日期完全一致。所以**不需要在 CI 里设 `TZ`**，也不需要为了 URL 去改日期。`date` 写真实时刻是为了同日排序稳定，与 URL 无关。
- **「更新于」靠 mtime，CI 里已还原（重要）**：`_config.yml` 是 `updated_option: mtime`，文章页「更新于」= 文件 mtime。CI 全新 clone 会把所有文件 mtime 变成 checkout 时刻，导致全站「更新于」都显示成构建时间。workflow 里已有 `Restore mtimes from git history` 步骤按每篇最后一次提交时间 `touch` 回来（配套 `fetch-depth: 0`，浅 clone 只能拿到同一个 tip 时间）。**不要删这两处，也不要改回浅 clone**，否则线上「更新于」会全部变成同一天。
- 仓库同时有 `package-lock.json` 和 `yarn.lock`，CI 走 `npm ci`。加依赖用 npm，别用 yarn
- 构建产物残留导致页面不更新：先 `npx hexo clean`
- 改了 `_config.anzhiyu.yml` 里的颜色值必须带双引号（`"#425AEF"`），否则 YAML 解析出错
- 主题配置里 `CDN.internal_provider: local`，不要再改成外部 CDN
- `.obsidian/` 在 `.gitignore` 里，**没有被跟踪**（`git ls-files .obsidian` 为空）。Pad 与桌面之间靠 Obsidian Sync 同步配置，不会产生 diff；但也意味着 Obsidian 侧改动（模板、插件设置）不进 git，换机器只能靠 Sync
- **首页分类卡片 404**：`_config.yml` 里有 `category_map`（技术→tech、笔记→notes、架构→architecture、概念→concepts、实践→practice），Hexo 生成的是对应的 `/categories/<英文>/`；`_config.anzhiyu.yml` 的 `home_top.category[].path` 如果写中文 `/categories/技术/` 就 404。**加/改分类时两处必须一起改**。分类共 5 类（内容类型维度），专栏（系列维度）承载在标签上（`专栏` 标记 + 系列名标签），不设为分类；判定标准见 `.pi/workflows/blog-write.js` 的「分类与标签标准」。验证办法：生成后遍历 `public/**/*.html` 的站内 `href`，逐个对 `public/` 落盘文件，一次就能抓出所有死链。

## 美化改动的边界

改外观时按这个顺序，越靠前越优先：

1. `_config.anzhiyu.yml` 的开关（`h2Divider`、`table_interlaced_discoloration`、`subtitle`、`cover`…）
2. `source/css/custom.css`（只用主题已有变量：`--anzhiyu-main`、`--anzhiyu-card-bg`、`--anzhiyu-fontcolor`、`--anzhiyu-secondbg`、`--anzhiyu-secondtext`、`--anzhiyu-border-radius`、`--anzhiyu-shadow-border`、`--anzhiyu-scrollbar`；深色模式用 `[data-theme='dark']`）
3. 改完必须 `npx hexo clean && npx hexo generate` 验证通过

关掉自定义 CSS：把 `inject.head` 里那行 `<link ... custom.css>` 注释掉即可，不需要删文件。

## 封面：logo 合成为主，Magpie 生图为辅（各自配色）

封面按文章主题分两条路：logo 合成沿用品牌色 / INK 与白底；**生图走贴合实际生活的自然配色**（木质、金属、织物、食物等真实颜色，不要全图蓝紫单色调），保持画面干净明亮。输出统一 900x675。流程与坑也写在 `.pi/workflows/blog-write.js` 的阶段 3。

**图片目录规则（2026-11 起）**
- 文章封面跟着文章走：`source/img/<年>/<月>/<key>.jpg`，frontmatter 的 `cover` 也写这个路径
- 站点级图片（默认封面、banner）在 `source/img/common/<key>.jpg`
- 两个封面脚本自动定位目录（按「哪篇文章引用了这张图」，见 `tools/imgpaths.py`），文章挪年月会自动跟上；文章还没写 frontmatter 时加 `--dir <目录>`
- 脚本**不会**改 frontmatter，生成后自己同步 `cover` 字段，别只改文件

**A. 框架/工具/库（有官方 logo）→ `tools/make-covers.py`（PIL 本地合成，不用生图 API）**
- 白底 + 官方 logo + 英文名 + 中文副标题 + 品牌色短线
- 清单在脚本里的 `COVERS` 字典，key 是封面文件名（不含路径）
- 单张：`python tools/make-covers.py --only cover-hono`；全部：`python tools/make-covers.py`
- 预览不覆盖：`python tools/make-covers.py --preview`（写到 `.tmp-img/`，已被 gitignore）
- 新增框架：从 `https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/<name>.svg` 取图标，栅格化成 1024 宽透明 PNG 放 `tools/logos/`，再加一条 `COVERS` 配置
- 配色：Express/Fastify/Prisma/Drizzle/Koa/Linux 用 INK（`#1F2D3D`）；Hono `#E36002`、NestJS `#E0234E`、Zod `#408AFF` 用品牌色；对比/横评类文章用 `logos=[...]` 多 logo 横排
- 版式参数在 `render()`：渲染 1280x960（输出压到 900 宽），logo 上限 560x300，多 logo 横排时每个 190x170、间距 56

**B. 没有 logo 的（算法笔记、AI 概念、项目拆解、默认封面）→ `tools/magpie-covers.py`（Magpie image MCP 生图）**
- **封面必须具体、可辨识（硬要求）**：画出实物/场景（机器、装置、工具、棋盘、手、具体道具），让读者一眼看出"在干什么"。**不要抽象图形**（节点+箭头、色块拼贴、散点网络、纯几何图案）。标杆是 `design-patterns-creational` 那张：机器 + 传送带 + 产物。`STYLE` 已经把这句锁进去了，但每条 prompt 的主题描述也要往"具体物件"上写
- **图内可以带短文字体现主题**：左上角一条短标签（`LABELS` 字典，英文单词或 2~4 个汉字，如 `CREATE`），底部小标题（`TEXTS`）。**所有文字都由脚本本地渲染，模型 prompt 仍写 `no text`**——本地叠字字形一定正确。标签只放 1 条、尽量短（≤ 12 个字符）
- prompt 模板 `STYLE` 已约定：贴近生活的自然配色（木质、金属、织物、食物等）、扁平矢量、整幅不裁切、无文字无水印 + 具体场景要求，只需在 `PROMPTS` 加每篇的主题描述
- **构图要主体突出、四周留背景边（2026-11 踩坑）**：prompt 里不要写 "small subject centered with huge empty space / wide margins on all sides" 这类话 —— 模型会照做，把主体缩成画面中心一个小点，四周全白。`STYLE` 已改成 "plain light background with a clear band of background color around the subject / subject centered and prominent with a balanced margin"，条目里也不要再带盖过 `STYLE` 的留白表述。反过来也不要写 "filling the frame"，会铺满贴边。留白指标要目测复核：脚本按「比 235 暗的像素外接框」算，暖色台面（桌面/码头/地面）本身偏暗会把外接框顶到边，报 0% 不一定是真贴边
- 底部小标题**由脚本本地合成**（`TEXTS` 字典，key 与 `PROMPTS` 一致，例如 `'cover-kmp': 'KMP 算法'`），不交给模型画 —— 混元画中文容易错字，本地叠字字形一定正确，字号/位置/蓝线也和 logo 封面一致。改标题只改 `TEXTS`
- 跑 `python tools/magpie-covers.py --only <slug>`，脚本自动调用 Magpie image MCP 生成、压到 900x675、落盘到文章的年/月目录并打印亮度/留白（指标在叠小标题**之前**量，不会被标题带偏）。默认模型在 `tools/magpie_mcp.py` 的 `DEFAULT_MODEL`，可用 `--model` 覆盖；不使用腾讯系模型。**通道可用性变化快（2026-11 实测）**：loomy/* 全部 406（账号无生图权限）、openrouter/* 全部 402（需余额 ≥ $1）、workbuddy-ai 与 workbuddy 两条混元通道可用但额度会耗尽（429 Credits exhausted）；报 429/402/406 时换 `--model` 试其它通道，别反复重试同一张
- 脚本自带硬指标，不合格必须改 prompt 只重跑该张（别整批重跑）：
  - 平均亮度 ≥ 150（画面干净明亮即可，不要求纯白底；低于报「底色偏暗」）
  - 主体突出、四周留可见背景边：不是中心一个小点（提示词写了 huge empty space），也不是铺满贴边（提示词写了 filling the frame）；留白 0% 先目测再定，暖色台面会顶满外接框
  - 无文字/字母/水印，无脏灰/泥泞底色，无 3D 写实
  - 对症改词：`clean bright background, no full-image blue or purple wash` / `zoomed out wide shot, entire composition fully visible, nothing cropped` / `flat vector illustration, no 3d, no photorealistic` / `no text, no letters, no numbers, no watermark`

## 常用工具

- `python tools/prepublish.py`：**发布前跑这一个就够**。它按顺序跑四步，任一失败即中止并返回 1：
  1. `check-frontmatter.py`（frontmatter 校验）
  2. 分类一致性（文章实际分类 ⊆ `_config.yml` 的 `category_map`；`_config.anzhiyu.yml` 的 `home_top` 卡片 `path: /categories/xxx/` 必须用映射后的英文名）
  3. `npx hexo clean && npx hexo generate`
  4. `check-links.py`（站内死链）

  `--fast` 只跑 1、2（改完 frontmatter 想快查时用），`-v` 透传详细输出。
  **改检查规则只改这个脚本**：`.pi/workflows/blog-write.js` 和 `blog-normalize.js` 的发布阶段都只调用它一行，不再各自维护一份清单。
- `python tools/check-frontmatter.py`：单独验 frontmatter，**已接入 CI**（在 `npm ci` 之前跑，快失败）。它挡的是「能构建但结果不对」那类错：
  - `date` 与文件所在 `<年>/<月>` 文件夹不一致（URL 在 11 月、归档却归到 1 月，首页排序沉底——hexo 不报错）
  - `date` 缺时间，或同一天两篇 `date` 完全相同（排序会不可预测）
  - `categories` 不是五类之一（会多出 `/categories/工程实践/` 这种野分类页）
  - 缺 `description` / `tags` / `cover`，或 `cover` 指向的文件不存在
  - 重复 slug / 重复 title、把分类名当标签用
  - `-v` 看警告（缺 `> ` 摘要块、tags 太多）
- `python tools/fill-date-times.py`：把缺时间的 `date` 补成**真实落盘时刻**（Windows 文件 CreationTime），同日同秒的会标出来等你定先后。先 `--dry-run` 看表格。已经全站跑过一次（40 篇）。
- `python tools/check-links.py`：构建后自查站内死链（扫 `public/**/*.html` 的 `href="/..."` 逐个对落盘文件），有死链返回 1，`-v` 列出引用页。**已接入 CI**，push 后死链会让部署失败；本地发布前跑一次能提前看到问题。
- `python tools/make-covers.py --preview`：预览封面不覆盖 `source/img`
- `tools/imgpaths.py`：封面目录推导（哪个脚本都不用改），它看的是「哪篇文章引用了这张图」

### SEO / 订阅产物

- `/sitemap.xml`：`hexo-generator-sitemap` 生成（配置在 `_config.yml` 的 `sitemap:`）。`rel: true` 会把 Sitemap 地址写进 robots.txt。
- `/robots.txt`：静态文件 `source/robots.txt`（只挡 `/page/` 翻页，别挡文章）。
- `/atom.xml`：`hexo-generator-feed` 生成，最近 20 篇。`_config.anzhiyu.yml` 的 `inject.head` 里有一行 `<link rel="alternate" type="application/atom+xml">` 供阅读器自动发现，**删了那行订阅器就发现不了 feed**。

## 改主题配置的坑（都是实际踩过的）

- **数组是按下标合并的**（Hexo 用 `hexo-util` 的 deepMerge，arrayMerge 保留 target 下标）：
  `home_top.category` 这类数组，你在 `_config.anzhiyu.yml` 写的条目数如果少于主题默认条数，剩下的 demo 项会残留。要全换就写满同样条数（3 条）。
- `peoplecanvas.enable: true` 会顶掉首页标题/副标题（渲染成粒子画布），而且它依赖一张外链图。想要标题就设 `false`。
- `wordcount.enable: true` 需要 `hexo-wordcount` 插件（已加入 `package.json`），否则构建报 `wordcount is not a function`。
- `avatar.effect: true` = 头像一直旋转。
- 作者卡 hover 时头像"下沉"其实是主题的 `#aside-content .card-info:hover .author-info-avatar { transform: scale(0) }` + `transform-origin: bottom`，已在 `custom.css` 改成头像始终可见（`opacity: 1; transform: none`）；副作用是那张绝对定位的简介（`.author-info__description`）会盖在头像上，所以同时让它 hover 保持 `opacity: 0`。
- **打赏**：`reward.enable: false` 只去掉文章页的按钮；中控台（`console.pug`）里的二维码是 `each item in theme.reward.QR_code` **无条件渲染**，而且数组按下标合并清不掉。已在 `custom.css` 用 `.console-card-group-reward { display: none }` 隐藏。
- **音乐**：两处开关 —— `aplayerInject.enable`（全局播放器资源）和 `nav_music.enable`（左下角播放器），都要关；只关一个会残留。
- **首页分类横栏 `#categoryBar`**：主题 `layout/index.pug` 里写死，没有配置开关。桌面端它和 hero 三张分类卡 + 顶部菜单「分类」完全重复，已在 `custom.css` 用 `@media (min-width: 769px) { #categoryBar { display: none } }` 隐藏；移动端保留（窄屏时它是 sticky 的分类入口）。想恢复就删这段 CSS。
- **文章目录（右侧 TOC）雾化**：主题 `sidebar.styl` 给非当前条目加了 `filter: blur(1px)` + `opacity: .6`，鼠标悬停整张卡才恢复。已在 `custom.css` 覆盖为 `filter: none; opacity: 1`（桌面侧栏与窄屏浮层同一套选择器，都生效）；现在只靠字号/颜色区分当前章节。
- 社交图标是 `social` 里的 `名称: 链接 || 图标类`，`mailto:` 链接能正常工作（`url_for` 对外部 scheme 原样返回），作者卡头像下方的图标也走同一份配置。
