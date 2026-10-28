---
title: Koa 入门到进阶：从基础到可上线工程
date: 2026-10-29 13:00:00
description: 一篇讲透 Koa。从洋葱模型、@koa/router、ctx 读写、错误处理、zod 校验、安全中间件，到工程化实战——项目结构、统一响应、JWT 登录/刷新、koa-body 上传、流式返回、pino 日志、优雅关闭、supertest 测试与 pm2/Docker 部署，并与 Express/Fastify/Hono 横向对比。
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

`app.listen()` 底层是 `http.createServer(app.callback()).listen()`，和 Express 一样。

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
  const { name } = ctx.request.body     // 需要 koa-bodyparser（见进阶 2）
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
  // ctx.throw(400, 'bad request')          // 抛 http 错误（见进阶 1）
  await next()
})
```

`ctx` 是 `request` + `response` 的封装，常用快捷属性：`ctx.query`、`ctx.params`、`ctx.method`、`ctx.url`、`ctx.headers`、`ctx.body`、`ctx.status`、`ctx.set()`、`ctx.get()`。

### ctx.state：中间件间传值

不要在 `ctx` 上随便挂属性。Koa 约定用 **`ctx.state`** 作为中间件之间传递数据的命名空间：

```js
app.use(async (ctx, next) => {
  const user = await verify(ctx.get('authorization'))
  ctx.state.user = user          // 放进 state，而不是 ctx.user
  await next()
})
```

## 进阶

### 1. 错误处理

Koa **没有** Express 的 `next(err)`。机制是：默认错误处理器是一个包在最外层的 try-catch；要自定义响应，就自己写个**包在最前面**的 try-catch 中间件：

```js
// 必须放在所有中间件之前
app.use(async (ctx, next) => {
  try {
    await next()
  } catch (err) {
    const status = err.status || 500
    ctx.status = status
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
  if (!ctx.get('authorization')) ctx.throw(401, 'missing token')   // 抛 http-error
  ctx.assert(ctx.state.user, 403, 'forbidden')
  await next()
})
```

- `ctx.throw(status, msg)` 同 `throw httpError(status, msg)`
- `ctx.assert(cond, status, msg)` 条件不满足就抛
- `app.on('error')` 只用于**日志**，改响应要在 try-catch 里

### 2. 参数校验（zod）

`koa-bodyparser` 只解析不校验。Koa 没内置 schema（不像 Fastify），推荐用 **zod**（比 joi 更 TS 友好，错误信息也好解析，joi 同样可用）：

```bash
npm i zod
```

```js
const { z } = require('zod')

function validate(schema) {
  return async (ctx, next) => {
    const result = schema.safeParse(ctx.request.body)
    if (!result.success) {
      const msg = result.error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join('; ')
      ctx.throw(400, msg)               // 进 errorHandler 统一格式
    }
    ctx.state.validated = result.data    // 下游用校验后的数据
    await next()
  }
}

const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(6),
})
```

### 3. 安全中间件

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

### 4. 静态与模板

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

### 5. 测试

Koa 自己没有 `inject`，用 `supertest` 打 `app.callback()`：

```bash
npm i -D supertest
```

```js
const request = require('supertest')
const app = require('../app')

test('GET /users/1', async () => {
  const res = await request(app.callback()).get('/users/1')
  expect(res.status).toBe(200)
  expect(res.body).toEqual({ id: '1' })
})
```

## 工程化实战：把服务做成一个能上线的后端

上面是 API 基础，下面把它们拼成工程。

### 6. 项目结构与 app 工厂

```text
src/
├─ app.js            # 组装中间件、路由，导出工厂
├─ server.js         # 启动 http、优雅关闭
├─ config.js         # 读环境变量
├─ middlewares/
│  ├─ response.js    # 统一响应 & 错误处理
│  ├─ auth.js        # JWT 鉴权
│  └─ validate.js    # zod 校验
├─ routes/
│  ├─ auth.js
│  └─ users.js
├─ services/
│  └─ user.js       # 业务逻辑（可单测）
└─ db.js             # 数据存取（这里用内存桩）
```

核心用 **app 工厂**：不在模块顶层 `new Koa()` 就 `listen`，而是导出一个 `createApp()`，测试时每次拿一套干净实例。

```js
// src/app.js
const Koa = require('koa')
const bodyParser = require('koa-bodyparser')
const Router = require('@koa/router')
const { responseHandler, errorHandler } = require('./middlewares/response')
const authRouter = require('./routes/auth')
const userRouter = require('./routes/users')

function createApp() {
  const app = new Koa()
  app.use(errorHandler)        // ① 错误中间件永远第一个
  app.use(responseHandler)     // ② 统一响应包装
  app.use(bodyParser())

  app.use(authRouter.routes()).use(authRouter.allowedMethods())
  app.use(userRouter.routes()).use(userRouter.allowedMethods())
  return app
}
module.exports = { createApp }
```

### 7. 统一响应 & 错误处理中间件

业务里到处写 `{ code, data, message }` 很乱。用中间件统一格式：

```js
// src/middlewares/response.js
module.exports.responseHandler = async (ctx, next) => {
  ctx.ok = (data = null, message = 'ok') => {
    ctx.status = 200
    ctx.body = { code: 0, data, message }
  }
  ctx.fail = (code, message, status = 400) => {
    ctx.status = status
    ctx.body = { code, message }
  }
  await next()
}

// 错误中间件放最前，try/catch 住下游
module.exports.errorHandler = async (ctx, next) => {
  try {
    await next()
  } catch (err) {
    const status = err.status || 500
    ctx.status = status
    ctx.body = {
      code: err.code || status,
      message: err.expose ? err.message : '服务器开小差了',
    }
    ctx.app.emit('error', err, ctx)
  }
}
```

业务里直接 `ctx.ok(data)` / `ctx.fail(code, msg)`，不用每次拼 JSON。

### 8. 配置管理

```bash
npm i dotenv
```

```js
// src/config.js
require('dotenv').config()
module.exports = {
  PORT: process.env.PORT || 3000,
  JWT_SECRET: process.env.JWT_SECRET,
  NODE_ENV: process.env.NODE_ENV || 'development',
}
```

永远不要把密钥写死在代码里；部署时通过环境变量注入。

### 9. 路由分层与子路由 prefix

```js
// src/routes/users.js
const Router = require('@koa/router')
const { authMiddleware } = require('../middlewares/auth')

const router = new Router({ prefix: '/api/v1/users' })   // 统一前缀

router.get('/', authMiddleware, async (ctx) => {
  const list = await ctx.state.userService.list()
  ctx.ok(list)
})
module.exports = router
```

多个子模块各自 `new Router({ prefix })`，`app.js` 里统一 `use(routes()).use(allowedMethods())`。`prefix` 让版本和资源分组一眼清楚。

### 10. 鉴权实战：JWT 登录 / 刷新

```bash
npm i jsonwebtoken
```

```js
// src/routes/auth.js
const Router = require('@koa/router')
const jwt = require('jsonwebtoken')
const { validate, loginSchema } = require('../middlewares/validate')
const { config } = require('../config')
const userService = require('../services/user')

const router = new Router({ prefix: '/api/v1/auth' })

router.post('/login', validate(loginSchema), async (ctx) => {
  const { email, password } = ctx.state.validated
  const user = await userService.verify(email, password)
  if (!user) ctx.throw(401, '账号或密码错误')

  const access = jwt.sign({ uid: user.id }, config.JWT_SECRET, { expiresIn: '15m' })
  const refresh = jwt.sign({ uid: user.id }, config.JWT_SECRET, { expiresIn: '7d' })
  ctx.ok({ access, refresh })
})

router.post('/refresh', async (ctx) => {
  const { refresh } = ctx.request.body || {}
  try {
    const payload = jwt.verify(refresh, config.JWT_SECRET)
    const access = jwt.sign({ uid: payload.uid }, config.JWT_SECRET, { expiresIn: '15m' })
    ctx.ok({ access })
  } catch {
    ctx.throw(401, 'refresh token 无效或过期')
  }
})
module.exports = router
```

```js
// src/middlewares/auth.js
const jwt = require('jsonwebtoken')
const { config } = require('../config')

module.exports.authMiddleware = async (ctx, next) => {
  const header = ctx.get('Authorization') || ''
  const token = header.replace(/^Bearer\s+/i, '')
  if (!token) ctx.throw(401, '未登录')
  try {
    ctx.state.user = jwt.verify(token, config.JWT_SECRET)   // { uid }
  } catch {
    ctx.throw(401, 'token 无效或过期')
  }
  await next()
}
```

> 把 UserService 通过 `ctx.state.userService` 注入（在 app 工厂里 `app.use((ctx,next)=>{ctx.state.userService=userService;return next()})`），测试时能轻松换桩。

### 11. Session：什么时候用它

JWT 适合**无状态** API；要服务端"踢人下线"、存购物车这类有状态场景，用 `koa-session`：

```bash
npm i koa-session
```

```js
const session = require('koa-session')
app.keys = [config.JWT_SECRET]              // 签名用
app.use(session(app))

// 登录后
ctx.session.user = { id: user.id }
ctx.session.maxAge = 1000 * 60 * 60 * 24    // 1 天

// 退出
ctx.session = null
```

Session 默认存内存（单实例可用），多实例要配 `store`（Redis）。**别把敏感信息塞进 session**。

### 12. 文件上传：koa-body

`koa-bodyparser` **不支持** `multipart/form-data`，上传要用 `koa-body`（或 `@koa/multer`）：

```bash
npm i koa-body
```

```js
const { koaBody } = require('koa-body')
app.use(koaBody({
  multipart: true,
  formidable: {
    uploadDir: '/tmp/uploads',
    keepExtensions: true,
    maxFileSize: 20 * 1024 * 1024,   // 20MB
  },
}))

router.post('/avatar', authMiddleware, async (ctx) => {
  const file = ctx.request.files.avatar
  if (!file) ctx.throw(400, '没有文件')
  // file.filepath 是临时路径，file.originalFilename 是原名
  await fs.promises.copyFile(file.filepath, `./uploads/${file.originalFilename}`)
  ctx.ok({ url: `/uploads/${file.originalFilename}` })
})
```

### 13. 大文件：流式返回

别把文件读进内存再 `ctx.body = buffer`，直接用流：

```js
router.get('/files/:name', async (ctx) => {
  const path = `./uploads/${ctx.params.name}`
  ctx.type = 'image/png'
  ctx.body = fs.createReadStream(path)     // 自动按块输出，省内存
})
```

### 14. 日志：pino

```bash
npm i koa-pino-logger
```

```js
const logger = require('koa-pino-logger')()
app.use(logger)                       // 之后 ctx.log.info(...) 可用

app.on('error', (err, ctx) => {
  ctx.log.error({ err, url: ctx.url }, 'request failed')
})
```

开发环境想看彩色请求行，可用 `koa-logger`；生产用 `pino`（结构化、可对接 ELK/Loki）。

### 15. 优雅关闭

```js
// src/server.js
const { createApp } = require('./app')
const { config } = require('./config')

const app = createApp()
const server = app.listen(config.PORT, () => console.log('listening', config.PORT))

async function shutdown(sig) {
  console.log(`${sig} received`)
  server.close(() => process.exit(0))   // 停接收新请求
  setTimeout(() => process.exit(1), 10000).unref()   // 兜底
}
process.on('SIGTERM', () => shutdown('SIGTERM'))
process.on('SIGINT', () => shutdown('SIGINT'))
```

`server.close()` 会等已在处理的请求跑完再关，配合 K8s/pm2 的滚动发布最稳。

### 16. 测试进阶：应用工厂 + listen(0)

用 `createApp()` 而不是全局实例，每次测试都是干净环境：

```js
const request = require('supertest')
const { createApp } = require('../src/app')

let app, server
beforeAll((done) => {
  app = createApp()
  server = app.listen(0, done)          // 0 = 随机端口
})
afterAll((done) => server.close(done))

test('登录失败返回 401', async () => {
  const res = await request(server).post('/api/v1/auth/login')
    .send({ email: 'a@b.com', password: '123' })
  expect(res.status).toBe(401)
  expect(res.body.code).toBe(401)
})
```

要 mock 业务层就给 `ctx.state.userService` 换桩：在测试里 `app.use((ctx,next)=>{ctx.state.userService = fakeService; return next()})` 注册在路由前即可。

### 17. 部署

```bash
npm i -g pm2
pm2 start src/server.js -i max        # 按 CPU 核数起 cluster
```

Dockerfile 要点：

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY . .
ENV NODE_ENV=production
EXPOSE 3000
CMD ["node", "src/server.js"]
```

> Koa 是 Node-only，跑容器记得 `ENV PORT=3000` 并让 `server.js` 监听 `process.env.PORT`；多实例的 session / 限流状态要外置到 Redis。

## Koa vs Express/Fastify/Hono 怎么选

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
- `koa-bodyparser` 不支持 `multipart`，**文件上传用 `koa-body`**
- 中间件间传值用 **`ctx.state`**，别在 `ctx` 上乱挂属性
- 测试用 `app.callback()` + `supertest`，Koa 没有 `inject`
- 路由用 **`@koa/router`**，别再装已废弃的 `koa-router`
- `ctx.redirect` 与 `ctx.body` 冲突：重定向前不要先设 body
- `file` 上传字段在 `ctx.request.files`；`jwt.verify` 要 `try/catch`，抛错不自动进 errorHandler
- session 默认内存存储，**多实例必须换 Redis store**
- 大文件用 `createReadStream`，别 `readFileSync` 全文进内存
- 测试用 `app.listen(0)` + supertest，别直接 `app.listen(3000)` 抢端口
- 优雅关闭用 `server.close()`，不是 `process.exit()` 直接退

## 参考

- [Koa 官方文档](https://github.com/koajs/koa/blob/master/Readme.md)
- [Koa Error Handling](https://github.com/koajs/koa/blob/master/docs/error-handling.md)
- [@koa/router](https://github.com/koajs/router)
- [koa-helmet](https://github.com/venables/koa-helmet)
- [koa-body](https://github.com/koajs/koa-body)
- [koa-session](https://github.com/koajs/session)
- [koa-pino-logger](https://github.com/pinojs/koa-pino-logger)
- [jsonwebtoken](https://github.com/auth0/node-jsonwebtoken)
- [zod](https://zod.dev/)
