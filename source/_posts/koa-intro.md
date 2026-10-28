---
title: Koa 入门与进阶：从入门到可上线
date: 2026-10-29 13:00:00
description: Koa 是 Express 原班人马打造的最小化框架，核心只有洋葱模型中间件。这篇覆盖洋葱模型、@koa/router、ctx 读写、错误处理、校验、安全中间件、koa-static/koa-views 与 supertest 测试，并与 Express/Fastify/Hono 横向对比。
categories:
  - 技术
tags:
  - Node.js
  - Koa
  - 后端
cover: /img/cover-koa.jpg
---

## Koa 是什么

Koa 由 **Express 原班人马**打造，目标是更现代、更极简。它的核心只有大约 600 行：只提供中间件机制和 `Context`，**没有内置路由、没有 body 解析、没有静态文件、没有模板引擎**——这些都靠中间件自己拼。

Koa 最标志性的概念是**洋葱模型**中间件：每个中间件 `await next()` 之后会一路走到底再"回卷"上来，让跨切面逻辑（日志、鉴权、耗时）写起来非常干净。它是 Node 里最早原生拥抱 `async/await` 的框架。

| | Express | Koa | Fastify | Hono |
| --- | --- | --- | --- | --- |
| 内核 | 大而全 | **极简** | 中（带 schema） | 极简（Web 标准） |
| 中间件 | `next()` 回调 | `await next()` 洋葱 | 生命周期钩子 | `await next()` 洋葱 |
| 路由 | 内置 | `@koa/router` | 内置 | 内置 |
| 解析 body | `express.json()` | `koa-bodyparser` | 内置 | `c.req.json()` |
| 错误 | `next(err)` | `try/catch` + `app.on('error')` | `throw` | `throw` |
| 运行时 | Node | Node | Node | 任意 |

一句话：想要"自己搭积木、全掌控"，选 Koa；想要开箱即用，选 Express/Fastify。

## 入门

```bash
npm init -y
npm i koa @koa/router koa-bodyparser
```

### 最小服务

```js
const Koa = require('koa')

const app = new Koa()
app.use(async (ctx) => {
  ctx.body = 'Hello Koa'          // 设 body，Koa 自动序列化为响应
})
app.listen(3000, () => console.log('on :3000'))
```

注意 `app.listen()` 底层是 `http.createServer(app.callback()).listen()`，和 Express 一样。

### 洋葱中间件

```js
app.use(async (ctx, next) => {
  const start = Date.now()
  await next()                    // 进入下游，所有下游跑完才回到这里
  const ms = Date.now() - start
  ctx.set('X-Response-Time', `${ms}ms`)
})
```

- `await next()` **前**是"请求进入时"，**后**是"响应返回时"
- 忘了 `await next()` → 下游中间件不会执行，请求卡住
- 在 `next()` 之前就 `ctx.body = ...` 会提前结束、跳过下游（利用这点可做短路）

### 路由（@koa/router）

> ⚠️ 旧的 `koa-router` 已停止维护，官方用 **`@koa/router`**。

```js
const Router = require('@koa/router')
const router = new Router()

router.get('/users/:id', (ctx) => {
  ctx.body = { id: ctx.params.id }      // 路径参数
})
router.post('/users', (ctx) => {
  const { name } = ctx.request.body     // 需要 koa-bodyparser（见下）
  ctx.status = 201
  ctx.body = { id: 1, name }
})

// 注册：先 routes() 再 allowedMethods()
app.use(router.routes()).use(router.allowedMethods())
```

`allowedMethods()` 负责 `OPTIONS`，以及对不支持的方法返回 405、未实现返回 501；**漏掉它这些方法就处理不了**。

### 取请求 & 回响应

```js
app.use(async (ctx, next) => {
  const q = ctx.query                       // 查询串，已解析成对象
  const id = ctx.params?.id
  const body = ctx.request.body             // 需 koa-bodyparser
  const token = ctx.get('authorization')    // 读请求头

  ctx.status = 200
  ctx.set('X-Foo', 'bar')
  ctx.body = { q, id, body, token }
  // ctx.redirect('/login')                 // 重定向
  // ctx.throw(400, 'bad request')          // 抛 http 错误（见进阶 2）
  await next()
})
```

`ctx` 是 `request` + `response` 的封装，常用快捷属性：`ctx.query`、`ctx.params`、`ctx.method`、`ctx.url`、`ctx.headers`、`ctx.body`、`ctx.status`、`ctx.set()`、`ctx.get()`。

## 进阶 1：ctx.state 中间件间传值

不要在 `ctx` 上随便挂属性。Koa 约定用 **`ctx.state`** 作为中间件之间传递数据的命名空间：

```js
app.use(async (ctx, next) => {
  const user = await verify(ctx.get('authorization'))
  ctx.state.user = user          // 放进 state，而不是 ctx.user
  await next()
})

app.use(async (ctx) => {
  ctx.body = { hello: ctx.state.user.name }
})
```

## 进阶 2：错误处理

Koa **没有** Express 的 `next(err)`。它的机制是：默认错误处理器是一个包在最外层的 try-catch；要自定义响应，就自己写个**包在最前面**的 try-catch 中间件：

```js
// 必须放在所有中间件之前
app.use(async (ctx, next) => {
  try {
    await next()
  } catch (err) {
    ctx.status = err.status || 500
    // expose=true 表示可安全暴露给客户端（4xx 通常是），5xx 不泄露内部信息
    ctx.body = { message: err.expose ? err.message : '服务器开小差了' }
    ctx.app.emit('error', err, ctx)   // 仍交给 app.on('error') 记日志
  }
})

// 只记日志、不改响应的全局钩子
app.on('error', (err, ctx) => {
  console.error('server error', err, ctx.url)
})
```

业务里直接抛或用 `ctx.throw`：

```js
app.use(async (ctx, next) => {
  if (!ctx.get('authorization')) {
    ctx.throw(401, 'missing token')   // 抛一个 http-error（本质是 http-errors）
  }
  ctx.assert(ctx.state.user, 403, 'forbidden')
  await next()
})
```

- `ctx.throw(status, msg)` 同 `throw httpError(status, msg)`
- `ctx.assert(cond, status, msg)` 条件不满足就抛
- `app.on('error')` 只用于**日志**，改响应要在 try-catch 里

## 进阶 3：参数校验

Koa 没有内置 schema 校验（不像 Fastify）。常见做法：用 `joi` 在中间件里手动校验，结果放 `ctx.state`。

```bash
npm i joi
```

```js
const Joi = require('joi')
const schema = Joi.object({
  name: Joi.string().min(1).max(20).required(),
  email: Joi.string().email().required(),
  age: Joi.number().integer().min(0).optional(),
})

app.use(async (ctx, next) => {
  if (ctx.path === '/users' && ctx.method === 'POST') {
    const { error, value } = schema.validate(ctx.request.body, { abortEarly: false })
    if (error) ctx.throw(400, error.message)
    ctx.state.validated = value          // 下游用校验后的数据
  }
  await next()
})
```

也可直接用现成中间件（如 `koa-joi-validate`），但核心思路都是"校验中间件 + `ctx.state`"。

## 进阶 4：安全中间件

```bash
npm i koa-helmet @koa/cors koa-jwt koa-ratelimit
```

```js
const helmet = require('koa-helmet')
const cors = require('@koa/cors')
const jwt = require('koa-jwt')
const ratelimit = require('koa-ratelimit')

app.use(helmet())                                   // 安全响应头
app.use(cors({ origin: 'https://dre4m1nd.github.io' }))

// JWT：除了 /public 开头的都校验
app.use(jwt({ secret: process.env.JWT_SECRET }).unless({ path: [/^\/public/] }))

// 简单内存限流（生产换 redis 驱动）
const db = new Map()
app.use(ratelimit({ driver: 'memory', db, max: 60, duration: 60000 }))
```

`koa-jwt` 的 `.unless()` 跳过白名单路径；校验通过后会把 payload 挂到 `ctx.state.user`。

## 进阶 5：静态文件 & 模板

```bash
npm i koa-static koa-views ejs
```

```js
const serve = require('koa-static')
const views = require('koa-views')

app.use(serve(__dirname + '/public'))               // 静态资源
app.use(views(__dirname + '/views', { extension: 'ejs' }))

app.use(async (ctx) => {
  await ctx.render('index', { title: 'Koa' })        // 渲染模板
})
```

`koa-bodyparser` 别忘了，否则 `ctx.request.body` 是 `undefined`：

```js
const bodyParser = require('koa-bodyparser')
app.use(bodyParser())          // 默认解析 application/json 和 urlencoded
```

## 进阶 6：测试

Koa 自己没有 `inject`，用 `supertest` 打 `app.callback()`：

```bash
npm i -D supertest
```

```js
const request = require('supertest')
const app = require('../app')     // 导出 new Koa() 实例

test('GET /users/1', async () => {
  const res = await request(app.callback()).get('/users/1')
  expect(res.status).toBe(200)
  expect(res.body).toEqual({ id: '1' })
})
```

## Koa vs 其他三个怎么选

- **Koa**：想要极简核心 + 完全掌控中间件级联，习惯 `async/await`，喜欢自己拼积木
- **Express**：要的是生态（multer、passport、海量中间件）和"开箱即用"
- **Fastify**：要吞吐 + 内置 JSON Schema 校验/序列化，省去手写校验
- **Hono**：要跑 Cloudflare Workers / Deno 等边缘运行时

值得一提：`koa-compose`（Koa 的中间件组合器）后来启发了 Redux 等库，洋葱模型思想影响很广。

## 常见坑清单

- 中间件**漏 `await next()`** → 下游不执行、请求卡住
- 路由必须先 `.routes()` 再 `.allowedMethods()`，否则 OPTIONS/405 处理缺失
- **错误中间件要放第一个 `app.use`**，才能 try-catch 住后面所有逻辑
- Koa **没有 `next(err)`**：用 `ctx.throw()` / 直接 throw，在外层 catch
- `app.on('error')` **只记日志、不改响应**，改响应去 try-catch 里
- `ctx.request.body` 需要 `koa-bodyparser`，且默认只解析 json/urlencoded
- 中间件间传值用 **`ctx.state`**，别在 `ctx` 上乱挂属性
- 测试用 `app.callback()` + `supertest`，Koa 没有 `inject`
- 路由用 **`@koa/router`**，别再装已废弃的 `koa-router`
- `ctx.redirect` 与 `ctx.body` 冲突：重定向前不要先设 body
- Koa 核心很小：**router / body parser / static / helmet 都要自己装**

## 参考

- [Koa 官方文档](https://github.com/koajs/koa/blob/master/Readme.md)
- [Koa Error Handling](https://github.com/koajs/koa/blob/master/docs/error-handling.md)
- [@koa/router](https://github.com/koajs/router)
- [koa-helmet](https://github.com/venables/koa-helmet)
