---
title: Koa 实战进阶：从零搭一个能上线的后端
date: 2026-10-29 13:15:00
description: 上一篇讲了 Koa 的 API 基础，这一篇把它们拼成工程：统一响应与错误处理、zod 校验、JWT 登录/刷新与鉴权中间件、session、koa-body 文件上传、大文件流式返回、pino 日志、优雅关闭、supertest 应用工厂测试，以及 pm2/Docker 部署。
categories:
  - 技术
tags:
  - Node.js
  - Koa
  - 后端
  - 实战
cover: /img/cover-koa-2.jpg
---

## 这一篇讲什么

[上一篇](/2026/10/29/koa-intro/)把 Koa 的 `ctx`、中间件、路由、错误处理都过了一遍。这一篇把它们**拼成工程**：怎么组织目录、怎么统一响应、怎么做登录鉴权、怎么上传文件、怎么写可测的代码、怎么上线。

读完你手上会有一个**分层清晰、可测试、可部署**的 Koa REST API 骨架。

## 1. 项目结构与初始化

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

核心是 **app 工厂**：不在模块顶层 `new Koa()` 就 `listen`，而是导出一个 `createApp()`，测试时每次拿一套干净实例。

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

## 2. 统一响应与错误处理

业务里到处写 `{ code, data, message }` 很乱。用中间件统一格式：

```js
// src/middlewares/response.js
// 给 ctx 挂两个方法，业务里直接调
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
    ctx.app.emit('error', err, ctx)   // 交给 app.on('error') 记日志
  }
}
```

业务里：

```js
router.get('/me', (ctx) => {
  ctx.ok({ id: ctx.state.user.id })      // → { code:0, data:{...}, message:'ok' }
})
```

## 3. 配置管理

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

## 4. 路由分层与子路由

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

## 5. 请求校验用 zod

`koa-bodyparser` 只解析不校验，校验交给 **zod**（比 joi 更 TS 友好，错误信息也好解析）：

```bash
npm i zod
```

```js
// src/middlewares/validate.js
const { z } = require('zod')

function validate(schema) {
  return async (ctx, next) => {
    const result = schema.safeParse(ctx.request.body)
    if (!result.success) {
      const msg = result.error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join('; ')
      ctx.throw(400, msg)               // 进入 errorHandler 统一格式
    }
    ctx.state.validated = result.data    // 下游用校验后的数据
    await next()
  }
}

const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(6),
})

module.exports = { validate, loginSchema }
```

## 6. 鉴权实战：JWT 登录 / 刷新

```bash
npm i jsonwebtoken
```

```js
// src/routes/auth.js
const Router = require('@koa/router')
const jwt = require('jsonwebtoken')
const { validate, loginSchema } = require('../middlewares/validate')
const { config } = require('../config')      // 见各模块的依赖注入
const userService = require('../services/user')

const router = new Router({ prefix: '/api/v1/auth' })

router.post('/login', validate(loginSchema), async (ctx) => {
  const { email, password } = ctx.state.validated
  const user = await userService.verify(email, password)   // 校验账号密码
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

## 7. Session：什么时候用它

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

## 8. 文件上传：koa-body

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

## 9. 大文件：流式返回

别把文件读进内存再 `ctx.body = buffer`，直接用流：

```js
router.get('/files/:name', async (ctx) => {
  const path = `./uploads/${ctx.params.name}`
  ctx.type = 'image/png'
  ctx.body = fs.createReadStream(path)     // 自动按块输出，省内存
})
```

## 10. 日志：pino

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

## 11. 优雅关闭

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

## 12. 测试进阶：应用工厂 + supertest

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

## 13. 部署

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

## 与第一篇的衔接 & 常见坑

- **`app.use` 顺序是洋葱**：错误中间件第一、响应包装第二、bodyParser 第三、路由最后
- `koa-bodyparser` 解析的 `ctx.request.body`，**在 `validate` 之前必须已注册 bodyparser**
- zod 校验用的是 `ctx.request.body`，**文件上传接口别挂 bodyparser**，交给 `koa-body`
- `ctx.throw(code, msg)` 的 `msg` 才会出现在 `err.message`；`err.expose` 决定能否暴露给客户端
- JWT 验证失败要 `try/catch`，`jwt.verify` 抛错不会自动进 `errorHandler`
- session 默认内存存储，**多实例必须换 Redis store**
- 大文件用 `createReadStream`，别 `readFileSync` 全文进内存
- 测试用 `app.listen(0)` + supertest，别直接 `app.listen(3000)` 抢端口
- 优雅关闭用 `server.close()`，不是 `process.exit()` 直接退

## 参考

- [koa-body](https://github.com/koajs/koa-body)
- [koa-session](https://github.com/koajs/session)
- [koa-pino-logger](https://github.com/pinojs/koa-pino-logger)
- [jsonwebtoken](https://github.com/auth0/node-jsonwebtoken)
- [zod](https://zod.dev/)
