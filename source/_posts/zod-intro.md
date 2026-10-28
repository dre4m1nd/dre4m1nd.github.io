---
title: Zod 入门与进阶：从入门到可上线
date: 2026-10-29 14:30:00
description: Zod 是 TypeScript 优先的运行时 schema 校验库。这篇覆盖 parse/safeParse、基础类型与约束、对象/数组/联合、类型推断、refine/superRefine/transform、错误定制、异步校验，以及和 Express/Koa/Hono/Fastify/NestJS 的集成与常见坑。
categories:
  - 技术
tags:
  - Node.js
  - TypeScript
  - Zod
  - 校验
cover: /img/cover-zod.jpg
---

## Zod 是什么

Zod 是一个 **TypeScript 优先的 schema 校验库**：你声明一份 schema，它既能**在运行时校验外部数据**（API 入参、表单、环境变量），又能**反推出 TypeScript 类型**。

记住一句话：**TypeScript 只在编译期保证类型，运行时（用户传进来的数据）它管不到**。Zod 补的就是这块——把"类型即契约"从编译期延伸到运行时。所以它是 Express / Koa / Hono / Fastify / NestJS 几乎每个后端笔记里都出现过的校验方案。

```bash
npm i zod
```

## 入门

### 1. 解析与捕获错误

```ts
import { z } from 'zod'

const stringSchema = z.string()
stringSchema.parse('hello')        // ✅ 返回 'hello'
// stringSchema.parse(12)          // ❌ 抛 ZodError

// 生产代码里更常用 safeParse：不抛错，返回结果对象
const result = stringSchema.safeParse(12)
if (!result.success) {
  console.log(result.error.issues)  // [{ path:[], message:'Expected string, received number', code:'invalid_type' }]
} else {
  console.log(result.data)          // 校验通过的值
}
```

- `parse` 失败**抛出 `ZodError`**
- `safeParse` 返回 `{ success: true, data }` 或 `{ success: false, error }`，**不抛错**
- 错误信息在 `error.issues`（数组，每项带 `path` / `message` / `code`）

### 2. 基础类型与约束

```ts
z.string().min(1).max(20).trim()         // 非空、去空格
// Zod 4 推荐顶层写法：z.email() / z.url() / z.uuid()
z.string().email()                       // 邮箱（v4 起方法形式已弃用，但仍可用）
z.string().url()
z.number().int().positive().min(0).max(150)
z.boolean()
z.enum(['admin', 'user'])                // 枚举
z.literal('v1')                          // 字面量（常用于判别联合）
z.date()
z.coerce.number()                        // 自动把 "12" 转成 12
```

常见约束：`.min / .max / .length / .regex / .startsWith / .optional / .nullable / .default`。

### 3. 对象

```ts
const userSchema = z.object({
  id: z.number().int(),
  name: z.string().min(1),
  email: z.string().email(),
  age: z.number().int().min(0).optional(),   // 可选
  role: z.enum(['admin', 'user']).default('user'),
})

userSchema.parse({ id: 1, name: 'A', email: 'a@b.com' })
// age 可省；role 不给就用 'user'
```

对象常用方法：

```ts
userSchema.partial()        // 所有字段变 optional（用于 PATCH）
userSchema.pick({ id: true, name: true })   // 只留字段
userSchema.omit({ role: true })              // 去掉字段
userSchema.extend({ token: z.string() })     // 追加字段
userSchema.strict()        // 出现多余字段直接报错（防未知 key）
```

### 4. 数组 / 记录 / 联合

```ts
z.array(z.string()).min(1)
z.record(z.string(), z.number())              // 任意 key 的对象
z.tuple([z.string(), z.number()])            // 定长元组
z.union([z.string(), z.number()])            // A 或 B

// 判别联合：比 union 更智能，按某个字段自动收窄类型
const result = z.discriminatedUnion('status', [
  z.object({ status: z.literal('ok'), data: z.string() }),
  z.object({ status: z.literal('err'), message: z.string() }),
])
```

### 5. 类型推断 & 强制转换

```ts
type User = z.infer<typeof userSchema>   // 由 schema 反推 TS 类型

// transform：校验通过后顺手转换（类型也会跟着变）
const upper = z.string().transform((s) => s.toUpperCase())
upper.parse('hi')   // => 'HI'，类型从 string 变 string（值被转换）

// 输入是字符串、输出是 number 的常见姿势
const idSchema = z.coerce.number().int().positive()
```

## 进阶

### 6. refine / superRefine（跨字段校验）

```ts
// 单字段
const pwd = z.string().refine((v) => /[A-Z]/.test(v), { message: '需含大写字母' })

// 跨字段：确认密码
const form = z.object({
  password: z.string().min(6),
  confirm: z.string(),
}).superRefine((val, ctx) => {
  if (val.password !== val.confirm) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['confirm'],
      message: '两次密码不一致',
    })
  }
})
```

`refine` 适合单值/单字段；`superRefine` 能访问整个对象、能 `addIssue` 多个错误（path 精确指到字段）。

### 7. 错误定制

```ts
const s = z.string({ required_error: '不能为空', invalid_type_error: '必须是字符串' })
  .min(3, { message: '至少 3 个字符' })

// 全局 error map（一次性统一文案）
const zh = z.setErrorMap((issue, ctx) => {
  if (issue.code === 'invalid_type') return { message: '类型不对' }
  return { message: ctx.defaultError }
})
```

### 8. 异步校验

```ts
// 比如校验用户名是否已被占用（要查库）
const uniqueUser = z.string().refine(async (name) => {
  return (await db.users.count({ where: { name } })) === 0
}, { message: '用户名已存在' })

const res = await uniqueUser.safeParseAsync('alice')   // 注意用 safeParseAsync
```

涉及异步（查库、远程）的 refine，校验时务必用 `safeParseAsync` / `parseAsync`。

### 9. 和框架集成

Zod 是"框架无关"的，哪个后端都能塞：

```ts
// Express：中间件
const validate = (schema) => (req, res, next) => {
  const r = schema.safeParse(req.body)
  if (!r.success) return res.status(400).json({ errors: r.error.issues })
  req.valid = r.data
  next()
}

// Koa：中间件（详见 Koa 实战篇）
const validate = (schema) => async (ctx, next) => {
  const r = schema.safeParse(ctx.request.body)
  if (!r.success) return ctx.throw(400, r.error.issues.map(i => i.message).join('; '))
  ctx.state.validated = r.data
  await next()
}

// Hono：@hono/zod-validator
// app.post('/users', zValidator('json', userSchema), (c) => c.json(c.req.valid('json')))

// Fastify：用 @fastify/type-provider-zod 把 schema 当类型与校验
// NestJS 11：StandardSchemaValidationPipe 直接吃 Zod
```

> 前面写的 [Koa](/2026/10/29/koa-intro/)、[Express](/2026/10/29/express-intro/)、[Hono](/2026/10/29/hono-intro/)、[Fastify](/2026/10/29/fastify-intro/)、[NestJS](/2026/10/29/nestjs-intro/) 笔记里都有 Zod 的具体用法，可以对照看。

### 10. 实战：环境变量校验

```ts
// src/env.ts
import { z } from 'zod'

const envSchema = z.object({
  DATABASE_URL: z.string().url(),
  PORT: z.coerce.number().default(3000),
  NODE_ENV: z.enum(['development', 'production']).default('development'),
})

export const env = envSchema.parse(process.env)   // 启动即校验，错了直接崩，早失败早修复
```

启动时把环境变量跑一遍 Zod，是性价比极高的"防呆"手段。

## 与 TypeScript 的关系

| | TypeScript | Zod |
| --- | --- | --- |
| 校验时机 | 编译期 | **运行时** |
| 校验对象 | 变量/函数签名 | **外部不可信数据** |
| 出错表现 | 编译报错 | 运行时抛/返回错误 |
| 类型来源 | 手写 / 推断 | **由 schema 反推（`z.infer`）** |

两者互补：TS 管你自己的代码，Zod 管进来的数据。理想状态是 **schema 写一次，类型自动来**（`z.infer`），不用重复声明。

## 常见坑清单

- **空字符串能过 `z.string()`**：要"非空"必须 `.min(1)`（或 `.length()`）
- `z.number()` **不自动转换** `"12"` → 用 `z.coerce.number()` 或 `z.string().transform(Number)`
- 应用代码用 **`safeParse`**，别裸用 `parse`（除非你在外层 catch）
- 错误信息读 **`error.issues`**（`error.errors` 在新版已弃用）
- 想拒绝多余字段要 `.strict()`，否则默认忽略未知 key
- `z.enum` 的参数是**值数组**，不是 `enum` 类型；判别联合需要 `z.literal` 当 discriminant
- `.optional()` 表示可 undefined；要"不给就用默认值"用 `.default()`
- `.transform` 会**改变输出类型**，下游拿到的是转换后的值
- Zod schema 是**不可变**的：`.extend/.pick/.partial` 返回新 schema，原 schema 不变
- 异步 refine 必须用 **`safeParseAsync`**，否则异步校验不会等
- **Zod 4 起 `z.string().email()` 等方法已弃用**，推荐顶层 `z.email()` / `z.url()`；方法形式暂可用但下个大版本会移除
- `parse` 抛的必须是 `ZodError`，用 `instanceof z.ZodError` 判断而不是看 message

## 参考

- [Zod 官方文档](https://zod.dev/)
- [Zod v4 变更说明](https://zod.dev/v4/changelog)
- [@hono/zod-validator](https://github.com/honojs/middleware/tree/main/packages/zod-validator)
- [zod 与 react-hook-form](https://react-hook-form.com/docs/resolvers)
