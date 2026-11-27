---
title: "Spring AOP 的代理边界：final、private、自调用，注解为什么不生效"
slug: spring-aop-proxy
date: 2026-11-27 10:12:41
description: "用 ProxyFactory 手工织入加真实 @EnableAspectJAutoProxy 两套实验，把 Spring AOP 的边界一条条测出来：接口走 JDK、没接口走 CGLIB、final 和 private 方法拦不到、自调用只拦外层；顺手踩到一个坑——容器里只要有一个 @EnableAspectJAutoProxy(proxyTargetClass=true)，全局都变 CGLIB。"
categories:
  - 技术
tags:
  - Spring AOP
cover: /img/2026/11/spring-aop-proxy.jpg
---

> 「Spring AOP 靠代理实现」这句话人人会说，但代理到底在哪一刀切下去，是另一回事。注解写在方法上不代表它会被执行——`final` 方法拦不到，`private` 方法拦不到，同一个类里 `this.other()` 也拦不到。
>
> 这篇用 Spring 6.2.12 做了两组实验：一组用 `ProxyFactory` 手工织入，逐个验证边界；一组用真实的 `@EnableAspectJAutoProxy` + `@Aspect` 走自动代理，看 Spring 到底给谁生成了哪种代理。结论是：有接口就 JDK、没接口就 CGLIB，且 cast 回实现类会直接 `ClassCastException`。最后是一个我自己踩到的坑——两个配置类被同一个包扫描进来，其中一个写了 `proxyTargetClass=true`，整个容器所有代理都变成了 CGLIB。

## 1. 先给结论

| 情况 | 结果 | 原因 |
|---|---|---|
| 目标类实现了接口，默认配置 | JDK 动态代理 `jdk.proxy1.$Proxy0` | 代理只实现接口 |
| 同上，但 `cast` 成实现类 | `ClassCastException` | 代理不是目标类的子类 |
| `proxyTargetClass = true` | CGLIB `Target$$SpringCGLIB$$0` | 生成子类 |
| 目标类没有接口 | 只能 CGLIB | JDK 代理必须有接口 |
| `final` 方法 | **拦不到** | CGLIB 靠覆写，final 不能覆写 |
| `private` 方法 | **拦不到** | 私有方法不可覆写/不可见 |
| 自调用 `this.inner()` | **拦不到** | 不经过代理对象 |

一句话：**Spring AOP 是运行时代理，不是编译期织入。任何让调用不经过代理对象的写法，注解都会失效。**

## 2. 实验怎么搭的

两组实验，都在 `.tmp-check/exp/spring-aop/` 下。

第一组用 `ProxyFactory` 手工织入，绕开容器配置，把边界一条条摆出来：

```java
// 手工织入：拦截器只打印一行，方便数「谁被拦了」
class Marker {}  // 占位接口，用来触发 JDK 代理
static class Target implements Marker {
    public void normal() { System.out.println("normal-ok"); }
    public final void finalMethod() { System.out.println("final-ok"); }
    public void privateCaller() { secret(); }
    private void secret() { System.out.println("secret-ok"); }
    public void outer() { this.inner(); }
    public void inner() { System.out.println("inner-ok"); }
}
```

```java
// 有接口 + 默认配置 → JDK
ProxyFactory pf = new ProxyFactory(new Target());
pf.addAdvice((MethodInterceptor) inv -> {
    System.out.println("    [advice] hit " + inv.getMethod().getName());
    return inv.proceed();
});
Object proxy = pf.getProxy();
```

第二组走真实容器配置，因为 `@Transactional`、`@Cacheable` 这些注解走的都是自动代理那条路：

```java
// 默认：不设 proxyTargetClass
@Configuration
@EnableAspectJAutoProxy
static class Cfg {
    @Bean TopGreeter top() { return new TopGreeterImpl(); }
    @Bean LogAspect2 aspect() { return new LogAspect2(); }
}
```

这里用显式 `@Bean` 而不是 `@ComponentScan`，原因放在后面那节讲——包扫描本身就是一个坑。

## 3. 两种代理：JDK 和 CGLIB

`DefaultAopProxyFactory` 的判定逻辑其实只有三行（Spring 6.2.12 源码）：

```java
// config 里只要有 optimize / proxyTargetClass，或者「没有用户指定的接口」，就走 CGLIB 分支
if (config.isOptimize() || config.isProxyTargetClass() || !config.hasUserSuppliedInterfaces()) {
    Class<?> targetClass = config.getTargetClass();
    // 目标本身就是接口、或已经是 Proxy、或是 lambda，仍退回 JDK
    if (targetClass == null || targetClass.isInterface() ||
            Proxy.isProxyClass(targetClass) || ClassUtils.isLambdaClass(targetClass)) {
        return new JdkDynamicAopProxy(config);
    }
    return new ObjenesisCglibAopProxy(config);
}
else {
    return new JdkDynamicAopProxy(config);
}
```

也就是说：**只要有接口可选，默认就是 JDK 代理**。实测输出：

```text
== 1. 有接口，默认 JDK 动态代理 ==
    class      = jdk.proxy1.$Proxy0
    superclass = java.lang.reflect.Proxy
    interfaces = [interface demo.App$Marker, interface org.springframework.aop.SpringProxy,
                  interface org.springframework.aop.framework.Advised,
                  interface org.springframework.core.DecoratingProxy]
    isJDK=true isCGLIB=false
    cast to Target 失败: ClassCastException（代理只实现接口）
```

注意 `interfaces` 里那三个 Spring 自带的接口：`SpringProxy` 是标记，`Advised` 让你能从外部拿到代理的拦截器链，`DecoratingProxy` 用来反查原始类。这三个是 Spring 加的，不是你写的。

强制 CGLIB，多一行 `pf.setProxyTargetClass(true)`：

```text
== 2. proxyTargetClass=true，强制 CGLIB ==
    class      = demo.App$Target$$SpringCGLIB$$0
    superclass = demo.App$Target
    interfaces = [interface demo.App$Marker, interface SpringProxy,
                  interface Advised, interface org.springframework.cglib.proxy.Factory]
```

子类代理的好处是能 `cast` 回目标类型，代价是类不能被 `final` 修饰、方法不能是 `final`。

## 4. 自动代理默认给谁：接口就 JDK

真实的 `@EnableAspectJAutoProxy` 不设 `proxyTargetClass` 时，实测输出：

```text
== 默认 @EnableAspectJAutoProxy ==
    creator.proxyTargetClass=false
    class=jdk.proxy2.$Proxy15
    isJDK=true isCGLIB=false
    [aspect] before
    greet() = hello-top
    cast to TopGreeterImpl -> ClassCastException
```

`creator.proxyTargetClass=false` 是关键：`AbstractAutoProxyCreator.createProxy()` 在非 CGLIB 模式下会调用 `evaluateProxyInterfaces(beanClass, proxyFactory)`，把目标类**实现的接口**塞进 `ProxyFactory`。于是 `hasUserSuppliedInterfaces()` 变成 true，`DefaultAopProxyFactory` 走 JDK 分支。

反过来，目标类一个接口都没有，`evaluateProxyInterfaces` 什么都加不进去，只能退回 CGLIB：

```text
== 6. 无接口，只能 CGLIB ==
    class      = demo.App$Plain$$SpringCGLIB$$0
    superclass = demo.App$Plain
    isJDK=false isCGLIB=true
```

这就解释了为什么「给 Service 抽个接口」在 Spring 项目里不只是分层习惯——它决定了代理方式。也解释了为什么 `@Transactional` 加在**实现类**的方法上、而调用方注入的是接口时，一切正常；一旦某个地方按实现类注入，就可能因为 JDK 代理不是实现类的子类而报 `ClassCastException`。

## 5. final 方法：CGLIB 拦不到

CGLIB 的原理是生成子类、覆写方法。`final` 方法不能覆写，所以拦截器根本没机会插进去。实测：

```text
== 3. CGLIB 拦 final 方法 ==
    [advice] hit normal
    normal() = normal-ok
    finalMethod() = final-ok
```

两行输出里只有 `normal` 有 `[advice]` 前缀，`finalMethod()` 直接执行了原方法体。**没有异常，没有警告**——这正是最麻烦的地方：你以为事务开了，其实没开。

## 6. private 方法：同样拦不到

```text
== 4. CGLIB 拦 private 方法（公有方法里调用私有的）==
    [advice] hit privateCaller
    privateCaller() = private -> secret-ok
```

`privateCaller()` 被拦了，但它内部调用的 `secret()` 没有。私有方法在子类里不可见，CGLIB 生成的子类里压根没有这个方法的覆写版本。

## 7. 自调用：只拦外层

```text
== 5. 自调用 outer() -> this.inner() ==
    [advice] hit outer
    outer() = outer -> inner-ok
```

`outer()` 被拦，`inner()` 没有。`this` 指向的是原始对象，不是代理对象，所以 `this.inner()` 是一次普通的 Java 调用。

这一条和上一篇《Spring 事务传播 7 种行为》里的实测是同一件事的两个视角：那篇里 `this.innerRequiresNew()` 因为绕过代理，`REQUIRES_NEW` 完全没有生效；这里看到的是同一个机制——**代理只在「从外部进来」的那一次调用上生效**。

三种解法，按推荐程度排：

```java
// 1. 拆 Bean（最稳）：inner 放到独立 Service，注入后调用
@Autowired private InnerService inner;

// 2. 注入自己：Spring 4.3+ 支持自注入，拿到的是代理对象
@Autowired @Lazy private SelfService self;

// 3. 暴露代理，从 ThreadLocal 里取
// 配置：@EnableAspectJAutoProxy(exposeProxy = true)
SelfService self = (SelfService) AopContext.currentProxy();
```

第 3 种要在注解上开 `exposeProxy = true`，否则 `AopContext.currentProxy()` 直接抛 `IllegalStateException: Cannot find current proxy`。它还有一个副作用：每次调用都要往 ThreadLocal 里塞/取，有微小开销，且跨线程会丢。

## 8. 一个坑：容器里只要有一个人要 CGLIB，全局都变 CGLIB

这是我做实验时真踩到的。第一版把两个配置类都放在 `demo` 包里，用 `@ComponentScan` 扫描，结果「默认配置」那一组也拿到了 CGLIB 代理，和预期不符。查了一下 creator 的属性：

```text
    creator=org.springframework.aop.aspectj.annotation.AnnotationAwareAspectJAutoProxyCreator
    proxyTargetClass=true
```

原因是 `@EnableAspectJAutoProxy(proxyTargetClass = true)` 的处理逻辑：

```java
// AopConfigUtils：无条件往共享的 auto-proxy creator 上写 proxyTargetClass=true
public static void forceAutoProxyCreatorToUseClassProxying(BeanDefinitionRegistry registry) {
    if (registry.containsBeanDefinition(AUTO_PROXY_CREATOR_BEAN_NAME)) {
        BeanDefinition definition = registry.getBeanDefinition(AUTO_PROXY_CREATOR_BEAN_NAME);
        definition.getPropertyValues().add("proxyTargetClass", Boolean.TRUE);
    }
}
```

方法名叫 `force`，因为没有反向操作。auto-proxy creator 在整个容器里只有一个（bean 名 `org.springframework.aop.config.internalAutoProxyCreator`），所以**任何一个**配置类写了 `proxyTargetClass = true`，整个容器所有被代理的 bean 都会变成 CGLIB，与声明顺序无关。

生产环境里这条的典型触发方式是：某个 starter 或某个同事的基础配置类打开了 CGLIB，你以为自己用的是 JDK 代理，实际不是。表现就是某处 `(SomeImpl) bean` 突然能 cast 成功了、或者某个 `final` 类突然报
`Cannot subclass final class`。

验证方法只有一句——把 creator 的属性打出来：

```java
// 想看当前容器到底用哪种代理，直接问 creator
Object c = ctx.getBean(AopConfigUtils.AUTO_PROXY_CREATOR_BEAN_NAME);
System.out.println(((ProxyConfig) c).isProxyTargetClass());
```

## 9. Spring Boot 的默认值不一样

手工装配（纯 Spring Framework）时 `@EnableAspectJAutoProxy` 的 `proxyTargetClass` 默认是 `false`，上面测的就是这个。**Spring Boot 不是**：从 2.0 起 `AopAutoConfiguration` 的默认值就是 `spring.aop.proxy-target-class=true`，也就是 Boot 应用里默认走 CGLIB。

所以同一个 Service，在纯 Spring 工程里是 JDK 代理（cast 实现类会炸），搬到 Boot 里是 CGLIB（cast 成功）。这解释了为什么「加个接口更安全」这条经验在 Boot 项目里经常不起作用——它本来就不走 JDK 分支。

## 10. 常见坑

1. **`final` 方法上加 `@Transactional`**。CGLIB 拦不到，注解静默失效。类上标 `final` 更直接：`Cannot subclass final class`。
2. **`private` 方法上加注解**。同理失效。要让注解生效，方法至少得是 `protected` 或 `public`。
3. **同类内 `this.xxx()` 调用**。注解完全不生效，且没有任何日志。拆 Bean 或用自注入。
4. **按实现类注入，却拿到 JDK 代理**。`ClassCastException`，或者注入失败 `NoSuchBeanDefinitionException`。要么全部按接口注入，要么开 CGLIB。
5. **以为 `proxyTargetClass` 只在当前配置类生效**。它写在共享的 creator 上，一个配置类开了，全容器都变。
6. **在 `@PostConstruct` 里调自己的被代理方法**。此时对象还没被代理包起来，注解不生效。
7. **用 `AopContext.currentProxy()` 但忘了 `exposeProxy = true`**。直接 `IllegalStateException`。

## 11. 重点总结

实测出来的四条硬结论：

1. **默认：有接口走 JDK，没接口走 CGLIB**。`creator.proxyTargetClass=false` 时，`evaluateProxyInterfaces` 会把目标类的接口交给 `ProxyFactory`，于是 `hasUserSuppliedInterfaces()` 为 true。
2. **JDK 代理不是目标类的子类**，`cast` 回实现类必炸。CGLIB 是子类，能 cast，但绕不过 `final`。
3. **`final` 方法、`private` 方法、自调用，三者都绕过代理**。前两个是覆写机制的限制，第三个是 `this` 指向原始对象。
4. **`proxyTargetClass` 是容器级开关**，`forceAutoProxyCreatorToUseClassProxying` 只有开没有关；Spring Boot 的默认值是 `true`。

写 AOP 相关代码时最值的两个习惯：**方法别写 `final`/`private`，同类调用拆成独立 Bean**；以及**不确定走哪种代理时，把 creator 的 `isProxyTargetClass()` 打出来看一眼**，比猜快得多。

## 12. 参考

- Spring Framework 6.2.12 源码：`DefaultAopProxyFactory`、`AopConfigUtils`、`AbstractAutoProxyCreator`
- [Spring Framework Reference — Aspect Oriented Programming](https://docs.spring.io/spring-framework/reference/core/aop.html)
- [Spring Framework Reference — Proxying Mechanisms](https://docs.spring.io/spring-framework/reference/core/aop/proxying.html)
- [Spring Boot — AopAutoConfiguration](https://docs.spring.io/spring-boot/docs/current/api/org/springframework/boot/autoconfigure/aop/AopAutoConfiguration.html)
