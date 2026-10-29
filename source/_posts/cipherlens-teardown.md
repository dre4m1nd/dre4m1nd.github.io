---
title: CipherLens 项目拆解：从架构到代码细节
date: 2026-10-29 15:30:00
description: 拆解密鉴 CipherLens（密码管理与安全评估平台）：Spring Boot 3.5 + MyBatis-Plus + MySQL + Redis 后端，Vue3 + Element Plus + Vite 前端，Docker Compose 一键部署。覆盖认证、密码信封加密、安全评分、AOP 日志、前端鉴权与构建，并给出工程上可再打磨的点。
categories:
  - 技术
tags:
  - 项目拆解
  - Java
  - Vue
  - Spring Boot
  - 安全
cover: /img/cover-cipherlens.jpg
---

## 项目概览

**密鉴 CipherLens** 是一个密码管理与安全评估平台：用户存密码条目，平台用 AES-256-GCM 加密存储，并提供一套密码强度评分与弱口令字典检测。典型"全栈小项目"结构——前后端分离、各自构建、通过 HTTP 接口通信。

> 源码在本地 `D:\dev-environment\code\cipherlens`，下面是按代码实际读出来的拆解（不是看名字猜的）。

## 技术栈总表

| 层 | 选型 |
| --- | --- |
| 前端 | Vue 3.2 + Vite 2 + Element Plus 2.3 + Vuex 4 + Vue Router 4 + WindiCSS + ECharts 5 + axios 0.26 |
| 后端 | Spring Boot 3.5.7（Java 21）+ MyBatis-Plus 3.5.14 + Knife4j 4.6 + Hutool + fastjson2 |
| 存储 | MySQL 8（utf8mb4）+ Redis 7（Token / 哈希） |
| 基础设施 | Docker Compose + 多阶段 Dockerfile + Nginx（托管 dist 并反代） |
| 安全 | PBKDF2WithHmacSHA256、AES-256-GCM、RSA-4096 信封加密、HMAC-SHA256 Token |

## 架构与部署

前后端解耦，靠"接口前缀"对齐：

- 前端请求统一走 `/api`（`baseURL = '/api'`）；
- 开发环境由 **Vite 代理**把 `/api/user/login` 转发到 `http://localhost:8080/user/login` 并去掉前缀；
- 生产环境由 **Nginx** 做同样的事（`location /api/ { proxy_pass http://backend:8080/; }`）；
- 后端**没有 context-path**，所以加/去 `/api` 全在网关侧完成；
- 前端用 **hash 路由**（`createWebHashHistory`），Nginx 再加 `try_files $uri /index.html` 兜底刷新白屏。

```nginx
location /api/ { proxy_pass http://backend:8080/; }   # 去前缀反代
location /    { try_files $uri $uri/ /index.html; }     # SPA 兜底
```

`docker-compose` 编排 MySQL + Redis + 后端 + 前端四个容器；后端暴露 `/actuator/health` 给 Docker 健康检查，前端 `depends_on backend healthy` 避免启动期 502。

## 后端拆解

### 分层结构

标准的"瘦 Controller + Service + Mapper"：

```
controller/      SysUserController / PasswordItemController / EvaluateController / OperationLogController
service/impl/    *ServiceImpl（继承 MyBatis-Plus 的 ServiceImpl）
mapper/          *Mapper（extends BaseMapper<T>）+ resources/mapper/*.xml
model/           entity（表）/ dto（入参）/ vo（出参）
common/          crypto（AES/RSA/PBKDF2）、util（Token/UserHolder/评估）
config/          MybatisPlusConfig / RedisConfiguration / WebConfig
interceptor/     LoginInterceptor（鉴权）
aop/             OperationLogAspect（操作日志）
exception/       BusinessException / SystemException / UnAuthorizedException
handler/         GlobalExceptionHandler / MPAutoFillHandler
```

### 认证与鉴权：自定义 Redis Token

`SysUserController.login` 返回的不是 JWT，而是**自定义 Token**：

```java
// RedisTokenUtil.buildToken：Base64(userId, HMAC_SHA256(salt + userId, secretKey))
String token = redisTokenUtil.buildToken(sysUser.getId());
redisTokenUtil.saveToken(token, userDTO);   // 存到 Redis Hash，带 TTL
```

鉴权由 `LoginInterceptor` 做：取请求头 `token` → `isValidToken`（验签名 + 查 Redis 是否存在/过期）→ 把 `userId` 塞进 `UserHolderUtil`（**ThreadLocal**）→ 业务里随时取。登出直接删 Redis 里的 key。

{% note info %}
和 JWT 对比：这是**有状态** Token（Redis 兜底），好处是能主动踢人（删 key 即下线）、能直接把用户信息塞进 Hash 省去每次查库；代价是 Redis 挂了全站登不了，且每台实例都要连同一 Redis。
{% endnote %}

### 密码安全：信封加密 + 评分

这是项目最核心、也最"安全向"的设计，分三层：

1. **登录密码**：用户登录密码用 `PBKDF2Util`（PBKDF2WithHmacSHA256，65536 次迭代，盐值随机）哈希后存 `sys_user.user_password_hash`，验证用**常量时间比较**防时序攻击。
2. **密码条目**：每条密码用 `AES256GCMUtil`（AES-256-GCM，12 字节随机 IV，认证标签防篡改）加密后存 `password_item.password`。
3. **密钥信封**：每个用户有一把 AES-256 密钥，用 **RSA-4096 公钥**加密后存在 `sys_user.aes_key_rsa_encrypted`（OAEP_SHA256，兼容华为云 KMS）。

`SecurityEvaluationUtil` 做强度评分（0–100）：基础 30 分，长度/字符类型加分，弱口令/过短/连续字符/重复字符扣分，并给出针对性优化建议（弱口令靠 `weak_password` 字典表 + `WeakPasswordService` 判定）。

### ORM：MyBatis-Plus

- Mapper 直接 `extends BaseMapper<T>`，白送 CRUD；
- `MybatisPlusConfig` 注册**分页插件** `PaginationInnerInterceptor(MYSQL)`；
- 全局 `map-underscore-to-camel-case: true`；
- `MPAutoFillHandler` 自动填充 `create_time` / `update_time`（`metaobject` 填充）；
- 复杂查询仍写 XML（`resources/mapper/*.xml` + `resultMap`）。

### 统一结果与异常

`Result<T>` 是统一响应体，`GlobalExceptionHandler` 把 `BusinessException / UnAuthorizedException / SystemException` 翻译成统一格式；前端 `request.js` 里 `res.code === 200` 才放行，否则弹 `ElMessage`，401/403 自动清 token 跳登录。

### 操作日志 AOP

`@OperationLogRecord(operationType, operationContent)` 标在方法上，`OperationLogAspect` 用 `@Around` 织入：进入时取 `UserHolderUtil` 的 userId，执行后算耗时、记结果，最后落 `operation_log` 表。

### 配置与多环境

`application.yml`（dev 默认）+ `application-prod.yml`（从环境变量注入 MySQL/Redis/Token 密钥/华为云 AK-SK，`SPRING_PROFILES_ACTIVE=prod` 切换）；`/actuator/health` 只暴露 health、不暴露详情；接口文档（Knife4j/Swagger）默认关，设 `API_DOCS_ENABLED=true` 才开。

## 前端拆解

### 技术栈与目录

Vue3 + Element Plus 的后台模板风格（带 layout / tabs / 菜单 / 主题切换）。目录：

```
layout/    Header（面包屑/全屏/主题）、Menu、Tabs、Logo
router/    modules/*（按业务拆路由）、permission（路由守卫 + 动态路由）、createNode
store/     app / keepAlive / user（Vuex），plugins/persistent 本地持久化
directive/ clickOutside / copy / debounce / drag / longpress / waterMarker
views/     dashboard（ECharts 图表）、password（增删改查+评估）、log、system（登录/注册/找回密码）
api/       user / passwordItem / log / operationLog（axios 封装）
```

### 请求层

`utils/system/request.js` 是 axios 实例（`/api` 前缀、5s 超时）：
- 请求拦截器把 `store.state.user.token` 放进 `token` 头（顺带也放 `Authorization: Bearer`，后端实际只认 `token` 头）；
- 响应拦截器统一处理 `code !== 200` 和 HTTP 错误，401/403 清本地数据跳登录。

### 鉴权与路由守卫

`router.beforeEach`：有 token 放行（已登录访问 `/login` 直接跳首页），无 token 且不在白名单（`/login`、`/register`、`/forgot-password`）就重定向登录页。`getAuthRoutes()` 负责把动态路由挂上（这里权限路由较简单，基本登录即可用）。

### 状态管理

`store/modules/user.js` 用 Vuex 管 `token` 和 `info`；登录时兼容后端两种返回（`res.data.token` 或 `res.data` 直接是 token）。登出清 `localStorage/sessionStorage` 里的 `vuex`/`tabs` 再跳登录。

### 构建与部署

Vite 多环境（`production` / `staging`），`manualChunks` 把 `echarts` 和 `vue-vendor` 拆包；`base` 由 `VITE_BASE_PATH` 控制；产物 `dist/` 交给 Nginx。

## 数据库设计（5 张表）

| 表 | 作用 | 要点 |
| --- | --- | --- |
| `sys_user` | 用户 | `user_password_hash`（PBKDF2）、`salt`、`aes_key_rsa_encrypted`（RSA 加密的 AES 密钥）、`aes_key_version` |
| `password_item` | 密码条目 | `password` 存 **AES-256-GCM 密文**，`user_id` 索引 |
| `password_evaluation_log` | 评估记录 | `evaluate_score`、`risk_type`、`suggestions` |
| `operation_log` | 操作日志 | `operation_type`、`operation_result`、`cost_time` |
| `weak_password` | 弱口令字典 | 极简种子（约 40 条），生产建议扩完整字典 |

`init.sql` 在 MySQL 卷为空时自动建库建表 + 写弱口令种子（删 `mysql-data` 卷可重置）。

## 安全设计点评

- **登录密码**走 PBKDF2 + 随机盐 + 常量时间比较，是正确做法；
- **密码条目** AES-256-GCM（带认证标签，防篡改）比 AES-CBC 更稳；
- **AES 密钥用 RSA 公钥加密落地**，即使数据库泄露，没有 RSA 私钥也解不出密码条目——这是合理的信封加密；
- 但也意味着**服务端握有 RSA 私钥就能解密全部明文**，不是"零知识"架构，私钥的保管（外部注入、KMS）是这条链路的真正命门。

## 从工程角度可再打磨的点

下面几条是读代码时觉得"可以更好"的地方，纯属技术讨论：

1. **`@Value` 注入到 `static` 字段**：`RedisTokenUtil.secretKey` 用 `private static` + `@Value`，Spring **不会给静态字段注入**，运行时会是 `null`，Token 签名会 NPE。建议改成实例字段（或 `@PostConstruct` 赋值）。
2. **操作日志失败分支会重复落库**：`OperationLogAspect` 的 `catch` 里 `save` 一次，`finally` 里又 `save` 一次，失败时会写两条日志（成功路径只写一条，行为不一致）。
3. **RSA 公钥硬编码在源码**（`RSA4096Util.PUBLIC_KEY_BASE64`）：公钥虽可公开，但写死不便轮换；私钥走占位符/外部注入，公钥建议同样外置。
4. **生产默认 `token.secret-key: change-me-in-production`**：README 已警告，但默认值仍是弱密钥，建议构建/启动期对默认值直接拒绝启动。
5. **前端依赖偏旧**：axios `0.26.1`、Vite `2`、Element Plus `2.3.8` 都是 2022 年前后版本，存在已知 CVE 与生态落后，可以考虑升级。
6. **Token 是有状态的**：强依赖 Redis，做集群/高可用时要保证 Redis 高可用或上 Redis Cluster。

## 部署速览

```bash
cp .env.example .env          # 填 MySQL/Redis/Token 密钥/华为云 AK-SK
docker compose up -d --build  # MySQL8 + Redis7 + 后端 + 前端(Nginx)
# 访问 http://localhost （前端），后端接口 http://localhost:8080
```

## 参考

- 本地源码：`D:\dev-environment\code\cipherlens`
- [Spring Boot 官方文档](https://spring.io/projects/spring-boot)
- [MyBatis-Plus 文档](https://baomidou.com/)
- [Vue 3 官方文档](https://cn.vuejs.org/)
- [Element Plus](https://element-plus.org/)
