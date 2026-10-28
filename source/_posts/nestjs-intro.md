---
title: NestJS 入门与进阶：从入门到可上线
date: 2026-10-29 13:30:00
description: NestJS 是 TS 优先、装饰器驱动、内置 DI 的全家桶框架，跑在 Express/Fastify 之上。这篇覆盖脚手架、模块/控制器/服务、DTO 全局校验、守卫、管道、拦截器、异常过滤器、中间件、测试与切 Fastify，并横向对比 Express/Koa/Fastify/Hono。
categories:
  - 技术
tags:
  - Node.js
  - NestJS
  - TypeScript
  - 后端
cover: /img/cover-nestjs.jpg
---

## NestJS 是什么

NestJS 是**受 Angular 启发的渐进式 Node 框架**：TypeScript 优先、用装饰器和**依赖注入（DI）**组织代码，内置模块化、路由、校验、守卫、拦截器、异常过滤。它不像 Koa 那样极简，而是给你一套**约定好的分层结构**，适合中大型、多人协作的项目。

关键点：Nest **不直接碰 HTTP 服务器**，而是走一个 HTTP Adapter。默认是 Express，也能一行切到 Fastify——**你的控制器、守卫、管道、过滤器代码一行都不用改**。

| | Express | Koa | Fastify | Hono | **NestJS** |
| --- | --- | --- | --- | --- | --- |
| 风格 | 裸框架 | 极简内核 | schema 驱动 | Web 标准/Edge | **全家桶 + 结构** |
| 语言 | JS | JS | JS | JS/TS | **TS 优先** |
| 路由 | 内置 | `@koa/router` | 内置 | 内置 | 装饰器 `@Get` |
| 校验 | 自己写 | 自己写 | 内置 JSON Schema | zod 中间件 | **class-validator / Zod** |
| 鉴权 | 中间件 | 中间件 | 钩子 | 中间件 | **Guard** |
| DI / 模块化 | 无 | 无 | 无 | 无 | **有** |
| 运行时 | Node | Node | Node | 任意 | Node |

一句话：想要"开箱即用的工程结构"选 Nest；想要"自己拼积木"选前面几个。

## 入门

```bash
npm i -g @nestjs/cli
nest new project        # 选 npm，自动生成目录
cd project && npm run start:dev   # 热重载，默认 :3000
```

### 引导与全局校验

```ts
// main.ts
import { NestFactory } from '@nestjs/core'
import { ValidationPipe } from '@nestjs/common'
import { AppModule } from './app.module'

async function bootstrap() {
  const app = await NestFactory.create(AppModule)
  app.useGlobalPipes(new ValidationPipe({ whitelist: true, transform: true }))
  await app.listen(3000)
}
bootstrap()
```

`whitelist` 会**剥掉 DTO 里没声明的字段**，`transform` 会把入参转换成 DTO 类型（比如把字符串 id 转 number）。

### 模块 / 控制器 / 服务

Nest 的"三件套"：

```ts
// app.module.ts
import { Module } from '@nestjs/common'
import { CatsController } from './cats/cats.controller'
import { CatsService } from './cats/cats.service'

@Module({
  controllers: [CatsController],   // 接收请求
  providers: [CatsService],        // 业务逻辑（可被注入）
})
export class AppModule {}
```

```ts
// cats/cats.service.ts
import { Injectable } from '@nestjs/common'
@Injectable()
export class CatsService {
  private cats: any[] = []
  findAll() { return this.cats }
  create(dto: any) { this.cats.push(dto); return dto }
}

// cats/cats.controller.ts
import { Controller, Get, Post, Param, Query, Body } from '@nestjs/common'
import { CatsService } from './cats/cats.service'

@Controller('cats')
export class CatsController {
  constructor(private readonly catsService: CatsService) {}   // 构造函数注入

  @Get()
  findAll(@Query('page') page: string) {
    return this.catsService.findAll()          // 返回值即响应体
  }

  @Get(':id')
  findOne(@Param('id') id: string) {
    return { id }
  }

  @Post()
  create(@Body() dto: CreateCatDto) {
    return this.catsService.create(dto)
  }
}
```

`@Controller('cats')` 就是前缀，方法装饰器 `Get/Post/Put/Delete/Patch` 决定 HTTP 方法，**返回的对象自动 JSON 序列化**。

### DTO 与全局校验

```ts
// cats/dto/create-cat.dto.ts
import { IsString, IsEmail, IsInt, Min } from 'class-validator'

export class CreateCatDto {
  @IsString() @Min(1) name: string
  @IsEmail() email: string
  @IsInt() @Min(0) age?: number
}
```

`ValidationPipe`（已在 main 注册）会在绑定 `@Body() dto: CreateCatDto` 时**自动校验**，失败直接返回 400，错误信息带字段。如果只写 `interface` 而不是 `class`，运行时拿不到类型元信息，**校验不会生效**——这是最常踩的坑。

## 进阶 1：守卫 Guard（鉴权）

```ts
import { Injectable, CanActivate, ExecutionContext } from '@nestjs/common'

@Injectable()
export class AuthGuard implements CanActivate {
  canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest()
    return !!request.headers.authorization   // 简化为"有 token 就放行"
  }
}
```

使用：

```ts
@Controller('cats')
@UseGuards(AuthGuard)                 // 整个控制器都要鉴权
export class CatsController {
  @Get()
  @UseGuards(AuthGuard)               // 或只加在某个路由
  findAll() { ... }
}
```

执行顺序是 **全局 → 控制器 → 路由**。要做全局守卫，推荐用 provider 方式而不是 `app.useGlobalGuards`（跨平台更一致）：

```ts
import { APP_GUARD } from '@nestjs/core'
@Module({ providers: [{ provide: APP_GUARD, useClass: AuthGuard }] })
export class AppModule {}
```

## 进阶 2：管道 Pipe（转换 + 校验）

内置了 `ParseIntPipe` / `ParseUUIDPipe` 等。自定义一个：

```ts
import { PipeTransform, Injectable, ArgumentMetadata, BadRequestException } from '@nestjs/common'

@Injectable()
export class ParseIntPipe implements PipeTransform {
  transform(value: any, _metadata: ArgumentMetadata) {
    const val = parseInt(value, 10)
    if (Number.isNaN(val)) throw new BadRequestException('必须是数字')
    return val
  }
}
```

```ts
@Get(':id')
get(@Param('id', ParseIntPipe) id: number) { ... }   // 进来就是 number
```

## 进阶 3：拦截器 Interceptor

```ts
import { Injectable, NestInterceptor, ExecutionContext, CallHandler } from '@nestjs/common'
import { Observable } from 'rxjs'
import { tap } from 'rxjs/operators'

@Injectable()
export class LoggingInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler): Observable<any> {
    const now = Date.now()
    return next.handle().pipe(tap(() => console.log(`耗时 ${Date.now() - now}ms`)))
  }
}
```

典型用途：统一日志、统一响应包装、缓存（`@UseInterceptors` 或 `APP_INTERCEPTOR`）。

## 进阶 4：异常过滤器 Exception Filter

```ts
import { ExceptionFilter, Catch, ArgumentsHost, HttpException, HttpStatus } from '@nestjs/common'
import { Response } from 'express'

@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  catch(exception: unknown, host: ArgumentsHost) {
    const res = host.switchToHttp().getResponse<Response>()
    const status = exception instanceof HttpException
      ? exception.getStatus()
      : HttpStatus.INTERNAL_SERVER_ERROR
    const message = exception instanceof HttpException ? exception.message : '服务器开小差了'
    res.status(status).json({ code: status, message })
  }
}
```

`host.switchToHttp().getResponse()` 拿到的类型依赖 adapter（Express 是 `Response`，Fastify 是 `reply`）。全局注册同样推荐 `APP_FILTER` provider。

## 进阶 5：中间件 Middleware

函数式中间件直接 `app.use` 即可；要按路由粒度挂载，用 `NestMiddleware` + `MiddlewareConsumer`：

```ts
// main.ts
app.use((req, res, next) => {
  console.log(req.method, req.url)
  next()
})
```

Nest 自己的中间件签名和 Express 一致，所以复用 Express 中间件没问题。

## 进阶 6：测试

Nest 的 DI 让单测很容易 mock：

```ts
import { Test } from '@nestjs/testing'
import { CatsController } from './cats.controller'
import { CatsService } from './cats.service'

const fake = { findAll: () => ['cat'] }
const moduleRef = await Test.createTestingModule({
  controllers: [CatsController],
  providers: [{ provide: CatsService, useValue: fake }],   // 用桩替换服务
}).compile()
const controller = moduleRef.get(CatsController)
```

端到端（e2e）用 `supertest` 打真实 HTTP：

```ts
import { Test } from '@nestjs/testing'
import { INestApplication } from '@nestjs/common'
import * as request from 'supertest'
import { AppModule } from '../src/app.module'

let app: INestApplication
beforeAll(async () => {
  const module = await Test.createTestingModule({ imports: [AppModule] }).compile()
  app = module.createNestApplication()
  await app.init()
})
it('GET /cats', () => request(app.getHttpServer()).get('/cats').expect(200))
```

## 进阶 7：切到 Fastify（性能）

```bash
npm i @nestjs/platform-fastify
```

```ts
import { FastifyAdapter, NestFastifyApplication } from '@nestjs/platform-fastify'

const app = await NestFactory.create<NestFastifyApplication>(
  AppModule,
  new FastifyAdapter(),
)
await app.listen(3000)
```

控制器、守卫、管道、过滤器**全部不变**，只是底层换了 Fastify——吞吐通常能上一个台阶。Nest 11 还新增了 `StandardSchemaValidationPipe`，可以直接用 **Zod** 等 Standard Schema 做校验，不必再写 `class-validator` 的 class DTO：

```ts
import { StandardSchemaValidationPipe } from '@nestjs/common'
app.useGlobalPipes(new StandardSchemaValidationPipe())
```

## Nest 什么时候选

- **选它**：中大型项目、TS 团队、需要清晰分层和 DI、要一套现成的校验/鉴权/异常体系、长期维护
- **别选它**：小脚本、想完全掌控中间件级联（Koa 更合适）、要跑 Cloudflare Workers / Deno 等边缘运行时（Hono）

## 常见坑清单

- 全局管道/守卫/过滤器最好用 **`APP_PIPE` / `APP_GUARD` / `APP_FILTER`** provider，跨平台行为一致
- `class-validator` 要自己装 `class-validator` + `class-transformer`（Nest 不自带）
- **DTO 必须是 `class`，不能是 `interface`**，否则运行时无类型元信息，校验失效
- 守卫/过滤器/拦截器里拿请求：`context.switchToHttp().getRequest()`（Fastify 下是 `getRequest`/`getResponse`）
- 用了 `@Res()` 直接操作响应，Nest 会认为"响应已处理"，**拦截器/管道会失效**，尽量 return
- provider 没放进 `@Module({ providers: [...] })` 会报 `Nest can't resolve dependencies`
- 循环依赖要用 `forwardRef(() => XxxModule)`
- 想切 Fastify 要装 `@nestjs/platform-fastify` 并传 `new FastifyAdapter()`
- e2e 测试用 `module.createNestApplication().init()` + `app.getHttpServer()` 喂给 supertest

## 参考

- [NestJS 官方文档](https://docs.nestjs.com/)
- [Validation](https://docs.nestjs.com/application/validation)
- [Guards](https://docs.nestjs.com/guards)
- [Exception Filters](https://docs.nestjs.com/exception-filters)
- [Performance (Fastify)](https://docs.nestjs.com/http/performance)
