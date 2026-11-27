---
title: "Spring 事务传播 7 种行为，我跑了一遍"
slug: spring-transaction-propagation
date: 2026-11-25 12:00:00
description: "用 Spring Boot 3.5.7 + H2 搭一个最小工程，逐项实测 REQUIRED / REQUIRES_NEW / NESTED / SUPPORTS / NOT_SUPPORTED / MANDATORY / NEVER 的提交与回滚边界，并验证四个最容易踩的坑：内层异常被 catch、同类自调用、readOnly 写库、受检异常不回滚。"
categories:
  - 实践
tags:
  - Spring 事务
cover: /img/2026/11/spring-transaction-propagation.jpg
---

> 事务传播的 7 种行为，背定义和实际跑出来的结果经常对不上：内层抛异常被 catch 之后，外层并不一定能提交；`readOnly` 写库可能静默不落盘；同类自调用会让 `REQUIRES_NEW` 直接失效。这篇用一个最小工程把 7 种行为逐项跑完，每条都给实测结果，而不是背书。

## 1. 先给结论

| 传播行为 | 无外层事务 | 有外层事务 |
| --- | --- | --- |
| `REQUIRED` | 创建并加入新事务 | 加入外层事务，一起提交或回滚 |
| `REQUIRES_NEW` | 创建新事务 | **挂起**外层，开新事务并独立提交/回滚 |
| `NESTED` | 创建新事务 | 在外层内建 **savepoint**，只回滚内层，外层可继续 |
| `SUPPORTS` | 非事务执行（自动提交） | 加入外层事务 |
| `NOT_SUPPORTED` | 非事务执行 | **挂起**外层，以非事务方式执行 |
| `MANDATORY` | **抛异常** | 加入外层事务 |
| `NEVER` | 非事务执行 | **抛异常** |

这 7 种行为在 Spring 里是同一套代理逻辑，区别只在进入方法时调用 `handleTransactionAttribute` 时走哪个分支。下面每个都实测一遍。

## 2. 实验怎么搭

环境：Spring Boot 3.5.7、JDK 21、H2 内存库（`MODE=MySQL`）。事务传播是 Spring 层的语义，与数据库无关；`NESTED` 用到的 savepoint H2 也支持，所以 H2 足够。

```properties
# src/main/resources/application.properties
spring.datasource.url=jdbc:h2:mem:tx;MODE=MySQL;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000
spring.jpa.hibernate.ddl-auto=create-drop
```

工程结构很薄，就三层：

```text
account 表（balance）
audit 表（id 自增，note）—— 每次操作插一条，用来观察事务到底提交了什么
InnerService    —— 被调用方，一个方法一种传播行为
OuterService    —— 调用方，负责开启外层事务，必要时 catch 内层异常
SelfInvocationService / ReadOnlyService —— 专门测自调用和 readOnly
```

一个必须交代的细节：**`NESTED` 在 `JpaTransactionManager` 下直接报错**，日志里是

```
NestedTransactionNotSupported JpaDialect does not support savepoints
```

JPA 方言不提供 savepoint 能力，所以传播测试全部走 `DataSourceTransactionManager`，`readOnly` 的 JPA 用例单独走 `JpaTransactionManager`。两者在配置里并存：

```java
// TxConfig.java
// 作用：JPA 默认事务管理器，名字必须是 transactionManager，readOnly 用例用它
@Bean("transactionManager")
@Primary
public PlatformTransactionManager jpaTx(EntityManagerFactory emf) {
    return new JpaTransactionManager(emf);
}

// 作用：纯 JDBC 事务管理器，开启 nested 支持，传播用例用它
@Bean("jdbcTx")
public PlatformTransactionManager jdbcTx(DataSource dataSource) {
    DataSourceTransactionManager manager = new DataSourceTransactionManager(dataSource);
    manager.setNestedTransactionAllowed(true);
    return manager;
}
```

下面所有传播用例都在 `jdbcTx` 上跑。

## 3. 七种行为逐项实测

每个用例的判定方式都一样：**在外层事务结束后，另开连接查 `audit` 表**，看哪些行真正落盘了。

### 3.1. REQUIRED：内外同生共死

```java
// InnerService.java
// 作用：REQUIRED，默认传播，加入调用方的事务
@Transactional(transactionManager = "jdbcTx", propagation = Propagation.REQUIRED)
public void required(String note, boolean fail) {
    insert(note);
    if (fail) {
        throw new IllegalStateException("inner-required-fail");
    }
}
```

```java
// OuterService.java
// 作用：外层事务里先插 outer，再让内层抛异常并向外传播
@Transactional(transactionManager = "jdbcTx")
public void requiredWithInnerFailure() {
    insert("outer");
    inner.required("inner", true);
}
```

实测：

```text
SCENARIO REQUIRED 内层抛异常并向外传播   expected=[]     actual=[]
```

异常从内层传到外层，整个事务回滚，`outer` 和 `inner` 都没有落盘。

### 3.2. REQUIRES_NEW：内层独立提交

外层 catch 内层异常后继续，内层的事务已经独立提交或回滚，不受影响：

```text
SCENARIO REQUIRES_NEW 内层回滚、外层提交   expected=[outer, outer-after]   actual=[outer, outer-after]
```

`inner` 回滚了，`outer` 与之后的 `outer-after` 正常提交。这就是「内层失败不能拖垮外层」的常用做法。

### 3.3. NESTED：只回滚到 savepoint

```java
// OuterService.java
// 作用：内层用 NESTED，失败后外层可以继续写
@Transactional(transactionManager = "jdbcTx")
public void nestedWithInnerFailure() {
    insert("outer");
    try {
        inner.nested("inner", true);
    } catch (IllegalStateException ignored) {
        insert("outer-after");
    }
}
```

```text
SCENARIO NESTED 内层回滚到 savepoint   expected=[outer, outer-after]   actual=[outer, outer-after]
```

内层回滚只回到 savepoint，外层接着写、最终提交。和 `REQUIRES_NEW` 的结果看起来一样，但实现机制完全不同：NESTED 不挂起外层连接，只回滚一段。

### 3.4. SUPPORTS：有则加入，无则非事务

```text
SCENARIO SUPPORTS 有外层事务   expected=active=true, [outer, inner]   actual=active=true, [outer, inner]
SCENARIO SUPPORTS 无外层事务   expected=active=false, [inner]        actual=active=false, [inner]
```

有外层事务时加入（`active=true`），没有时以非事务方式执行（`active=false`），每条 SQL 自动提交。内层能感知当前是否处于事务中。

### 3.5. NOT_SUPPORTED：挂起外层、内层独立

外层事务被挂起，内层以非事务方式执行，**内层写的内容不受外层回滚影响**：

```text
SCENARIO NOT_SUPPORTED 外层回滚、内层保留   expected=[inner]   actual=[inner]
```

外层最后抛异常回滚，`outer` 丢了，但 `inner` 保留。这是「想留审计/日志，又怕外层回滚把它一起带走」时的手段。

### 3.6. MANDATORY：必须有外层事务

```text
SCENARIO MANDATORY 无事务调用   expected=IllegalTransactionStateException   actual=IllegalTransactionStateException
SCENARIO MANDATORY 有外层事务   expected=[outer, inner]   actual=[outer, inner]
```

没有外层事务时直接抛 `IllegalTransactionStateException`；有则正常加入。适合「这个方法必须在某个事务里调用」的防御性约束。

### 3.7. NEVER：绝不加入外层事务

```text
SCENARIO NEVER 在外层事务中调用   expected=[]   actual=[]
```

有外层事务时抛 `IllegalTransactionStateException`，外层事务随之回滚。适合「这个方法永远要自己管事务」的场景。

## 4. 四个反直觉点

这 7 种行为里，真正值得记住的是下面四个实测出来的细节。

### 4.1. REQUIRED 内层异常被 catch，外层仍会回滚

最常见的误解是「内层异常被 catch 住，事务就能提交」。实测：

```java
// OuterService.java
// 作用：内层异常被 catch 后继续写，并正常返回
@Transactional(transactionManager = "jdbcTx")
public void requiredInnerFailureCaught() {
    insert("outer");
    try {
        inner.required("inner", true);
    } catch (IllegalStateException ignored) {
        insert("outer-after");
    }
}
```

```text
SCENARIO REQUIRED 内层异常被 catch 后提交   expected=[]   actual=[]
```

提交阶段抛的是 `UnexpectedRollbackException`，**一行都没落盘**。原因：内层 `REQUIRED` 加入的是同一个事务，内层抛异常时事务被标记为 `rollback-only`，外层即使 catch 住异常、正常返回，提交时也会发现这个标记而回滚。

要「内层失败不影响外层」，必须用 `REQUIRES_NEW` 或 `NESTED`，光 catch 没用。

### 4.2. 同类自调用会让 REQUIRES_NEW 失效

```java
// SelfInvocationService.java
// 作用：外层事务里用 this 调用内层方法，绕过代理
@Transactional(transactionManager = "jdbcTx")
public void outerThenFail() {
    jdbc.update("insert into audit(note) values ('self-outer')");
    this.innerRequiresNew();
    throw new IllegalStateException("self-outer-fail");
}

// 作用：标注 REQUIRES_NEW，但自调用时不会走到代理
@Transactional(transactionManager = "jdbcTx", propagation = Propagation.REQUIRES_NEW)
public void innerRequiresNew() {
    jdbc.update("insert into audit(note) values ('self-inner')");
}
```

```text
SCENARIO 同类自调用 REQUIRES_NEW   expected=[]（代理未生效）   actual=[]
```

`this.innerRequiresNew()` 是同一个对象内的普通调用，不经过 Spring 代理，**注解形同虚设**。`REQUIRES_NEW` 想生效，必须跨 Bean 调用（或通过 `TransactionTemplate` 手动开事务）。

### 4.3. readOnly 不等于写保护

两个 readOnly 用例，结果完全不同：

```java
// SelfInvocationService.java
// 作用：readOnly 事务里用 JdbcTemplate 直接写
@Transactional(transactionManager = "jdbcTx", readOnly = true)
public void readOnlyWrite() {
    jdbc.update("insert into audit(note) values ('read-only-write')");
}
```

```text
SCENARIO readOnly + JdbcTemplate 写入   expected=由数据库决定   actual=committed: [read-only-write]
```

用 JdbcTemplate 直写时，本实验环境（H2）**没有拦截，写入成功**。`readOnly` 只是给数据库连接设了个提示性标志，是否真正阻止写入取决于驱动和数据库。

换成 JPA 改实体，则是另一种失败方式——**静默不落盘**：

```java
// ReadOnlyService.java
// 作用：readOnly 事务里改实体，Hibernate 把 FlushMode 设成 MANUAL
@Transactional(readOnly = true)
public void jpaWriteWithoutFlush() {
    Account account = accounts.findById(1L).orElseThrow();
    account.setBalance(999);
}
```

```text
SCENARIO readOnly + JPA 改实体   expected=balance=100（不刷盘）   actual=balance=100
```

方法内改了 `999`，方法返回后查库仍是 `100`。不报错、不异常，只是没写进去。所以 `readOnly` 不能当作「只读保护」，更不能假设它能阻止写操作。

### 4.4. 受检异常默认不回滚

```java
// OuterService.java
// 作用：抛受检异常，验证默认回滚规则
@Transactional(transactionManager = "jdbcTx")
public void checkedException() throws Exception {
    insert("checked");
    throw new Exception("checked-exception");
}
```

```text
SCENARIO 受检异常默认不回滚   expected=[checked]   actual=[checked]
```

Spring 默认只在 `RuntimeException` 和 `Error` 上回滚，受检异常默认**提交**。要让它回滚，必须显式声明 `rollbackFor = Exception.class`。

## 5. 什么时候用哪个

| 场景 | 选哪个 | 理由 |
| --- | --- | --- |
| 常规业务，内外逻辑应该一起成功或一起失败 | `REQUIRED` | 默认值，最符合直觉 |
| 内层失败不能影响外层（如日志、缓存） | `REQUIRES_NEW` | 内层独立提交，外层可回滚 |
| 内层失败要回滚，但外层还想继续 | `NESTED` | 只回滚到 savepoint，外层连接不挂起 |
| 只读方法，事务可有可无 | `SUPPORTS` | 有则加入，没有也不报错 |
| 内层想留审计，且不能被外层回滚带走 | `NOT_SUPPORTED` | 内层非事务提交，不受外层影响 |
| 方法必须在某个事务里调用 | `MANDATORY` | 没有就尽早报错 |
| 方法必须自己管理事务 | `NEVER` | 有外层事务就报错，防止意外加入 |

## 6. 常见坑清单

1. **只 catch 不换传播**：`REQUIRED` 内层异常被 catch，事务仍会被标记 `rollback-only`，提交时抛 `UnexpectedRollbackException`。
2. **同类内自调用**：`@Transactional` 注解不生效，`REQUIRES_NEW`、`readOnly` 都不起作用。需要跨 Bean 调用。
3. **`NESTED` 依赖方言**：`JpaTransactionManager` 下会直接抛 `NestedTransactionNotSupported`，必须换 `DataSourceTransactionManager` 或使用支持 savepoint 的方言。
4. **`readOnly` 不是写保护**：JdbcTemplate 直写可能成功，JPA 改实体可能静默不刷盘。要真正限制，靠数据库权限。
5. **受检异常默认不回滚**：必须 `rollbackFor` 显式声明。
6. **事务管理器混用**：`@Transactional` 不指定 `transactionManager` 时会按 Bean 名/类型选，配置两个管理器时很容易选错，建议显式指定或用 `@Primary` 收敛默认值。

## 7. 重点总结

**7 种传播行为只有两个核心动作：加入已有事务，还是自己开事务。** `REQUIRED`/`MANDATORY` 加入，`REQUIRES_NEW`/`NESTED` 自己开，`SUPPORTS`/`NOT_SUPPORTED`/`NEVER` 决定能否加入。

**实测出来的三条硬结论：**

1. **内层异常被 catch 不会让 `REQUIRED` 提交**——事务被标成 `rollback-only`，提交阶段照样回滚。
2. **`@Transactional` 靠代理生效**，同类自调用会让它完全失效，包括 `REQUIRES_NEW` 和 `readOnly`。
3. **`readOnly` 只设连接标志**，JdbcTemplate 可能写入成功，JPA 可能静默不落盘；受检异常默认不回滚，需要 `rollbackFor`。

真正写事务时，最稳的习惯是：**每个用 `@Transactional` 的方法都显式写清传播行为**，不要依赖默认值；需要跨方法独立提交时，拆成独立的 Bean，不要自调用。

## 8. 参考

- [Spring 事务传播文档](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/annotations.html)
- [Spring `Propagation` 枚举源码](https://github.com/spring-projects/spring-framework/blob/main/spring-tx/src/main/java/org/springframework/transaction/annotation/Propagation.java)
- [`AbstractPlatformTransactionManager` 源码](https://github.com/spring-projects/spring-framework/blob/main/spring-tx/src/main/java/org/springframework/transaction/support/AbstractPlatformTransactionManager.java)（`getDefaultTransactionDefinition`、`isRollbackOnly` 相关逻辑）
- 实测工程：Spring Boot 3.5.7 + JDK 21 + H2（`MODE=MySQL`），`DataSourceTransactionManager` 跑传播用例，`JpaTransactionManager` 跑 readOnly 用例
