---
title: Prisma 入门与进阶：从入门到可上线
date: 2026-10-29 14:00:00
description: Prisma 是 schema-first、类型安全的 Node ORM，自带迁移工具和生成客户端。这篇覆盖初始化、schema.prisma 建模、迁移、CRUD 与关联、过滤分页、错误处理、事务、客户端扩展，以及与 Drizzle 的选型对比。
categories:
  - 技术
tags:
  - Node.js
  - Prisma
  - ORM
  - 数据库
cover: /img/cover-prisma.jpg
---

## Prisma 是什么

Prisma 是目前最主流的 Node **ORM**，特点是 **schema-first + 类型安全**：你在一个 `schema.prisma` 里定义数据模型，它帮你生成一套带完整 TS 类型的客户端 `PrismaClient`，并用迁移（migration）管理数据库表结构。

它支持 PostgreSQL、MySQL、SQLite、SQL Server、MongoDB。和后面要写的 Drizzle 最大的不同：**Prisma 有一个 Rust 写的查询引擎二进制**（query engine），查询会经它转换执行——换来了极致的类型安全和开发体验，但也带来体积与运行开销。

| | Prisma | Drizzle（对比用） |
| --- | --- | --- |
| 范式 | schema-first ORM | SQL 查询构建器 |
| 运行时 | 有 Rust 查询引擎 | 几乎零运行时 |
| 类型 | 全量、自动生成 | 由 schema 推导 |
| 迁移 | `migrate dev` 生成 SQL | `drizzle-kit generate` |
| 边缘运行时 | 不太适合（需 Accelerate） | **原生支持**（libsql/turso） |
| 上手 | 快 | 要懂 SQL |

## 入门

```bash
npm i prisma @prisma/client
npx prisma init --datasource-provider postgresql   # 也可 sqlite / mysql
```

这步会生成 `prisma/schema.prisma` 和 `.env`（含 `DATABASE_URL`）。

### 1. 定义模型

```prisma
// prisma/schema.prisma
generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model User {
  id        Int      @id @default(autoincrement())
  email     String   @unique
  name      String?
  createdAt DateTime @default(now())
  posts     Post[]
}

model Post {
  id        Int      @id @default(autoincrement())
  title     String
  ownerId   Int
  owner     User     @relation(fields: [ownerId], references: [id])
}
```

### 2. 生成迁移并同步

```bash
npx prisma migrate dev --name init    # 生成 SQL 迁移 + 执行 + 生成客户端
npx prisma generate                   # 只重新生成客户端（改了 schema 后）
```

快速验证不想写迁移文件时：`npx prisma db push` 直接把 schema 推到库（不保留迁移历史）。**生产环境建议用 migrate 保留历史**。

### 3. PrismaClient 单例

```ts
// src/db.ts
import { PrismaClient } from '@prisma/client'

const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient }
export const prisma =
  globalForPrisma.prisma ?? new PrismaClient({ log: ['warn', 'error'] })

if (process.env.NODE_ENV !== 'production') globalForPrisma.prisma = prisma
```

热重载时重复 `new PrismaClient()` 会耗尽连接，所以用 `globalThis` 做成单例。

### 4. CRUD

```ts
import { prisma } from './db'

// 增
const user = await prisma.user.create({
  data: { email: 'a@b.com', name: 'Alice' },
})

// 查（关联、排序、分页）
const list = await prisma.user.findMany({
  where: { name: { contains: 'Ali' } },
  include: { posts: true },          // 一并查出关联 posts
  orderBy: { createdAt: 'desc' },
  skip: 0,
  take: 10,
})

// 改 / 删
await prisma.user.update({ where: { id: user.id }, data: { name: 'Bob' } })
await prisma.user.delete({ where: { id: user.id } })
```

`include` 用来联表取出嵌套数据；只想取部分字段用 `select`。

## 进阶

### 5. 关联写入与查询

```ts
// 嵌套创建：建用户时顺带建两篇帖子
await prisma.user.create({
  data: {
    email: 'a@b.com',
    posts: { create: [{ title: '第一篇' }, { title: '第二篇' }] },
  },
})

// 关联已有数据：用 connect
await prisma.post.create({
  data: { title: '新帖', owner: { connect: { id: 1 } } },
})

// 用 findUnique 取单条 + 关联
const u = await prisma.user.findUnique({
  where: { id: 1 },
  include: { posts: { where: { title: { contains: '第' } }, take: 5 } },
})
```

### 6. 过滤、分页、聚合

```ts
import { Prisma } from '@prisma/client'

await prisma.user.findMany({
  where: {
    AND: [{ email: { endsWith: '@b.com' } }, { createdAt: { gte: new Date('2026-01-01') } }],
  },
})

// 聚合
const { _count } = await prisma.user.aggregate({ _count: { _all: true } })

// 游标分页（大数据集比 skip/take 更稳）
await prisma.user.findMany({ cursor: { id: 100 }, take: 20, skip: 1 })
```

### 7. 错误处理

```ts
import { Prisma } from '@prisma/client'

try {
  await prisma.user.create({ data: { email: 'dup@b.com' } })
} catch (e) {
  if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
    // 唯一约束冲突（email 重复）
    ctx.throw(409, '邮箱已存在')
  }
  if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2025') {
    // 记录不存在
    ctx.throw(404, '用户不存在')
  }
  throw e
}
```

常用错误码：`P2002` 唯一冲突、`P2025` 记录未找到、`P2003` 外键约束。

### 8. 事务

```ts
// 批量事务：要么全成要么全败
await prisma.$transaction([
  prisma.account.update({ where: { id: 1 }, data: { balance: { decrement: 100 } } }),
  prisma.transaction.create({ data: { accountId: 1, amount: -100 } }),
])

// 交互式事务：需要上一步结果
await prisma.$transaction(async (tx) => {
  const acc = await tx.account.findUnique({ where: { id: 1 } })
  if (!acc) throw new Error('no account')
  await tx.transaction.create({ data: { accountId: 1, amount: -100 } })
})
```

### 9. 客户端扩展 $extends

```ts
// 给查询出来的 user 加一个派生字段 fullName
const prisma = new PrismaClient().$extends({
  result: {
    user: {
      fullName: {
        needs: { firstName: true, lastName: true },
        compute: (u) => `${u.firstName} ${u.lastName}`,
      },
    },
  },
})
```

`$extends` 还能做只读副本路由、注入租户 ID、统一软删除等。v6 起**旧的 `$use` 中间件已不推荐**，请用 `$extends`。

### 10. 调试 & 可视化

```bash
npx prisma studio     # 浏览器里可视化增删改查，本地调试神器
```

想看执行的 SQL：把 `log: ['query', 'info', 'warn', 'error']` 传进 `PrismaClient`，或用 `$on('query', e => console.log(e.query))`。

### 11. 和 Web 框架配合

```ts
// 进程退出时断开，避免连接泄漏
process.on('SIGINT', async () => {
  await prisma.$disconnect()
  process.exit(0)
})
```

Express/Fastify/Koa 里都是 `import { prisma } from './db'` 直接用，注意中间件里**别每次请求 new 一个 client**。

## Prisma 选型建议

- **选它**：追求开发效率、要强类型、团队不想手写 SQL、需要可视化 studio、迁移工具开箱即用
- **不选它**：对运行时体积/延迟极敏感、要跑边缘（Workers）又不想加 Accelerate、查询走的是极复杂的原生 SQL

## 常见坑清单

- 改了 `schema.prisma` 后**必须重新 `prisma generate`**（否则类型/字段不更新）
- 热重载/Serverless 下要 **PrismaClient 单例**，否则连接数爆炸
- `migrate dev` 会丢数据（重置开发库）；**生产用 `migrate deploy`**
- `@relation` 的 `fields` 必须是一个真实字段，外键列要自己声明（如 `ownerId`）
- `include` / `select` 二选一，不能同时用
- 错误码用 `Prisma.PrismaClientKnownRequestError` 判断（`e.code`），别只 `catch` 后笼统处理
- 大数据分页优先**游标分页**，别用大 `skip`
- 边缘运行时原生跑 Prisma 有障碍，要么用 `pg` + 普通 SQL，要么上 Prisma Accelerate
- `$use` 中间件在新版已不推荐，改用 `$extends`
- `db push` 不保留迁移历史，**生产别拿它当迁移工具**

## 参考

- [Prisma 官方文档](https://www.prisma.io/docs/orm)
- [Prisma Client 参考](https://www.prisma.io/docs/orm/reference/prisma-client-reference)
- [Prisma Migrate](https://www.prisma.io/docs/orm/prisma-migrate)
