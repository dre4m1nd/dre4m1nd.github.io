---
title: Drizzle 入门与进阶：从入门到可上线
date: 2026-10-29 14:15:00
description: Drizzle 是类型安全的 SQL 查询构建器，零运行时、贴近原生 SQL，还能跑边缘。这篇覆盖 schema 定义、drizzle-kit 迁移/推、select/insert/update/delete、关系查询、join、事务、upsert、libsql 边缘用法，以及与 Prisma 的选型对比。
categories:
  - 技术
tags:
  - Node.js
  - Drizzle
  - ORM
  - 数据库
cover: /img/cover-drizzle.jpg
---

## Drizzle 是什么

Drizzle 不是传统 ORM，而是一个**类型安全的 SQL 查询构建器**：你用 `pgTable / sqliteTable` 定义表，它生成**贴合 SQL 语义**的查询 API（`db.select().from(t).where(eq(...))`）。它**几乎零运行时**（只是把你的链式调用拼成 SQL），所以既快又能跑在边缘（Workers / Deno / Bun，配 `libsql` 连 Turso）。

如果你习惯写 SQL、又想要 TS 类型保护，Drizzle 比 Prisma 更对味。

| | Drizzle | Prisma（对比用） |
| --- | --- | --- |
| 范式 | SQL 查询构建器 | schema-first ORM |
| 运行时 | 几乎零 | 有 Rust 查询引擎 |
| 写查询 | 像写 SQL | 用自己 DSL |
| 边缘 | **原生支持**（libsql/turso） | 需 Accelerate |
| 迁移 | `drizzle-kit generate/migrate` | `migrate dev` |
| SQL 掌控力 | 高 | 低（被抽象） |

## 入门

```bash
npm i drizzle-orm
npm i pg                 # PostgreSQL 驱动（sqlite 用 better-sqlite3，边缘用 @libsql/client）
npm i -D drizzle-kit     # 生成/执行迁移
```

### 1. 定义 schema

```ts
// src/db/schema.ts
import { pgTable, serial, text, varchar, timestamp, integer } from 'drizzle-orm/pg-core'
import { relations } from 'drizzle-orm'

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  email: varchar('email', { length: 255 }).notNull().unique(),
  name: text('name').notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
})

export const posts = pgTable('posts', {
  id: serial('id').primaryKey(),
  title: text('title').notNull(),
  ownerId: integer('owner_id').notNull(),
})

export const usersRelations = relations(users, ({ many }) => ({
  posts: many(posts),
}))
export const postsRelations = relations(posts, ({ one }) => ({
  owner: one(users, { fields: [posts.ownerId], references: [users.id] }),
}))
```

### 2. 连接数据库

```ts
// src/db/index.ts
import { drizzle } from 'drizzle-orm/node-postgres'
import { Pool } from 'pg'
import * as schema from './schema'

const pool = new Pool({ connectionString: process.env.DATABASE_URL })
export const db = drizzle(pool, { schema })
```

### 3. drizzle-kit 配置与迁移

```ts
// drizzle.config.ts
import { defineConfig } from 'drizzle-kit'

export default defineConfig({
  dialect: 'postgresql',
  schema: './src/db/schema.ts',
  out: './drizzle',
})
```

```bash
npx drizzle-kit generate    # 根据 schema 生成 SQL 迁移文件
npx drizzle-kit migrate     # 把 ./drizzle 里的迁移执行到数据库
# 想快速验证不想留 SQL 文件：
npx drizzle-kit push        # 直接把 schema 推到库（code-first，无迁移历史）
```

### 4. 基础 CRUD

```ts
import { eq } from 'drizzle-orm'
import { db } from './db'
import { users, posts } from './db/schema'

// 增（returning 拿回插入的行）
const [user] = await db.insert(users).values({ email: 'a@b.com', name: 'Alice' }).returning()

// 查
const one = await db.select().from(users).where(eq(users.id, 1))
const all = await db.select().from(users)

// 改
await db.update(users).set({ name: 'Bob' }).where(eq(users.id, 1))

// 删
await db.delete(users).where(eq(users.id, 1))
```

`where` 里用 `eq / ne / gt / gte / lt / lte / like / and / or / inArray / isNull`，复杂片段用 `sql` 模板。

## 进阶

### 5. 关系查询（Relational Queries）

不用手写 join，也能嵌套取关联数据：

```ts
// 取用户并带上它的帖子
const list = await db.query.users.findMany({
  with: { posts: true },
  limit: 10,
  offset: 0,
})

// 带条件
const u = await db.query.users.findFirst({
  where: eq(users.id, 1),
  with: { posts: { where: eq(posts.title, '第一篇') } },
})
```

### 6. 显式 join

```ts
import { eq, like, desc } from 'drizzle-orm'

const rows = await db
  .select({ userName: users.name, postTitle: posts.title })
  .from(users)
  .leftJoin(posts, eq(users.id, posts.ownerId))
  .where(like(users.email, '%@b.com'))
  .orderBy(desc(posts.id))
  .limit(20)
```

`select({ ... })` 里可以挑字段做投影，比 `SELECT *` 更省。

### 7. 过滤、分页、聚合

```ts
import { and, gte, sql } from 'drizzle-orm'

await db.select().from(users).where(
  and(eq(users.name, 'Alice'), gte(users.createdAt, new Date('2026-01-01'))),
)

// 聚合
const [{ count }] = await db.select({ count: sql<number>`count(*)` }).from(users)

// 游标式分页
await db.select().from(users).where(gte(users.id, 100)).limit(20)
```

### 8. 事务 & Upsert

```ts
// 事务（pg 驱动支持回调式）
await db.transaction(async (tx) => {
  const [u] = await tx.insert(users).values({ email, name }).returning()
  await tx.insert(posts).values({ title, ownerId: u.id })
})

// Upsert（冲突时更新）
await db.insert(posts)
  .values({ id: 1, title: '新标题', ownerId: 1 })
  .onConflictDoUpdate({ target: posts.id, set: { title: '新标题' } })
```

### 9. 跑在边缘（Workers / Deno / Turso）

```bash
npm i @libsql/client
```

```ts
// src/db/index.ts（边缘版）
import { drizzle } from 'drizzle-orm/libsql'
import { createClient } from '@libsql/client'

const client = createClient({
  url: process.env.TURSO_URL!,
  authToken: process.env.TURSO_TOKEN,
})
export const db = drizzle(client, { schema })
```

`schema.ts` 不变，**同样的查询代码**即可跑在 Cloudflare Workers 上——这是 Drizzle 相对 Prisma 的最大优势。

### 10. 和 Web 框架配合

```ts
import { db } from './db'

app.get('/users/:id', async (c) => {
  const [u] = await db.select().from(users).where(eq(users.id, Number(c.req.param('id'))))
  if (!u) return c.notFound()
  return c.json(u)
})
```

连接池由底层驱动（pg Pool / libsql client）管理；进程退出时记得 `pool.end()` / `client.close()`。

## Drizzle 选型建议

- **选它**：熟悉 SQL、要类型安全又不想被 ORM 抽象、在意运行时开销、**要跑边缘**、需要精细控制生成的 SQL
- **不选它**：完全不想碰 SQL、要 Prisma Studio 那种可视化、希望迁移/客户端尽量"无脑"开箱

## 常见坑清单

- `drizzle(pool, { schema })` 的 **第二个参数 schema 别忘了传**，否则 `db.query.*` 关系查询取不到
- `drizzle-kit` 的 `dialect` 必须和驱动匹配（`postgresql` / `mysql` / `sqlite`）
- `generate` 只生成 SQL 文件，**还要 `migrate` 才真正改库**；`push` 才直接改库但无历史
- 改了 schema 记得重新 `generate` + `migrate`，否则代码类型和库表对不上
- 更新/删除**一定要加 `where`**，否则会全表操作
- `insert().returning()` 返回的是**数组**，取单行用 `[row] = await ...`
- 关系查询（`db.query`）依赖 schema 里的 `relations`，没定义就取不到嵌套
- 复杂条件用 `sql\`...\`` 模板时，参数用 `${param}` 占位，别直接字符串拼接（防注入）
- 边缘场景要用 `@libsql/client` + `drizzle-orm/libsql`，不是 `node-postgres`
- 分页投影用 `select({...})` 挑字段，别默认 `select()` 全选大行

## 参考

- [Drizzle 官方文档](https://orm.drizzle.team/docs/overview)
- [Drizzle Quickstart](https://orm.drizzle.team/docs/quick-start)
- [Drizzle Kit](https://orm.drizzle.team/docs/drizzle-kit-overview)
- [Relational Queries](https://orm.drizzle.team/docs/rqb)
