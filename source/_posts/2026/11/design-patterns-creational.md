---
title: 设计模式（一）：创建型 5 种，用 Java 讲清楚
date: 2026-11-06 12:00:00
description: 创建型模式解决“怎么造对象”：单例、工厂方法、抽象工厂、建造者、原型。每节给意图、可运行的 Java 代码、什么时候用和坑，最后一张选型表。
categories:
  - 笔记
tags:
  - 设计模式
  - Java
  - 后端
cover: /img/2026/11/design-patterns-creational.jpg
---

## 1. 前言：创建型管什么

设计模式按目的分三类，这篇讲**创建型**。创建型只关心一件事：**对象怎么造出来**。它把"new 哪个类、怎么初始化"从调用方手里拿走，调用方只要说"我要一个通知器"，不用关心是邮件还是短信。

一句话记住这一族：**创建型 = 把 `new` 关进盒子里。**

## 2. 单例 Singleton

**意图**：一个类只有一个实例，并提供全局访问点。

**代码**：枚举写法最稳（防反射、防反序列化破坏）：

```java
enum Config {
    INSTANCE;

    private final String dbUrl = "jdbc:postgresql://localhost/app";

    String dbUrl() {
        return dbUrl;
    }
}
```

用的时候：`Config.INSTANCE.dbUrl()`。

需要懒加载时，双检锁写法长这样（面试常问）：

```java
final class LazyConfig {
    private static volatile LazyConfig instance;   // volatile 不能省

    private LazyConfig() {}

    static LazyConfig getInstance() {
        if (instance == null) {
            synchronized (LazyConfig.class) {
                if (instance == null) {
                    instance = new LazyConfig();
                }
            }
        }
        return instance;
    }
}
```

**什么时候用**：配置中心、连接池、日志器这类"全进程一份"的东西。

**坑**：`clone()`、反射、反序列化都能造出第二个实例，枚举写法天然免疫；双检锁忘了 `volatile`，会因指令重排拿到"构造到一半"的对象。

## 3. 工厂方法 Factory Method

**意图**：定义创建对象的接口，让子类决定实例化哪个类。

**代码**：

```java
interface Notifier {
    void send(String msg);
}

class EmailNotifier implements Notifier {
    public void send(String msg) {
        System.out.println("EMAIL " + msg);
    }
}

class SmsNotifier implements Notifier {
    public void send(String msg) {
        System.out.println("SMS " + msg);
    }
}

abstract class NotifierFactory {
    abstract Notifier create();                       // 由子类决定造谁

    void notify(String msg) {
        create().send(msg);                           // 公共流程写在父类
    }
}

class EmailFactory extends NotifierFactory {
    Notifier create() {
        return new EmailNotifier();
    }
}

class SmsFactory extends NotifierFactory {
    Notifier create() {
        return new SmsNotifier();
    }
}
```

用的时候：

```java
NotifierFactory factory = new SmsFactory();
factory.notify("hello");
```

**什么时候用**：创建逻辑有分支、或者想给子类/插件留扩展点。

**坑**：类会膨胀；产品只有一种、短期不会变时，直接 `new` 更清楚，别硬上。

## 4. 抽象工厂 Abstract Factory

**意图**：创建"一族"相关对象，而不指定具体类。

**代码**：跨平台 UI，按钮和复选框必须来自同一套主题：

```java
interface Button {
    void paint();
}

interface Checkbox {
    void paint();
}

interface GuiFactory {
    Button button();
    Checkbox checkbox();
}

class MacButton implements Button {
    public void paint() {
        System.out.println("mac button");
    }
}

class MacCheckbox implements Checkbox {
    public void paint() {
        System.out.println("mac checkbox");
    }
}

class MacFactory implements GuiFactory {
    public Button button() {
        return new MacButton();
    }

    public Checkbox checkbox() {
        return new MacCheckbox();
    }
}

class WinButton implements Button {
    public void paint() {
        System.out.println("win button");
    }
}

class WinCheckbox implements Checkbox {
    public void paint() {
        System.out.println("win checkbox");
    }
}

class WinFactory implements GuiFactory {
    public Button button() {
        return new WinButton();
    }

    public Checkbox checkbox() {
        return new WinCheckbox();
    }
}
```

用的时候：

```java
GuiFactory ui = new MacFactory();
ui.button().paint();
ui.checkbox().paint();
```

**什么时候用**：要保证"同一族"的产品配套使用——一套 UI 组件、一套数据库驱动。

**坑**：加一种新产品（比如 Slider）要改所有工厂接口。抽象工厂对"新增产品族"友好，对"新增产品种类"不友好。

## 5. 建造者 Builder

**意图**：分步构造复杂对象，最终对象不可变。

**代码**：

```java
import java.util.LinkedHashMap;
import java.util.Map;

final class HttpRequest {
    private final String url;
    private final String method;
    private final Map<String, String> headers;

    private HttpRequest(Builder b) {
        this.url = b.url;
        this.method = b.method;
        this.headers = Map.copyOf(b.headers);          // 防御性拷贝，外部改不到
    }

    static Builder builder(String url) {
        return new Builder(url);
    }

    public String toString() {
        return method + " " + url + " " + headers;
    }

    static final class Builder {
        private final String url;
        private String method = "GET";
        private final Map<String, String> headers = new LinkedHashMap<>();

        private Builder(String url) {
            this.url = url;
        }

        Builder method(String m) {
            this.method = m;
            return this;
        }

        Builder header(String k, String v) {
            headers.put(k, v);
            return this;
        }

        HttpRequest build() {
            return new HttpRequest(this);
        }
    }
}
```

用的时候：

```java
HttpRequest req = HttpRequest.builder("https://api.example.com/users")
        .method("POST")
        .header("Content-Type", "application/json")
        .build();
System.out.println(req);
```

**什么时候用**：参数多、可选参数多、想保证构造完成后不可变。

**坑**：参数就两三个时别上 builder；Lombok `@Builder` 省样板，但和继承、必填校验容易打架。

## 6. 原型 Prototype

**意图**：用"复制现有对象"代替"重新 new + 初始化"。

**代码**：

```java
interface Shape {
    Shape copy();

    void draw();
}

final class Circle implements Shape {
    private final int radius;

    Circle(int radius) {
        this.radius = radius;
    }

    public Shape copy() {
        return new Circle(radius);       // 拷贝构造
    }

    public void draw() {
        System.out.println("circle r=" + radius);
    }
}

final class Rect implements Shape {
    private final int w;
    private final int h;

    Rect(int w, int h) {
        this.w = w;
        this.h = h;
    }

    public Shape copy() {
        return new Rect(w, h);
    }

    public void draw() {
        System.out.println("rect " + w + "x" + h);
    }
}
```

用的时候：

```java
Shape proto = new Circle(10);
Shape copy = proto.copy();
copy.draw();
```

**什么时候用**：对象初始化很贵（查库、算配置），或者想从"样板实例"派生一批对象。

**坑**：`Object.clone()` 是**浅拷贝**，集合和引用字段要自己深拷；`Cloneable` 只是标记接口，不实现它又调 `clone()` 会抛 `CloneNotSupportedException`。所以现代 Java 更推荐**拷贝构造**或 `record`。

## 7. 选型表

| 你要解决的事 | 用 |
| --- | --- |
| 全进程就一个实例 | 单例（优先枚举） |
| 造哪个类由子类/配置决定 | 工厂方法 |
| 一族产品必须配套 | 抽象工厂 |
| 参数多、要分步构建、要不可变 | 建造者 |
| 复制现成对象更便宜 | 原型（拷贝构造） |

## 8. 参考

- GoF《设计模式：可复用面向对象软件的基础》
- `java.util.Map#copyOf`、`java.lang.Cloneable`（Java 21 API 文档）
</content>
