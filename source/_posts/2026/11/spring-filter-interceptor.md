---
title: "过滤器与拦截器全方面对比：Spring Boot 里到底差在哪"
slug: spring-filter-interceptor
date: 2026-11-24 14:00:00
description: "从 Servlet 规范与 Spring MVC 两个层面讲清 Filter 与 Interceptor 的来源、生命周期、执行顺序与能力边界，配一个 Spring Boot 3.5.7 最小工程的 MockMvc 实测输出，再给出典型场景的选型表和常见误区。"
categories:
  - 技术
tags:
  - Web 框架
  - Java
cover: /img/2026/11/spring-filter-interceptor.jpg
---

> 同一个请求上，过滤器和拦截器都能"拦"，但拦的位置、拿到的信息、能做的事完全不同。一句话先记住：**Filter 是 Servlet 容器层面的关卡，Interceptor 是 Spring MVC 层面的关卡**。Filter 永远在 `DispatcherServlet` 之前，Interceptor 在 `DispatcherServlet` 内部、handler 映射完成之后。
>
> 下面所有顺序结论都基于一个 **Spring Boot 3.5.7 + Java 21** 的最小工程，用 `MockMvc` 真实跑出来，不是背书式的口述。

## 1. 先给结论

| | Filter | Interceptor |
| --- | --- | --- |
| 归属 | Jakarta Servlet 规范（容器层） | Spring MVC（`DispatcherServlet` 内部） |
| 位置 | `DispatcherServlet` 之前 | handler 映射之后、方法调用前后 |
| 能拿到 handler 信息 | 不能 | 能（`HandlerMethod`、方法/类注解） |
| 注册方式 | `@Component` + `@Order`、`FilterRegistrationBean` | `WebMvcConfigurer.addInterceptors` |
| 路径匹配 | Servlet 风格 `/api/*` | Spring MVC 风格 `/api/**` |
| 能改视图 | 不能 | `postHandle` 能拿到 `ModelAndView` |
| 异常受 `@ControllerAdvice` 处理 | 否 | 是 |
| 典型职责 | 编码、CORS、trace、请求/响应包装 | 认证、方法级权限、耗时、审计 |

## 2. 一个请求的完整路径

{% mermaid %}
%%{init: {'theme':'base', 'themeVariables': {'fontFamily':'inherit','fontSize':'14px','minNodeSpacing':20}}}%%
flowchart TB
    A["HTTP 请求"] --> F1["Filter 链<br/>Trace/Header"]
    F1 --> DS["Dispatcher<br/>Servlet"]
    DS --> I1["preHandle<br/>正序：Auth→Timing"]
    I1 --> H["Controller"]
    H --> I2["postHandle<br/>逆序：Timing→Auth"]
    I2 --> V["视图渲染"]
    V --> I3["完成回调<br/>逆序：Timing→Auth"]
    I3 --> F2["Filter 收尾"]
    F2 --> R["响应"]
{% endmermaid %}

Filter 的 `doFilter` 用 `chain.doFilter()` 把请求往下放，自己则用 `try/finally` 包住整个下游；拦截器由 `DispatcherServlet` 在 handler 执行链里逐个调用，分 `preHandle`、`postHandle`、`afterCompletion` 三个回调。

## 3. 来源与定义

### 3.1. Filter：Servlet 规范的过滤器

`Filter` 是 Jakarta Servlet 规范（Spring Boot 3 用 `jakarta.servlet.Filter`）定义的接口，和 Spring 没有必然关系，容器就能管理。三个方法：`init`、`doFilter`、`destroy`，真正干活的是 `doFilter`：

```java
// 作用：声明为 Spring Bean，让 Boot 把它注册进 Servlet 容器
@Component
// 作用：控制该 Filter 在 Filter 链中的位置，数字小先执行
@Order(1)
public class TraceFilter extends OncePerRequestFilter {

    @Override
    // 作用：单个请求的过滤逻辑，由容器在请求进入时调用
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        // 作用：记录请求进入 Filter 链
        log.info("TRACE filter enter {}", request.getRequestURI());
        try {
            // 作用：把请求交给下一个 Filter，最终交给 DispatcherServlet
            filterChain.doFilter(request, response);
        } finally {
            // 作用：无论下游是否抛异常，都会记录请求离开
            log.info("TRACE filter exit  {}", request.getRequestURI());
        }
    }
}
```

`OncePerRequestFilter` 是 Spring 提供的基类，用请求属性保证**每个请求只过滤一次**（默认跳过 ASYNC、ERROR 的二次 dispatch），做 trace、包装这类无状态逻辑时优先继承它。

### 3.2. Interceptor：Spring MVC 的拦截器

`HandlerInterceptor` 是 Spring MVC 自己的接口，由 `DispatcherServlet` 在处理请求时调用：

```java
// com.example.filterinterceptor.TimingInterceptor
public class TimingInterceptor implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws Exception {
        // 作用：记录耗时起点
        long start = System.currentTimeMillis();
        // 作用：把起点存到请求属性，供 afterCompletion 计算耗时
        request.setAttribute("timing.start", start);
        String note = "";
        // 作用：命中控制器方法时，可读取方法上的自定义注解
        if (handler instanceof HandlerMethod handlerMethod
                && handlerMethod.getMethodAnnotation(Tracked.class) != null) {
            // 作用：命中 @Tracked 时在日志中标注出来
            note = " @Tracked";
        }
        // 作用：记录本次 preHandle，返回 true 表示放行
        log.info("TIMING preHandle{} {}", note, request.getRequestURI());
        return true;
    }

    @Override
    public void postHandle(HttpServletRequest request, HttpServletResponse response, Object handler,
                           ModelAndView modelAndView) {
        // 作用：handler 正常返回后执行，按拦截器逆序调用
        log.info("TIMING postHandle {}", request.getRequestURI());
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler,
                                Exception ex) {
        // 作用：取出起点算出耗时并记录；异常路径也会执行
        long start = (Long) request.getAttribute("timing.start");
        log.info("TIMING afterCompletion {} cost={}ms",
                request.getRequestURI(), System.currentTimeMillis() - start);
    }
}
```

注意 `preHandle` 里的 `handler`：命中控制器方法时它是 `HandlerMethod`，能直接读到方法上的注解（示例里的 `@Tracked`）。这是 Filter 完全拿不到的能力，也是两者最根本的分野。

## 4. 生命周期与调用时机

| 时机 | Filter | Interceptor |
| --- | --- | --- |
| 启动时 | `init` 执行一次 | 无，随 Spring 容器创建 |
| 请求开始 | `doFilter` | `preHandle`（按注册正序） |
| handler 返回后 | 还在 `doFilter` 内 | `postHandle`（按注册逆序） |
| 响应完成后 | `doFilter` 返回 | `afterCompletion`（按注册逆序） |
| 销毁 | `destroy` | 随容器销毁 |

三个容易踩的细节：

- **`preHandle` 返回 `false` 即短路**：后续拦截器和控制器都不会执行，而且返回 `false` 的拦截器自己也不会收到 `afterCompletion`。
- **`postHandle` 只在 handler 正常返回时调用**：handler 抛异常时直接跳过；`afterCompletion` 则只要 `preHandle` 返回过 `true` 就会执行，异常也会执行。
- **异步请求**：handler 启动异步后，初始线程不会走 `postHandle`/`afterCompletion`，改为回调 `AsyncHandlerInterceptor.afterConcurrentHandlingStarted`；等异步结果回到容器再次 dispatch 时，才走 `postHandle`/`afterCompletion`。Filter 对异步则要注意 ASYNC dispatch。

## 5. 执行顺序：谁先谁后（实测）

实测配置：两个 Filter（`TraceFilter` 用 `@Order(1)`，`HeaderFilter` 用 `FilterRegistrationBean` 注册在 `/api/*`），两个拦截器（`AuthInterceptor` order 1、`TimingInterceptor` order 2，都挂在 `/api/**`），一个带 `@Tracked` 的控制器。

```java
// WebConfig
@Override
public void addInterceptors(InterceptorRegistry registry) {
    // 作用：认证拦截器挂到 /api/**，order 小先执行
    registry.addInterceptor(new AuthInterceptor())
            .order(1)
            .addPathPatterns("/api/**");
    // 作用：计时拦截器排在后面，preHandle 晚于认证、后置回调早于认证
    registry.addInterceptor(new TimingInterceptor())
            .order(2)
            .addPathPatterns("/api/**");
}
```

请求 `GET /api/hello`（带 `X-Auth: demo`）的实际日志：

```text
TRACE filter enter /api/hello
HEADER filter enter /api/hello
AUTH preHandle /api/hello
TIMING preHandle @Tracked /api/hello
CONTROLLER hello
TIMING postHandle /api/hello
AUTH postHandle /api/hello
TIMING afterCompletion /api/hello cost=2ms
AUTH afterCompletion /api/hello
HEADER filter exit  /api/hello
TRACE filter exit  /api/hello
```

三点结论：

1. **Filter 整体包在最外层**：所有 Filter 的 enter/exit 都出现在整个链路最前和最后，必然先于任何拦截器。
2. **拦截器 `preHandle` 正序，`postHandle`/`afterCompletion` 逆序**：order 小的先进入，后退出。
3. **`postHandle` 对 `@ResponseBody` 也会调用**：日志里 `CONTROLLER hello` 之后 `TIMING postHandle` 依然执行，但此时响应体已经由消息转换器写出，在 `postHandle` 里再改响应体或状态通常无效。

### 5.1. preHandle 返回 false 的短路（实测）

不带 `X-Auth` 请求同一个接口：

```text
TRACE filter enter /api/hello
HEADER filter enter /api/hello
AUTH preHandle /api/hello
HEADER filter exit  /api/hello
TRACE filter exit  /api/hello
```

`AuthInterceptor` 在 `preHandle` 里写 401 并返回 `false`，结果是：**后续拦截器不执行、控制器不执行、返回 `false` 的拦截器自己的 `afterCompletion` 也不执行**；而两个 Filter 的 `finally` 收尾照常执行。这是认证类拦截器的标准写法。

### 5.2. 控制器抛异常时（实测）

请求 `/api/boom`，控制器抛 `IllegalStateException`：

```text
TRACE filter enter /api/boom
HEADER filter enter /api/boom
AUTH preHandle /api/boom
TIMING preHandle @Tracked /api/boom
CONTROLLER boom
ADVICE handle IllegalStateException: boom
TIMING afterCompletion /api/boom cost=66ms
AUTH afterCompletion /api/boom
HEADER filter exit  /api/boom
TRACE filter exit  /api/boom
```

异常发生在 `DispatcherServlet` 内部，所以 `@ControllerAdvice` 接住了它；**`postHandle` 被跳过，`afterCompletion` 依然执行**。这和上一条规则是同一个机制：异常只影响 `postHandle`，不影响 `afterCompletion`。

## 6. 能力边界对比

| 能力 | Filter | Interceptor |
| --- | --- | --- |
| 拿到 `HandlerMethod`、读方法/类注解 | ❌ | ✅ |
| 修改视图、操作 `ModelAndView` | ❌ | ✅（`postHandle`） |
| 直接写响应 | ✅ | ✅（`preHandle` 里写并返回 false） |
| 包装请求/响应 | ✅（`HttpServletRequestWrapper` 等） | 拿到的是 Filter 包装后的对象 |
| 异常进入 `HandlerExceptionResolver` | ❌（在容器层，`@ControllerAdvice` 接不到） | ✅ |
| 依赖注入 | 需注册为 Bean 才行 | 天然是 Spring Bean |
| 作用范围 | 进入容器的请求（含容器级映射） | 仅 `DispatcherServlet` 处理的请求 |
| 异步 | 注意 ASYNC/ERROR dispatch | `AsyncHandlerInterceptor` 专门处理 |
| 执行次数 | 每次 `doFilter` | 每个匹配的 handler 执行链 |

## 7. Filter 的用法与坑

### 7.1. 注册方式

1. **`@Component` + `@Order`**：最省事，Spring Boot 自动注册，默认 URL 模式 `/*`、只对 REQUEST dispatch 生效，顺序看 `@Order`。
2. **`FilterRegistrationBean`**：要精确控制路径、dispatcher 类型和顺序时用：

```java
// 作用：注册 Filter，精确控制路径、dispatcher 类型和顺序
@Bean
public FilterRegistrationBean<HeaderFilter> headerFilterRegistration() {
    // 作用：新建注册项，并指定要注册的 Filter 实例
    FilterRegistrationBean<HeaderFilter> registration = new FilterRegistrationBean<>(new HeaderFilter());
    // 作用：Servlet 风格路径，只匹配 /api/ 下
    registration.addUrlPatterns("/api/*");
    // 作用：只对普通请求生效，默认不含 FORWARD/ASYNC/ERROR
    registration.setDispatcherTypes(DispatcherType.REQUEST);
    // 作用：设置在 Filter 链中的执行顺序
    registration.setOrder(2);
    return registration;
}
```

### 7.2. 常见坑

- **路径是 Servlet 风格，不是 Spring 风格**：写 `/api/*`、`/*`。`/api/**` 按 Servlet 规范不是通配路径，会被当成精确匹配（实际永远匹配不到普通请求），别照搬 MVC 的写法。
- **dispatcher 类型默认只有 REQUEST**：`FORWARD`、`INCLUDE`、`ASYNC`、`ERROR` 要显式 `setDispatcherTypes`。
- **读请求体会把流耗掉**：下游控制器再读就是空的。要缓存 body 得自己包装（如 `ContentCachingRequestWrapper` 或自定义 `HttpServletRequestWrapper` 缓存输入流）。
- **Filter 里抛异常绕过 Spring MVC**：`@ControllerAdvice` 接不到，由容器接管（Boot 下通常走到 `/error`），排查时别把两层混在一起。
- **响应提交后不可改**：`getWriter()`/`getOutputStream()` 一旦写出，状态码和响应头就定型了。
- **异步请求**：`doFilter` 在异步任务启动后即返回，在 `finally` 里清理 MDC/日志上下文可能过早；需要时重写 `OncePerRequestFilter.shouldNotFilterAsyncDispatch()` 和 `shouldNotFilterErrorDispatch()`。

## 8. Interceptor 的用法与坑

### 8.1. 注册与典型写法

```java
@Configuration
public class WebConfig implements WebMvcConfigurer {
    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // 作用：认证拦截器挂到 /api/**，排除公开接口，order 小先执行
        registry.addInterceptor(new AuthInterceptor())
                .order(1)
                .addPathPatterns("/api/**")
                .excludePathPatterns("/api/public/**");
    }
}
```

认证拦截器的标准实现：`preHandle` 里校验，不通过就写响应并返回 `false`：

```java
@Override
public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
        throws Exception {
    // 作用：校验请求头，未通过则直接写响应并返回 false
    if (!"demo".equals(request.getHeader("X-Auth"))) {
        // 作用：设置 401 状态码
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        // 作用：设置 JSON 响应类型，避免中文乱码
        response.setContentType("application/json;charset=UTF-8");
        // 作用：写出错误响应，返回 false 中断后续拦截器和控制器
        response.getWriter().write("{\"error\":\"missing X-Auth\"}");
        return false;
    }
    // 作用：校验通过，放行
    return true;
}
```

### 8.2. 常见坑

- **拦截器是单例**：不要把请求级状态放进字段，用 `request.setAttribute` 或局部变量。
- **`postHandle` 对 `@ResponseBody` 改不了响应**：响应体已写出，需要改响应就在 `preHandle` 做，或用 Filter 包装 `Response`。
- **handler 抛异常时只跳过 `postHandle`**：只要该拦截器的 `preHandle` 返回过 `true`，`afterCompletion` 仍会执行，清理资源和记审计放在这里才能覆盖异常路径。
- **作用范围是 `DispatcherServlet`**：只处理走 MVC 的请求。Boot 里静态资源由 `ResourceHttpRequestHandler` 处理、同样经过 `DispatcherServlet`，所以拦截器也会命中（路径匹配时会命中）；但容器直接处理或不在 MVC 映射里的请求不会经过拦截器。
- **异步场景要换接口**：用 `AsyncHandlerInterceptor`，初始线程回调 `afterConcurrentHandlingStarted`，异步完成后的二次 dispatch 才走 `postHandle`/`afterCompletion`。

## 9. 场景选型

| 需求 | 选谁 | 原因 |
| --- | --- | --- |
| 统一加响应头、CORS、字符编码 | Filter | 与 handler 无关，容器级统一处理 |
| 链路 trace ID、访问日志 | Filter | 所有进入容器的请求都要有 |
| 请求体缓存、包装、限流 | Filter | 在 MVC 之前就能读到原始请求 |
| 登录态校验、方法级权限注解 | Interceptor | 需要 `HandlerMethod` 上的元信息 |
| 控制器耗时统计、审计 | Interceptor | 天然覆盖 handler 生命周期 |
| 视图/模型处理 | Interceptor | `postHandle` 能拿到 `ModelAndView` |
| 安全粗筛 + 细粒度权限 | 组合 | Filter 做网关级（trace、包装、认证粗筛），Interceptor 做 handler 级（方法权限） |

安全场景是最典型的组合用法：Spring Security 本身就是一条 Filter 链，负责认证和粗粒度授权；方法级权限（`@PreAuthorize`、自定义注解）交给拦截器或 AOP，因为只有拦截器能拿到 `HandlerMethod`。

## 10. 常见误区

1. **"Filter 一定比 Interceptor 先执行"**：对进入 `DispatcherServlet` 的请求成立；但容器级映射的请求（没走 MVC）只有 Filter 会执行。两个 Filter 内部的顺序由自己的 order 决定，和拦截器顺序是两套独立排序。
2. **"拦截器不能写响应"**：能。`preHandle` 里写响应并返回 `false` 是认证拦截器的常规写法。
3. **"拦截器不能读请求体"**：能读，但 body 是流，读完后控制器读不到，需要包装缓存。
4. **"异常都能被 `@ControllerAdvice` 接住"**：只有发生在 `DispatcherServlet` 内部的异常（控制器、拦截器 `preHandle`）才会走 `HandlerExceptionResolver`；Filter 里抛出的异常在容器层。
5. **"拦截器不处理静态资源"**：在 Boot 里静态资源由 `ResourceHttpRequestHandler` 处理，也经过 `DispatcherServlet`，拦截器同样生效，除非用 `excludePathPatterns` 排除。
6. **"Filter 里用不了 Spring Bean"**：只要注册为 Bean（`@Component` 或 `@Bean`）就能注入；不注册、由容器自己实例化的 Filter 没有 Spring 上下文。

## 11. 结语

选 Filter 还是 Interceptor，本质是**选在哪一层做横切**：

- 容器层、和 handler 无关、所有请求都要覆盖 → **Filter**；
- MVC 层、需要 handler 元信息、需要控制视图 → **Interceptor**。

记住三组固定规律，实践中就不会乱：**Filter 永远在外层**；**拦截器 `preHandle` 正序、后置回调逆序**；**handler 异常只跳过 `postHandle`，`preHandle` 已返回 `true` 的拦截器仍会收到 `afterCompletion`**。另外，Filter 里抛出的异常在容器层，`@ControllerAdvice` 接不到。最后一条是写安全代码的底线：把清理和审计放在一定会执行的位置，而不是"看起来会执行"的位置。
