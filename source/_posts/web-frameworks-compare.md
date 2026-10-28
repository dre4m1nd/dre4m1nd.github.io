---
title: 四个 Web 框架的优劣势对比（Node 后端怎么选）
date: 2026-10-29 13:45:00
description: Express、Koa、Fastify、Hono 四个 Node Web 框架的定位、优劣势与选型建议横向对比，并补充 NestJS 这个建立在它们之上的元框架。每节都链接到对应入门笔记。
categories:
  - 技术
tags:
  - Node.js
  - 后端
  - 框架对比
  - 选型
cover: /img/cover-compare.jpg
---

## 先给结论（太长不看）

| 你的场景 | 推荐 |
| --- | --- |
| 想最快跑起来、要现成中间件、新手友好 | **Express** |
| 想要极简内核、自己拼中间件、享受洋葱模型 | **Koa** |
| 高吞吐 API、要内置校验 + 序列化、在意性能 | **Fastify** |
| 要跑 Cloudflare Workers / Deno / 边缘、要类型安全 RPC | **Hono** |
| 中大型团队、TS、需要 DI 和清晰分层 | NestJS（建立在 Express/Fastify 之上） |

前面已经给每个框架写了入门笔记，这篇把它们放在一起横向比：

- [Express 入门与进阶](/2026/10/29/express-intro/)
- [Koa 入门与进阶](/2026/10/29/koa-intro/)
- [Fastify 入门与进阶](/2026/10/29/fastify-intro/)
- [Hono 教程](/2026/10/29/hono-intro/)
- [NestJS 入门与进阶](/2026/10/29/nestjs-intro/)

## 定位速览

| 维度 | Express | Koa | Fastify | Hono |
| --- | --- | --- | --- | --- |
| 一句话定位 | 事实标准、全家桶 | 极简内核、洋葱中间件 | 高性能、schema 驱动 | 边缘优先、Web 标准 |
| 内核大小 | 大（自带路由/解析） | **极小**（~600 行） | 中（带校验/序列化） | **极小**（~14KB） |
| 运行环境 | 仅 Node | 仅 Node | 仅 Node | **任意 JS runtime** |
| 请求处理 | `(req, res, next)` | `(ctx, next)` 洋葱 | `(request, reply)` 钩子 | `(c)` 返回 Response |
| 内置校验 | 无 | 无 | **JSON Schema** | 需中间件 |
| 错误处理 | `next(err)` | `try/catch` | `throw` | `throw` |
| 性能 | 最慢 | 中 | **最快之一** | **最快之一** |
| 生态成熟度 | **最成熟** | 成熟 | 成熟 | 较新 |
| TypeScript | 一般（靠 @types） | 一般 | 好 | **原生友好** |
| 学习曲线 | 低 | 低 | 中 | 低 |

下面逐个拆优劣势。

## Express —— 永远的"标准答案"

**优势**
- **生态最成熟**：`multer`、`passport`、`express-session`、海量中间件，几乎"想到就能搜到"
- 开箱即用：路由、JSON 解析、静态文件、模板引擎全内置
- 招人/协作成本低，文档和教程最多，是很多人的第一框架

**劣势**
- **性能在四者里最弱**（同步回调历史包袱，v5 才彻底 async）
- 没有内置校验/序列化，参数校验要自己写或接 zod 中间件
- 回调/中间件风格偏"自由"，大型项目容易写出意大利面条

**适合谁**：小到中型服务、内部系统、学习用途、需要某个冷门中间件时。

## Koa —— 极简主义者的洋葱

**优势**
- **核心极简**，只有中间件机制 + `ctx`，理解成本低、可控性高
- 洋葱模型让"请求进入/响应返回"两段逻辑写在一起，干净优雅
- 最早原生拥抱 `async/await`，代码可读性高
- 来自 Express 原班人马，理念有传承

**劣势**
- **太"裸"**：路由、body 解析、静态、helmet 全要自己装（`@koa/router`、`koa-bodyparser`…）
- 没有内置校验体系
- 生态比 Express 小，遇到特殊需求可能要自己造轮子
- `ctx` 上手要习惯 `await next()` 的顺序

**适合谁**：想要完全掌控中间件级联、喜欢轻量拼积木的开发者，以及做框架/中间件二次封装。

## Fastify —— 性能与类型一致性

**优势**
- **性能顶尖**：schema 同时驱动校验和序列化（`fast-json-stringify` 预编译），吞吐远高于 Express
- **内置 JSON Schema 校验**：省掉一堆手写 if，还能自动生成文档（配合 `@fastify/swagger`）
- 钩子 + 插件封装（encapsulation）机制清晰，自带 `inject` 测试
- 丰富的官方插件体系（`cors`/`jwt`/`rate-limit`/`static`/`multipart`）

**劣势**
- 生态比 Express 小，部分 Express 中间件不能直接用（v5 甚至移除了 `app.use`）
- **Schema 写法有一定心智负担**，类型联动要额外配 TypeBox/Zod provider
- 仅 Node，跑不了边缘
- v5 要求 Node 20+

**适合谁**：对吞吐敏感的后端 API、需要强校验一致性的服务、从 Express 升级性能的项目。

## Hono —— 边缘时代的轻骑兵

**优势**
- **跨运行时**：同一份代码跑 Workers / Deno / Bun / Node，冷启动极快
- 基于 Web 标准（`Request`/`Response`），未来-proof，SSR 也方便
- **极小**（~14KB）、API 简洁，`c.text/json/html` 语法糖好用
- 招牌的**类型安全 RPC**（`hc` + `AppType`），前后端共享类型
- 自带 `zValidator`、测试用 `app.request()` 无需起端口

**劣势**
- **生态最年轻**，复杂场景（长连接、重型中间件）不如 Express
- 通配符等能力在 v4 还有缺口（如 `/*` 拿不到匹配值）
- 团队招人/参考资料相对少
- Node 原生能力（如 `process.env`）在边缘运行时要换 `c.env`

**适合谁**：边缘函数、Cloudflare Workers、轻量 API/BFF、需要前后端共用类型的全栈场景。

## （补充）NestJS：不是同类，是"元框架"

前面四个是**底层 Web 框架**，NestJS 不一样——它是**建立在 Express 或 Fastify 之上的元框架**（默认 Express，可切 Fastify）。它的价值不在"多快"，而在**工程结构**：装饰器、`@Module`、依赖注入、`Guard`/`Pipe`/`Interceptor`/`Filter` 一整套约定。

- **优势**：TS 优先、分层清晰、DI、内置校验/鉴权/异常体系，最适合中大型团队和长期维护
- **劣势**：重、学习曲线陡、不跑边缘、性能取决于底层适配器
- 所以严格说它和上面四个**不是同一层**，选型时通常是"底层框架选谁"之后再决定"要不要套 Nest"

## 横向对比：性能与场景

```
性能（大致）：Fastify ≈ Hono  >  Koa  >  Express
           （均指 Node 运行时内的相对水平，Hono 还能跑边缘）
```

| 需求 | 第一选择 | 次选 |
| --- | --- | --- |
| 最快上手 / 最多资料 | Express | Koa |
| 最高吞吐 API | Fastify | — |
| 跑边缘 / 多运行时 | Hono | — |
| 最轻量、最可控 | Koa | Hono |
| 大型 TS 工程 | NestJS（底层 Fastify） | Fastify |
| 复用老 Express 中间件 | Express | NestJS |

## 怎么选：决策清单

1. **是不是要上 Cloudflare Workers / Deno / 边缘？**
   是 → Hono；否 → 往下
2. **是不是中大型、多人、要长期维护、强 TS？**
   是 → NestJS（底层用 Fastify）；否 → 往下
3. **吞吐是不是硬指标、要内置校验？**
   是 → Fastify；否 → 往下
4. **想不想完全掌控、喜欢自己拼中间件？**
   是 → Koa；否 → Express

绝大多数"普通 Node 服务"，**Express 和 Fastify 二选一**就够了：求稳求生态选 Express，求性能求规范选 Fastify。Koa 是"享受写中间件"的人用，Hono 是"要边缘"的人用。

## 常见误区

- **"Koa 是 Express 的升级版"**：不是。Koa 更底层、更极简，两者定位不同，Koa 不向后兼容 Express 中间件
- **"Fastify 只是更快的 Express"**：不止，它的 schema 校验/序列化范式和插件封装是另一套设计
- **"Hono 只能跑边缘"**：不是，Node 也能跑，只是它在边缘场景最有优势
- **"NestJS 比 Fastify 快"**：Nest 默认底层是 Express/Fastify，性能取决于适配器，它赢在结构不在速度
- **"新项目无脑上 Nest"**：小项目套 Nest 反而被结构拖累，先用轻框架更快

## 参考

- [Express 官方文档](https://expressjs.com/)
- [Koa 文档](https://github.com/koajs/koa)
- [Fastify 文档](https://fastify.dev/)
- [Hono 文档](https://hono.dev/)
- [NestJS 文档](https://docs.nestjs.com/)
