---
title: Express 入门与进阶：从 10 行服务到可上线的结构
date: 2026-10-29 12:00:00
description: 入门部分讲清路由、中间件、req/res；进阶部分补上分层结构、统一错误处理、参数校验、安全加固、优雅关闭、supertest 测试，以及 Express 4 升 5 的坑。
categories:
  - 技术
tags:
  - Node.js
  - Express
  - 后端
cover: /img/cover-express.jpg
---

## 入门：先跑起来

```bash
mkdir my-api && cd my-api
npm init -y
npm i express
```

```js
// app.js
const express = require('express');
const app = express();

app.get('/', (req, res) => {
  res.json({ hello: 'world' });
});

app.listen(3000, () => {
  console.log('http://localhost:3000');
});
```

`node app.js` 就能访问了。Express 5 要求 **Node 18+**。

{% note blue 'anzhiyufont anzhiyu-icon-circle-info' %}
本文用 CommonJS（`require`）。想用 ESM 就在 `package.json` 加 `"type": "module"`，把 `require` 换成 `import` 即可，其余写法一样。
{% endnote %}

## 路由：方法 + 路径 + 处理函数

```js
app.get('/users/:id', (req, res) => {
  const { id } = req.params;      // 路径参数 /users/42 → id = "42"
  const { verbose } = req.query;  // 查询串 ?verbose=1
  res.json({ id, verbose });
});

app.post('/users', (req, res) => {
  const { name } = req.body;      // 需要先挂 express.json()
  if (!name) return res.status(400).json({ error: 'name required' });
  res.status(201).json({ id: 1, name });
});
```

几个要点：

- `req.params` 一定是字符串，要数字自己 `Number(id)`
- `req.query` 的形状完全由用户控制，**不可信**，用之前先校验
- `req.body` 只有在挂了 body 解析中间件之后才有值（Express 5 里没有解析器时是 `undefined`，不是 `{}`）
- 处理函数返回 `res` 不影响 Express，用 `return res.status(...)` 只是为了提前结束函数、避免继续执行

## 中间件：Express 的全部

中间件就是 `(req, res, next) => {}`。请求进来后**按注册顺序**依次穿过中间件，谁调了 `next()` 谁就放行到下一个。

```js
// 全局：每个请求都走
app.use((req, res, next) => {
  req.startAt = Date.now();
  res.on('finish', () => {
    console.log(`${req.method} ${req.originalUrl} ${Date.now() - req.startAt}ms`);
  });
  next();                          // 忘了调 next() 请求就永远挂着
});

// 路由级：只挂在这条路由上
const auth = (req, res, next) => {
  if (req.get('Authorization') !== `Bearer ${process.env.TOKEN}`) {
    return next(new Error('unauthorized'));   // 交给错误中间件
  }
  next();
};

app.get('/admin', auth, (req, res) => res.send('ok'));
```

内置的三个最常用：

```js
app.use(express.json({ limit: '100kb' }));        // 解析 application/json
app.use(express.urlencoded({ extended: true }));  // 解析表单
app.use(express.static('public'));                // 静态文件，不用自己写
```

`express.json()` 和 `express.urlencoded()` 从 4.16 起就内置了，**不需要再装 body-parser**。

## 进阶 1：分层结构

能跑之后第一件事是把 `app.js` 拆开。一个够用的骨架：

```
src/
  app.js              # 创建 app、挂中间件、挂路由（不 listen）
  server.js           # listen + 优雅关闭
  config/env.js       # 环境变量解析与校验
  utils/AppError.js   # 自定义错误
  middleware/
    auth.js
    validate.js
    error.js          # 404 兜底 + 错误处理
  routes/users.js
  controllers/users.js
  services/users.js   # 业务逻辑 + 数据库
```

`app.js` 和 `server.js` 分离是为了**测试**：`supertest` 需要直接拿到 `app`，不能让它自己 `listen`。

```js
// routes/users.js
const { Router } = require('express');
const ctrl = require('../controllers/users');

const router = Router();
router.get('/', ctrl.list);
router.post('/', ctrl.create);

module.exports = router;

// app.js
app.use('/api/users', require('./routes/users'));
```

## 进阶 2：统一错误处理

这是 Express 项目里最容易写乱的地方。三件事：**自定义错误类**、**404 兜底**、**4 参数错误中间件**。

```js
// utils/AppError.js
class AppError extends Error {
  constructor(message, status = 400, code = 'BAD_REQUEST') {
    super(message);
    this.status = status;
    this.code = code;
  }
}
module.exports = AppError;
```

```js
// middleware/error.js
const AppError = require('../utils/AppError');

// 404 兜底：必须放在所有路由之后
const notFound = (req, res, next) => {
  next(new AppError(`no route for ${req.originalUrl}`, 404, 'NOT_FOUND'));
};

// 错误处理中间件：必须 4 个参数，必须放在最后
const errorHandler = (err, req, res, next) => {
  if (res.headersSent) return next(err);        // 响应已发出，交回 Express 默认处理
  const status = err.status || 500;
  if (status >= 500) console.error(err);        // 5xx 打日志，4xx 不打
  res.status(status).json({
    code: err.code || 'INTERNAL_ERROR',
    message: status >= 500 ? '服务器开小差了' : err.message,
  });
};

module.exports = { notFound, errorHandler };
```

```js
// app.js 里的顺序不能变
app.use('/api/users', userRouter);
app.use(notFound);          // ① 所有路由之后
app.use(errorHandler);      // ② 最后
```

**4 个参数缺一不可**：只写 `(err, req, res)` 时 Express 会把它当成普通中间件，永远不调用。

### async 处理函数的坑

Express 4 里 `async` 处理函数抛错 **不会**自动进错误中间件，会变成 unhandledRejection：

```js
// Express 4：这样写是错的，错误会静默丢失
app.get('/x', async (req, res) => {
  const data = await db.query();     // 抛错 → 请求挂死
  res.json(data);
});
```

要么手动包一层，要么升到 Express 5：

```js
// Express 4 的标准解法
const wrap = (fn) => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);

app.get('/x', wrap(async (req, res) => {
  res.json(await db.query());
}));
```

Express 5 已经原生支持：**返回的 Promise 被 reject 时会自动转发给错误中间件**，不用再 `wrap`。

## 进阶 3：参数校验

校验写在控制器里会散得到处都是，抽成中间件：

```js
const { z } = require('zod');
const AppError = require('../utils/AppError');

const validate = (schema, where = 'body') => (req, res, next) => {
  const result = schema.safeParse(req[where]);
  if (!result.success) {
    const first = result.error.issues[0];
    return next(new AppError(`${first.path.join('.')}: ${first.message}`, 422, 'VALIDATION_FAILED'));
  }
  req[where] = result.data;      // 用解析后的数据，多余字段被丢掉
  next();
};
```

```js
const createUserSchema = z.object({
  name: z.string().min(1).max(20),
  email: z.string().email(),
  age: z.number().int().min(0).optional(),
});

router.post('/', validate(createUserSchema), ctrl.create);
```

好处是**校验和业务解耦**，而且 `req.body` 之后拿到的就是干净数据。

## 进阶 4：安全加固

上生产前这四件基本都要挂：

```js
const helmet = require('helmet');
const cors = require('cors');
const rateLimit = require('express-rate-limit');

app.use(helmet());                                   // 一堆安全响应头
app.use(cors({                                       // 跨域白名单
  origin: ['https://dre4m1nd.github.io'],
  credentials: true,
}));
app.use(rateLimit({                                  // 限流：每 IP 每分钟 60 次
  windowMs: 60_000,
  limit: 60,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
}));
app.use(express.json({ limit: '100kb' }));           // 限制 body 大小，防打爆内存

// 在 nginx / 负载均衡后面时，必须让 Express 知道
app.set('trust proxy', 1);                           // 否则 req.ip 全是代理 IP，限流会误伤
```

- `helmet()` 默认会设 CSP，前端资源加载不出来时可以逐条关掉而不是整体禁用
- `cors` 只允许白名单 origin，别图省事写 `origin: '*'` 又开 `credentials: true`（浏览器会直接拒绝）
- `express-rate-limit` v7 的字段叫 `limit`，老版本叫 `max`

## 进阶 5：日志与配置

```js
// config/env.js —— 启动时校验环境变量，缺了就立刻退出
require('dotenv').config();
const { z } = require('zod');

const env = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  PORT: z.coerce.number().default(3000),
  DATABASE_URL: z.string().min(1),
  TOKEN: z.string().min(1),
}).parse(process.env);

module.exports = env;
```

```js
// 结构化日志，别用 console.log
const pinoHttp = require('pino-http');
app.use(pinoHttp({
  redact: ['req.headers.authorization', 'req.headers.cookie'],   // 别把密钥打进日志
}));
```

`config/env.js` 在启动时 `require` 一次，任何地方 `require('../config/env')` 拿到的都是校验过的值。

## 进阶 6：优雅关闭

`Ctrl+C` 时直接把进程杀掉，正在处理的请求会断，数据库连接池也不会释放。生产上要接信号：

```js
// server.js
const app = require('./app');
const env = require('./config/env');

const server = app.listen(env.PORT, () => {
  console.log(`listening on ${env.PORT}`);
});

const shutdown = (signal) => {
  console.log(`${signal} received, shutting down`);
  server.close(async () => {        // 停止接收新连接，等在途请求结束
    await db.close();               // 释放连接池
    process.exit(0);
  });
  setTimeout(() => process.exit(1), 10_000).unref();   // 兜底：10s 还没关完就强退
};

['SIGTERM', 'SIGINT'].forEach((sig) => process.on(sig, () => shutdown(sig)));
```

Kubernetes / Docker 停容器时发的就是 `SIGTERM`，不接这个信号会一直等到 `kill -9`。

## 进阶 7：测试

```bash
npm i -D jest supertest
```

```js
// test/health.test.js
const request = require('supertest');
const app = require('../src/app');

test('GET /health', async () => {
  const res = await request(app).get('/health').expect(200);
  expect(res.body.ok).toBe(true);
});
```

因为 `app.js` 不 `listen`，`supertest` 会自己在随机端口起服务，测完自动关，不用手动管理端口。

## Express 4 升 5 的差异

| 变化 | v4 | v5 |
| --- | --- | --- |
| 通配符路由 | `*`、`(.*)` | 必须命名：`/*splat` |
| 可选参数 | `/user/:id?` | `/user{/:id}` |
| `res.send(body, status)` | 支持 | 移除 → `res.status(s).send(b)` |
| `res.send(status)` | 支持 | 移除 → `res.sendStatus(s)` |
| `res.redirect('back')` | 支持 | 移除，用 `req.get('Referrer')` |
| `async` 处理函数抛错 | 手动 catch | 自动进错误中间件 |
| `req.query` | 普通对象 | getter，不可写 |
| 无解析器时的 `req.body` | `{}` | `undefined` |
| `app.del` | 有 | 移除，用 `app.delete` |
| Node 版本 | 0.10+ | 18+ |

## 常见坑清单

- **中间件顺序**：`express.json()` 必须在读 `req.body` 的路由之前；`notFound` 在所有路由之后；`errorHandler` 最后
- **错误中间件必须 4 个参数**，少一个就静默失效
- **`next()` 之后又 `res.send()`** → `ERR_HTTP_HEADERS_SENT`，`return` 一下能挡住大部分
- **Express 4 的 async 路由**抛错不进错误中间件，要么 `wrap` 要么升 5
- **CORS 预检被 404 拦掉**：`OPTIONS` 请求也要能过 `cors()`，别在它前面挂自定义鉴权
- **`app.use('*')` 在 v5 报错**，要么 `app.use((req, res) => ...)` 不写路径，要么 `/*splat`
- **`trust proxy` 没设**：`req.ip` 拿到的是代理 IP，限流、日志全错
- **生产用 `NODE_ENV=production`**：模板缓存、错误堆栈、`express.static` 的缓存策略都跟它有关
- **文件上传别用 `express.json()`**：用 `multer`，并且单独限制体积

## 参考

- [Express 官方文档](https://expressjs.com/)
- [Upgrade to Express v5](https://expressjs.com/en/guide/migrating-5/)
- [Express 5 发布说明](https://expressjs.com/en/blog/2024-10-15-v5-release/)
