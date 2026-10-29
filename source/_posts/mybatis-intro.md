---
title: MyBatis 入门到进阶：从 XML 到 MyBatis-Plus
date: 2026-10-29 14:45:00
description: MyBatis 是 Java 半自动持久层框架，SQL 握在自己手里、映射交给框架。这篇覆盖 Spring Boot 接入、Mapper 接口与 XML、#{} 与 ${}、动态 SQL、resultMap 关联映射、缓存、插件，以及 MyBatis-Plus 的 BaseMapper/条件构造器/分页插件与常见坑。
categories:
  - 技术
tags:
  - Java
  - MyBatis
  - MyBatis-Plus
  - 后端
cover: /img/cover-mybatis.jpg
---

## MyBatis 是什么

MyBatis 是 Java 生态里最主流的**半自动持久层框架**：它不替你生成 SQL，而是让你**自己写 SQL，它负责把参数填进去、把结果映射成对象**。相比 Hibernate / JPA 那种"全自动 ORM"（连 SQL 都帮你生成），MyBatis 的取舍是——**把 SQL 的控制权还给你**。

| | JPA / Hibernate | MyBatis |
| --- | --- | --- |
| SQL | 框架生成（HQL/JPQL） | **自己写** |
| 上手 | 快（注解就能 CRUD） | 稍慢（要写 Mapper） |
| 复杂 SQL | 难调、易 N+1 | **手到擒来** |
| 学习曲线 | 概念多（一级/二级缓存、脏检查） | 概念少、贴近 SQL |
| 适合 | 简单 CRUD、快速原型 | 报表、多表关联、性能敏感 |

核心概念：`SqlSessionFactory`（工厂）→ `SqlSession`（会话）→ `Mapper`（接口，由框架代理实现）。

## 入门

### 1. Spring Boot 接入

```xml
<dependency>
  <groupId>org.mybatis.spring.boot</groupId>
  <artifactId>mybatis-spring-boot-starter</artifactId>
  <version>3.0.3</version>
</dependency>
```

```yaml
# application.yml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/demo?useSSL=false&serverTimezone=UTC
    username: root
    password: root
mybatis:
  mapper-locations: classpath:mapper/**/*.xml   # XML 位置
  type-aliases-package: com.example.demo.entity  # 实体别名
  configuration:
    map-underscore-to-camel-case: true          # 下划线列自动转驼峰字段
    log-impl: org.apache.ibatis.logging.stdout.StdOutImpl  # 打印 SQL，调试神器
```

在启动类上扫 Mapper 接口：

```java
@SpringBootApplication
@MapperScan("com.example.demo.mapper")   // 或每个接口加 @Mapper
public class DemoApplication { public static void main(String[] a) { SpringApplication.run(DemoApplication.class, a); } }
```

### 2. 实体与 Mapper 接口

```java
public class User {
    private Long id;
    private String userName;     // 对应列 user_name
    private Integer age;
    // getter / setter 省略
}

public interface UserMapper {
    User selectById(Long id);
    List<User> selectAll();
    int insert(User user);
    int updateById(User user);
    int deleteById(Long id);
}
```

### 3. Mapper XML

```xml
<!-- resources/mapper/UserMapper.xml -->
<mapper namespace="com.example.demo.mapper.UserMapper">
    <select id="selectById" resultType="User">
        SELECT id, user_name, age FROM user WHERE id = #{id}
    </select>

    <select id="selectAll" resultType="User">
        SELECT id, user_name, age FROM user
    </select>

    <insert id="insert" useGeneratedKeys="true" keyProperty="id">
        INSERT INTO user (user_name, age) VALUES (#{userName}, #{age})
    </insert>

    <update id="updateById">
        UPDATE user SET user_name = #{userName}, age = #{age} WHERE id = #{id}
    </update>

    <delete id="deleteById">
        DELETE FROM user WHERE id = #{id}
    </delete>
</mapper>
```

要点：
- `namespace` **必须等于 Mapper 接口全限定名**，否则找不到
- `id` **必须等于方法名**
- `resultType` 用别名 `User`（来自 `type-aliases-package`）；列名→字段靠 `map-underscore-to-camel-case`
- `#{userName}` 是预编译占位符，**防 SQL 注入**

调用：

```java
@Autowired UserMapper userMapper;
User u = userMapper.selectById(1L);
```

### 4. 参数与 @Param

多个参数、或想给参数命名时加 `@Param`：

```java
List<User> selectByAgeAndName(@Param("age") Integer age, @Param("name") String name);
```

```xml
<select id="selectByAgeAndName" resultType="User">
  SELECT * FROM user WHERE age = #{age} AND user_name LIKE #{name}
</select>
```

不加 `@Param` 时 XML 里只能用 `param1` / `param2` 引用，可读性差，建议都加。

## 进阶

### 5. 动态 SQL

真实业务里 SQL 条件是可变的，MyBatis 用标签拼装：

```xml
<select id="search" resultType="User">
  SELECT id, user_name, age FROM user
  <where>
    <if test="name != null and name != ''">
      AND user_name LIKE CONCAT('%', #{name}, '%')
    </if>
    <if test="minAge != null">
      AND age &gt;= #{minAge}
    </if>
    <if test="maxAge != null">
      AND age &lt;= #{maxAge}
    </if>
  </where>
  <choose>
    <when test="sort == 'age'">ORDER BY age DESC</when>
    <otherwise>ORDER BY id DESC</otherwise>
  </choose>
</select>
```

- `<where>` 会自动去掉首尾多余的 `AND` / `OR`
- `<set>` 用于 UPDATE，自动去掉末尾逗号
- `<foreach>` 用于 `IN` 查询：`collection="ids" item="id" open="(" separator="," close=")"`
- `>` `<` `&` 在 XML 里要转义，或用 `<![CDATA[ age >= #{minAge} ]]>`

### 6. resultMap：解决列字段不一致 & 关联

当自动映射不够用时，手写 `resultMap`：

```xml
<resultMap id="UserMap" type="User">
  <id column="id" property="id"/>
  <result column="user_name" property="userName"/>
  <result column="age" property="age"/>
</resultMap>

<select id="selectById" resultMap="UserMap">
  SELECT id, user_name, age FROM user WHERE id = #{id}
</select>
```

一对多 / 一对一：

```xml
<resultMap id="UserWithPosts" type="User">
  <id column="id" property="id"/>
  <collection property="posts" ofType="Post">
    <id column="pid" property="id"/>
    <result column="title" property="title"/>
  </collection>
</resultMap>
```

`association` 一对一、`collection` 一对多。注意列名冲突时给别名（如 `pid`）。

### 7. 主键回写

```xml
<insert id="insert" useGeneratedKeys="true" keyProperty="id">
  INSERT INTO user (user_name, age) VALUES (#{userName}, #{age})
</insert>
```

插入后 `user.getId()` 就有值了。MySQL 自增靠 `useGeneratedKeys`；Oracle 序列用 `<selectKey>`。

### 8. #{} 与 ${} —— 安全红线

| | `#{}` | `${}` |
| --- | --- | --- |
| 处理 | 预编译占位符 `?` | 字符串直接拼接 |
| SQL 注入 | **安全** | **有风险** |
| 用途 | 几乎所有值 | 表名、排序字段等动态标识符 |

```xml
<!-- ✅ 正确：值用 #{} -->
WHERE user_name = #{name}

<!-- ❌ 危险：用户输入拼进 ${} 会被注入 -->
WHERE user_name = '${name}'

<!-- ✅ ${} 仅用于排序字段（值来自白名单） -->
ORDER BY ${safeColumn}
```

**原则：值一律用 `#{}`；只有排序字段、表名这类"标识符"才用 `${}`，且必须白名单校验。**

### 9. 缓存

- **一级缓存**：默认开，作用域是 `SqlSession`（一次会话）。同一个 SqlSession 内重复查同条件会命中。Spring 里每次 mapper 调用可能是新会话，一级缓存基本不跨调用
- **二级缓存**：按 `namespace` 共享，需显式开：

```xml
<cache/>   <!-- 在 Mapper XML 里，实体要实现 Serializable -->
```

二级缓存要小心：多表更新、分布式部署下容易读到旧数据，生产常配合 Redis，而不是用 MyBatis 自带二级缓存。

### 10. 插件 / 拦截器

MyBatis 的插件基于拦截 `Executor` / `StatementHandler` 等。分页经典做法是拦截器（如 PageHelper 或下面的 MyBatis-Plus 分页插件）。自定义插件用 `@Intercepts`：

```java
@Intercepts({@Signature(type = Executor.class, method = "update", args = {MappedStatement.class, Object.class})})
public class MyPlugin implements Interceptor { /* ... */ }
```

### 11. 事务

交给 Spring：

```java
@Transactional
public void transfer(Long from, Long to, BigDecimal amount) {
    accountMapper.debit(from, amount);
    accountMapper.credit(to, amount);   // 抛异常自动回滚
}
```

注意：MyBatis 的 `SqlSession` 由 Spring 管理，方法结束才提交；别在方法里自己吞异常导致不回滚。

## MyBatis-Plus：不用写 XML 的增强

绝大多数新项目直接用 **MyBatis-Plus（MP）**——它在 MyBatis 之上加了通用 CRUD 和条件构造器，能省掉大量模板 SQL。

### 12. BaseMapper 内置 CRUD

```java
@TableName("user")                    // 表名与类名不一致时指定
public class User {
    @TableId(type = IdType.AUTO)     // 主键自增
    private Long id;
    private String userName;
    private Integer age;
}

public interface UserMapper extends BaseMapper<User> {}   // 白送 CRUD
```

```java
userMapper.insert(user);
User u = userMapper.selectById(1L);
userMapper.updateById(user);
userMapper.deleteById(1L);
userMapper.selectList(null);          // 查全部
```

字段名和列名不一致用 `@TableField("user_name")`。

### 13. 条件构造器

```java
// QueryWrapper
List<User> list = userMapper.selectList(
    new QueryWrapper<User>().gt("age", 18).like("user_name", "a").orderByDesc("id"));

// LambdaQueryWrapper：用方法引用，字段改名也不怕字符串拼错
LambdaQueryWrapper<User> q = new LambdaQueryWrapper<User>()
    .gt(User::getAge, 18)
    .like(User::getUserName, "a");
List<User> list2 = userMapper.selectList(q);
```

### 14. IService 业务层

```java
public interface UserService extends IService<User> {}
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements UserService {}

@Autowired UserService userService;
userService.save(user);
userService.page(new Page<>(1, 10), q);   // 分页
```

### 15. 分页插件

MP 的分页**必须注册插件**才会自动加 `LIMIT`：

```java
@Configuration
public class MybatisPlusConfig {
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        // 注意：较新版本 PaginationInnerInterceptor 已拆分到 mybatis-plus-jsqlparser 模块
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        return interceptor;
    }
}
```

```java
Page<User> page = new Page<>(1, 10);                 // 第 1 页，每页 10
userMapper.selectPage(page, new LambdaQueryWrapper<User>().gt(User::getAge, 18));
page.getRecords();   // 数据
page.getTotal();     // 总数
```

## MyBatis vs JPA 选型

- **选 MyBatis / MP**：SQL 复杂、报表多、要精细性能调优、团队 SQL 强、接老库
- **选 JPA**：业务以简单 CRUD 为主、想少写 SQL、原型阶段求快

实际项目里 MP 用得最多：既保留写 SQL 的自由，又省掉重复 CRUD。

## 常见坑清单

- Mapper XML 的 `namespace` 必须和接口**全限定名**一致，`id` 必须和方法名一致，否则启动报 `Invalid bound statement`
- 列名 `user_name` 映射到字段 `userName` 要开 `map-underscore-to-camel-case`，或手写 `resultMap`
- **值一律用 `#{}`**，只有排序/表名这类标识符才用 `${}`，且必须白名单
- XML 里 `<` `>` `&` 要转义或放 `<![CDATA[ ]]>`，否则 XML 解析报错
- 多参数不加 `@Param` 时，XML 只能用 `param1/param2`，可读性差
- `selectOne` 查到多条会抛 `TooManyResultsException`，不是返回 list
- 自增主键回写要 `useGeneratedKeys="true" keyProperty="id"`，否则 `getId()` 为 null
- MP 分页**必须注册 `MybatisPlusInterceptor` + `PaginationInnerInterceptor`**，否则只是普通查询不分页
- MP 表名/字段名不一致用 `@TableName` / `@TableField`，不然拼错表
- 一级缓存只在同一个 SqlSession 内有效，Spring 下别指望它跨请求命中
- 实体类要序列化（实现 `Serializable`）才用二级缓存，且分布式下慎用自带二级缓存
- 事务里别吞异常，否则 `@Transactional` 不回滚

## 参考

- [MyBatis 官方文档](https://mybatis.org/mybatis-3/zh/index.html)
- [mybatis-spring-boot-starter](https://github.com/mybatis/spring-boot-starter)
- [MyBatis-Plus 文档](https://baomidou.com/)
- [MyBatis-Plus 分页插件](https://baomidou.com/plugins/pagination/)
