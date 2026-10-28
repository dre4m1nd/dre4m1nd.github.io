---
title: Fastify 入门与进阶：从入门到可上线
date: 2026-10-29 12:45:00
description: Fastify 以 schema 驱动校验与序列化，async-first、钩子代替中间件、插件带作用域。这篇覆盖路由、JSON Schema 校验、生命周期钩子、错误处理、安全插件、inject 测试和优雅关闭，以及 v5 的破坏性变更。
categories:
  - 技术
tags:
  - Node.js
  - Fastify
  - 后端
cover: /img/cover-fastify.jpg
---

## Fastify 是什么

Fastify 是一个**以性能为第一目标**的 Node Web 框架：路由上声明 JSON Schema，它把校验和序列化编译成高度优化的函数，吞吐比 Express 高一大截。它的几个核心特征：

- **async-first**：处理函数直接 `async`，抛错自动进错误处理
- **Schema 驱动**：请求校验 + 响应序列化都用 JSON Schema
- **钩子（hook）**：用生命周期钩子代替 Express 风格的 `app.use` 中间件
- **插件 + 封装**：`register` 的插件自带作用域隔离，`decorate` 的东西不会污染全局

| | Express | Hono | Fastify |
| --- | --- | --- | --- |
| 请求对象 | `req` | `c.req` | `request` |
| 响应 | `res` / `res.json` | `c.json` | `reply.send` |
| 校验 | 自己写 / zod 中间件 | `@hono/zod-validator` | **内置 JSON Schema** |
| 错误处理 | `next(err)` | `throw` | `throw`（自动进 handler） |
| 中间件 | `app.use` | `await next()` | 钩子（v5 移除 `app.use`） |
| 跨运行时 | 仅 Node | 任意运行时 | 仅 Node |
| 亮点 | 生态大 | 小、Edge | 快、schema 序列化 |

Fastify 意思是"快"——适合对吞吐和类型/校验一致性有要求的 Node 服务。

## 入门

```bash
npm init -y
npm i fastify
```

### 最小服务

```js
const Fastify = require('fastify')

const app = Fastify({ logger: true })   // 开日志，生产可关

app.get('/', async (request, reply) => {
  return { hello: 'world' }             // 直接 return，Fastify 帮你序列化成 JSON
})

const start = async () => {
  try {
    await app.listen({ port: 3000, host: '0.0.0.0' })   // 容器里别漏 host
  } catch (err) {
    app.log.error(err)
    process.exit(1)
  }
}
start()
```

`host` 默认是 `127.0.0.1`，**容器/云上必须显式写 `0.0.0.0`**，否则外部访问不到。

### 路由与取请求

```js
app.post('/users/:id', async (request, reply) => {
  const { id } = request.params                 // 路径参数
  const { q } = request.query                    // 查询串，已解析成对象
  const body = request.body                       // 默认解析 application/json
  const token = request.headers['authorization']
  return { id, q, body, token }
})
```

要点：

- `request.body` 默认只解析 `application/json`，表单需要 `@fastify/formbody`
- `request.query` 里同名参数会合并成数组（如 `?t=1&t=2` → `['1','2']`）
- 处理函数里 `async` 抛错会**自动进错误处理器**，不用手动传

### 响应

```js
app.post('/users', async (request, reply) => {
  // 三种写法都行，但 reply.send 和 return 二选一，别都写
  return reply.code(201).send({ id: 1 })
})

app.get('/old', async (request, reply) => {
  return reply.redirect('/new')            // 默认 302
})

app.get('/dl', async (request, reply) => {
  reply.header('x-foo', 'bar')
  return reply.send('ok')
})
```

`reply.code()` / `reply.status()` 等价，`reply.send()` 触发序列化。

## 进阶 1：JSON Schema 校验与序列化

这是 Fastify 最值得用的特性。**v5 起必须写完整 JSON Schema**（带 `type`），旧版的速记语法已删除。

```js
const createUserSchema = {
  body: {
    type: 'object',
    required: ['name', 'email'],
    properties: {
      name: { type: 'string', maxLength: 20 },
      email: { type: 'string', format: 'email' },
      age: { type: 'integer', minimum: 0 },
    },
  },
  response: {
    200: {
      type: 'object',
      properties: { id: { type: 'string' } },
    },
  },
}

app.post('/users', { schema: createUserSchema }, async (request, reply) => {
  // request.body 已经是校验 + 类型转换后的对象，少了字段直接 400，根本进不了这里
  const { name, email, age } = request.body
  return { id: 'u_1', name, email, age }
})
```

- 校验失败 Fastify **自动返回 400**，错误信息里带字段详情；想自定义就在 `setErrorHandler` 里处理
- `response` schema 让 Fastify 用 `fast-json-stringify` 预编译序列化函数，这是它快的关键
- `format: 'email'` 需要额外装 `@fastify/ajv-formats` 并注册，否则校验时直接报错
- 想要 TS 类型跟 schema 联动，用 `@fastify/type-provider-typebox`（TypeBox）或 `@fastify/type-provider-zod`

## 进阶 2：生命周期钩子

Fastify 没有中间件栈，而是**生命周期钩子**：

```
onRequest → preValidation → preHandler → handler → preSerialization → onSend → onResponse
```

```js
// 全局钩子，每个请求都过
app.addHook('preHandler', async (request, reply) => {
  // 鉴权放这里最合适
})

// 只在某个子树加钩子：用 register 包一层
app.register(async (instance) => {
  instance.addHook('preHandler', async (request, reply) => {
    if (!request.headers['authorization']) {
      throw app.httpErrors.unauthorized('missing token')   // 见进阶 4
    }
  })
  instance.get('/admin', async () => ({ ok: true }))
})
```

- `onError` 钩子**只适合记日志**，不要在这里改响应（改了会抛异常）；改响应去 `setErrorHandler`
- 钩子可以用 `done` 回调或 `async`，官方推荐 `async`

## 进阶 3：插件与封装

Fastify 的插件是**封装（encapsulation）**的：`register` 进来的插件、在它里面 `decorate` 的东西，只在该插件及其子作用域可见。

```js
async function dbPlugin(fastify, opts) {
  fastify.decorate('db', createDb())        // fastify.db 现在可用
}

app.register(dbPlugin)
app.get('/users', async (request) => {
  return request.server.db.find()             // 同作用域内可用
})
```

如果希望 `decorate` 的东西**全局可见**（比如一个 logger、一个 client），用 `fastify-plugin` 包裹插件：

```js
const fp = require('fastify-plugin')
module.exports = fp(async function (fastify, opts) {
  fastify.decorate('cache', createCache())
})
```

不加 `fp` 包裹，`fastify-plugin` 的封装会让 `decorate` 只局限在插件内部。

## 进阶 4：统一错误处理

```js
app.setErrorHandler((error, request, reply) => {
  request.log.error(error)
  const status = error.statusCode ?? 500
  reply.code(status).send({
    code: error.code ?? 'INTERNAL_ERROR',
    message: status >= 500 ? '服务器开小差了' : error.message,
  })
})

app.setNotFoundHandler((request, reply) => {
  reply.code(404).send({ code: 'NOT_FOUND', message: `no route for ${request.url}` })
})
```

配合 `@fastify/sensible` 可以优雅地抛业务错误：

```js
await app.register(require('@fastify/sensible'))

app.get('/users/:id', async (request, reply) => {
  const user = await findUser(request.params.id)
  if (!user) throw app.httpErrors.notFound('user not found')   // 自动 404
  return user
})
```

`app.httpErrors` 提供 `badRequest / unauthorized / forbidden / notFound / ...`，都带正确状态码。

## 进阶 5：安全插件

```js
await app.register(require('@fastify/helmet'))            // 安全响应头（Hono 的 secureHeaders / Express 的 helmet）
await app.register(require('@fastify/cors'), {
  origin: ['https://dre4m1nd.github.io'],
  credentials: true,
})
await app.register(require('@fastify/rate-limit'), {
  max: 60,
  timeWindow: '1 minute',
})
await app.register(require('@fastify/jwt'), { secret: process.env.JWT_SECRET })
```

其余常用：`@fastify/static`（静态文件）、`@fastify/multipart`（文件上传）、`@fastify/websocket`（WebSocket）、`@fastify/cookie`（Cookie）。

⚠️ **v5 移除了 `app.use()`**：想用 Express 中间件要先 `await app.register(require('@fastify/middie'))` 再 `app.use(...)`。但官方建议直接用钩子替代中间件。

## 进阶 6：测试

Fastify 自带 `inject`，把请求打进内存，**不用起端口**：

```js
const { test } = require('node:test')
const assert = require('node:assert')

test('GET /health', async () => {
  const res = await app.inject({ method: 'GET', url: '/health' })
  assert.equal(res.statusCode, 200)
  assert.deepEqual(res.json(), { ok: true })
})
```

`res` 上有 `statusCode`、`json()`、`body`、`headers`——就是个伪造的响应对象，和真实请求行为一致。

## 进阶 7：优雅关闭

```js
const app = Fastify({ logger: true })

// ...register routes, plugins...

const shutdown = async (signal) => {
  app.log.info(`${signal} received, shutting down`)
  await app.close()        // 停监听 + 释放插件里的连接（数据库、缓存等）
  process.exit(0)
}

process.on('SIGTERM', () => shutdown('SIGTERM'))
process.on('SIGINT', () => shutdown('SIGINT'))

await app.listen({ port: 3000, host: '0.0.0.0' })
```

`app.close()` 是异步的（v4+），会等 `onClose` 钩子和插件清理逻辑跑完。

## Fastify vs Express vs Hono 怎么选

- **要极致吞吐 + 强校验一致性 + TS 友好**：Fastify。Schema 一把梭，少写一堆 if 校验。
- **已有 Express 生态（multer/passport/session）**：别硬换。
- **要跑 Cloudflare Workers / Deno / 边缘**：Hono（Fastify 只跑 Node）。

三者都能接同一个 Node 后端逻辑，只是壳不同。

## 常见坑清单

- **v5 的 schema 必须写完整 JSON Schema**（带 `type`），速记语法已删除
- **`app.use` 在 v5 不存在**，要用 `@fastify/middie` 或改钩子
- 字段只有写进 `required` 才会校验"是否存在"，只写 `properties` 不报错
- **`reply.send` 和 `return` 二选一**，都调用会抛 `FST_ERR_REPLY_SENT`
- async 抛错自动进 `setErrorHandler`，但**没设就走默认**（生产默认不泄露堆栈，挺好）
- `request.body` 默认只解析 JSON，表单要 `@fastify/formbody`
- `format: 'email'` / `date` 需要 `@fastify/ajv-formats`
- 插件里 `decorate` 的东西**只在子树可见**，跨作用域用 `fastify-plugin` 包
- 测试用 `inject` 别再 `listen`；`listen` 在容器里记得 `host: '0.0.0.0'`
- **v5 要求 Node 20+**，老项目先升 Node

## 参考

- [Fastify 官方文档](https://fastify.dev/)
- [Fastify v5 迁移指南](https://fastify.dev/docs/latest/Guides/Migration-Guide-V5/)
- [Validation and Serialization](https://fastify.dev/docs/latest/Reference/Validation-and-Serialization/)
- [@fastify/sensible](https://github.com/fastify/fastify-sensible)
