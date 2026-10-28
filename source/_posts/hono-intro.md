---
title: Hono 教程：从入门到可上线
date: 2026-10-29 12:30:00
description: Hono 是跑在边缘运行时、基于 Web 标准的小框架。这篇覆盖路由、Context、中间件洋葱模型、zod 校验、错误处理、安全头、测试、类型安全 RPC 和多运行时部署。
categories:
  - 技术
tags:
  - Node.js
  - Hono
  - TypeScript
cover: /img/cover-hono.jpg
---

## Hono 是什么

Hono 是一个基于 **Web 标准（Request / Response）**的 Web 框架，同一份代码可以跑在：

- Cloudflare Workers / Deno / Bun
- Node.js（配 `@hono/node-server`）
- Vercel Edge Functions、Lagon、AWS Lambda 等

它不依赖 Node 的 `http` 模块，所以没有 `req` / `res` 这种全局可变对象，而是**每个请求一个 `Context`（`c`）**，处理函数返回一个 `Response`。

| | Express | Hono |
| --- | --- | --- |
| 底层 | Node `http` | Web 标准 `fetch` |
| 处理函数 | `(req, res, next)` | `(c)`，返回 `Response` |
| 取请求体 | `req.body`（同步） | `await c.req.json()`（异步） |
| 中间件放行 | `next()` | `await next()` |
| 运行环境 | 仅 Node | 任意 JS runtime |
| 体积 | ~几百 KB | ~14 KB |

Hono 的意思是"羽毛"（日语），卖点就是**小、快、到处能跑**。

## 入门

```bash
mkdir my-api && cd my-api
npm init -y
npm i hono
```

### 最小服务（Workers / Deno / Bun）

```ts
import { Hono } from 'hono'

const app = new Hono()
app.get('/', (c) => c.text('Hello Hono!'))

export default app
```

### 跑在 Node 上

```bash
npm i @hono/node-server
```

```ts
import { Hono } from 'hono'
import { serve } from '@hono/node-server'

const app = new Hono()
app.get('/', (c) => c.text('Hello Hono!'))

serve({
  fetch: app.fetch,      // 注意：不是 app.listen()
  port: 3000,
})
```

Hono 实例本身不 `listen`，它只暴露 `app.fetch`；监听交给运行时自己的适配器。

## 路由

```ts
app.get('/users/:id', (c) => {
  const id = c.req.param('id')        // 路径参数
  return c.json({ id })
})

app.post('/users', (c) => c.text('created', 201))
app.all('/hello', (c) => c.text('任意方法'))
app.on('PURGE', '/cache', (c) => c.text('purged'))   // 自定义方法

// 通配符
app.get('/assets/*', (c) => c.text('ok'))
```

两个要点：

- **通配符在 v4 里拿不到匹配到的值**（`c.req.param('*')` 还不支持，是 v5 的提案）。要拿只能用 `c.req.path` 自己截：`c.req.path.replace('/assets/', '')`
- 多个参数可以一次取：`const { id, commentId } = c.req.param()`

## Context 与响应

处理函数的返回值就是 `Response`，Hono 给了一批语法糖：

```ts
app.post('/users', (c) => {
  c.status(201)                       // 设置状态码
  c.header('X-Custom', 'value')       // 设置响应头
  return c.json({ ok: true })
})

app.get('/login', (c) => c.redirect('/oauth', 302))
app.get('/', (c) => c.html('<h1>hi</h1>'))
app.get('/notfound', (c) => c.notFound())          // 触发 app.notFound
```

拿请求：

```ts
app.get('/search', (c) => {
  const q = c.req.query('q')                       // 查询串
  const all = c.req.queries('tag')                 // 同名多次出现 → string[]
  return c.json({ q, all })
})

app.post('/users', async (c) => {
  const body = await c.req.json()                  // 注意是异步的
  const form = await c.req.formData()
  const auth = c.req.header('Authorization')
  return c.json(body)
})
```

**`await c.req.json()` 是最容易踩的坑**：Express 的 `req.body` 是同步的，换成 Hono 会不自觉漏掉 `await`，然后拿到一个 Promise。

## 进阶 1：中间件

Hono 的中间件是**洋葱模型**：`await next()` 之前是"进入"，之后是"返回"。

```ts
app.use('*', async (c, next) => {
  const start = Date.now()
  await next()                                  // 必须 await，否则直接返回空响应
  const ms = Date.now() - start
  c.res.headers.set('X-Response-Time', `${ms}ms`)   // next() 之后才能改响应
})
```

注意两点：

- **`await next()` 漏掉 await，请求会卡住**
- 要改响应（头/状态）只能在 `next()` 之后，而且用的是 `c.res`

中间件也可以直接返回 `Response` 提前结束：

```ts
const auth = async (c, next) => {
  const token = c.req.header('Authorization')?.replace('Bearer ', '')
  if (!token) return c.text('Unauthorized', 401)   // 直接返回，不往下走
  c.set('userId', await verify(token))
  await next()
}

app.use('/api/*', auth)
```

### 类型安全的 Context 变量

```ts
type Env = {
  Variables: { userId: string }
  Bindings: { DB: D1Database }        // Cloudflare 的绑定
}

const app = new Hono<Env>()

app.get('/me', (c) => {
  const userId = c.var.userId          // 有类型提示
  return c.json({ userId })
})
```

`c.set/get` 和 `c.var` 都可以用，后者带类型；这是 Hono 相比 Express 最大的体验优势。

## 进阶 2：路由分组与挂载

```ts
const users = new Hono()
users.get('/', (c) => c.json([]))              // GET /api/users
users.post('/', (c) => c.text('created', 201)) // POST /api/users
users.get('/:id', (c) => c.json({ id: c.req.param('id') }))

app.route('/api/users', users)                  // 挂载，自动继承类型
```

也可以给整个子应用加统一前缀：

```ts
const v1 = new Hono().basePath('/api/v1')
v1.get('/ping', (c) => c.text('pong'))          // → /api/v1/ping
app.route('/', v1)
```

## 进阶 3：参数校验

用官方生态的 `@hono/zod-validator`：

```bash
npm i @hono/zod-validator zod
```

```ts
import { zValidator } from '@hono/zod-validator'
import * as z from 'zod'

const schema = z.object({
  name: z.string().min(1).max(20),
  email: z.string().email(),
  age: z.number().int().min(0).optional(),
})

app.post('/users', zValidator('json', schema), (c) => {
  const data = c.req.valid('json')      // 已经是校验并转换后的数据
  return c.json(data, 201)
})
```

校验失败会自动返回 `400`，错误信息在 `c.req.valid('json')` 抛出的 `result.error` 里；想自定义格式可以用第二个参数 hook。支持的位置：`json`、`form`、`query`、`param`、`header`、`cookie`。

## 进阶 4：错误处理

```ts
import { HTTPException } from 'hono/http-exception'

app.onError((err, c) => {
  if (err instanceof HTTPException) {
    return err.getResponse()             // 由 HTTPException 自己决定状态码
  }
  console.error(err)
  return c.json({ error: 'Internal Server Error' }, 500)
})

app.notFound((c) => c.json({ error: `Not Found: ${c.req.path}` }, 404))
```

业务里直接抛：

```ts
app.get('/users/:id', async (c) => {
  const user = await db.find(c.req.param('id'))
  if (!user) throw new HTTPException(404, { message: 'user not found' })
  return c.json(user)
})
```

和 Express 的区别：**Express 用 `next(err)`，Hono 用 `throw`**（异步处理函数里也一样，不需要额外包装）。

## 进阶 5：安全

```ts
import { secureHeaders } from 'hono/secure-headers'   // Hono 的 helmet
import { cors } from 'hono/cors'
import { jwt } from 'hono/jwt'

app.use('*', secureHeaders())                        // 一堆安全响应头
app.use('/api/*', cors({ origin: ['https://example.com'] }))
app.use('/api/*', jwt({ secret: process.env.JWT_SECRET! }))
```

限流没有内置中间件，单机版可以自己写：

```ts
const hits = new Map<string, number[]>()

app.use('/api/*', async (c, next) => {
  const ip = c.req.header('x-forwarded-for') ?? 'unknown'
  const now = Date.now()
  const arr = (hits.get(ip) ?? []).filter((t) => now - t < 60_000)
  arr.push(now)
  hits.set(ip, arr)
  if (arr.length > 60) return c.text('Too Many Requests', 429)
  await next()
})
```

⚠️ 这个 `Map` 只在**单个实例**有效。Cloudflare Workers 要用 KV / Durable Object，Node 集群要用 Redis。

## 进阶 6：测试

Hono 实例可以直接"虚拟请求"，不需要监听端口：

```ts
import { Hono } from 'hono'

const app = new Hono()
app.get('/health', (c) => c.json({ ok: true }))

test('GET /health', async () => {
  const res = await app.request('/health')
  expect(res.status).toBe(200)
  expect(await res.json()).toEqual({ ok: true })
})
```

配合 vitest 或 `@hono/testing` 的 `testClient` 更好读：

```ts
import { testClient } from 'hono/testing'
import { app } from './app'

const client = testClient(app)
const res = await client.health.$get()
```

## 进阶 7：类型安全的 RPC

这是 Hono 的招牌能力：**服务端类型直接共享给客户端**，不用手写 API 文档。

```ts
// server.ts
import { Hono } from 'hono'

const app = new Hono()
  .get('/posts/:id', (c) => c.json({ id: c.req.param('id'), title: 'hello' }))
  .post('/posts', async (c) => {
    const body = await c.req.json()
    return c.json({ ok: true }, 201)
  })

export type AppType = typeof app        // 关键：导出类型，不要导出实例
export default app
```

```ts
// client.ts
import { hc } from 'hono/client'
import type { AppType } from './server'

const client = hc<AppType>('http://localhost:8787')

const res = await client.posts[':id'].$get({ param: { id: '1' })
const data = await res.json()          // data 的类型来自服务端返回值
```

路径、参数、请求体、响应体全都有类型，服务端改字段客户端立刻报错。

## 进阶 8：部署到不同运行时

| 运行时 | 写法 |
| --- | --- |
| Cloudflare Workers | `export default app`，`wrangler deploy` |
| Deno | `export default app`，`deno serve` |
| Bun | `export default app`，`bun run` |
| Node | `serve({ fetch: app.fetch, port })` |
| Vercel | `export default app` |

**环境变量在各运行时不一样**：Node 用 `process.env`，Workers 用 `c.env`（绑定），所以配置统一走 Hono 的 Env 类型更省心：

```ts
type Env = { Variables: { db: Database }; Bindings: { JWT_SECRET: string } }
const app = new Hono<Env>()
app.use('*', async (c, next) => {
  const secret = c.env.JWT_SECRET       // Workers 的绑定
  await next()
})
```

## Hono vs Express：什么时候用哪个

**选 Hono**：要部署到 Cloudflare Workers / Deno / Bun、在意冷启动和体积、想用 RPC 类型共享、团队用 TypeScript。

**选 Express**：依赖了大量 Node 生态中间件（`multer`、`passport`、`express-session` 这类）、项目已经在 Express 上跑得很好、需要长连接/WebSocket（Hono 本身不内置）。

两者可以共存：用 Hono 做边缘入口，Node 服务继续用 Express 接内部逻辑。

## 常见坑清单

- 中间件**漏 `await next()`** → 请求永远不返回
- 要改响应只能 `await next()` 之后操作 `c.res`，之前 `c.res` 还不存在
- `c.req.json()` 是**异步**的，别按 Express 的 `req.body` 习惯写
- 中间件提前结束是 `return c.text(...)`，**不是 `next(err)`**；错误用 `throw` + `app.onError`
- `cors()` / `secureHeaders()` / `jwt()` 必须挂在**路由之前**，否则不生效
- Node 下**不能 `app.listen`**，要 `serve({ fetch: app.fetch })`
- Workers 里**没有 `process.env`**，用 `c.env`
- 通配符 `/*` 在 v4 拿不到匹配值，要自己截 `c.req.path`
- 自写的限流/缓存 `Map` 只在单实例有效，多实例要上 Redis / Durable Object

## 参考

- [Hono 官方文档](https://hono.dev/)
- [Hono Routing](https://hono.dev/docs/api/routing)
- [Hono Middleware](https://hono.dev/docs/guides/middleware/)
- [@hono/zod-validator](https://github.com/honojs/middleware/tree/main/packages/zod-validator)
