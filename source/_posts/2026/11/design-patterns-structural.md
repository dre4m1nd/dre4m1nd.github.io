---
title: 设计模式（二）：结构型 7 种，用 Java 讲清楚
date: 2026-11-06 12:01:00
description: 结构型模式解决“怎么把类/对象拼成一个更大的结构”：适配器、桥接、组合、装饰器、外观、享元、代理。每节给意图、可运行的 Java 代码、什么时候用和坑。
categories:
  - 笔记
tags:
  - 设计模式
  - Java
  - 后端
cover: /img/2026/11/design-patterns-structural.jpg
---

## 1. 前言：结构型管什么

结构型模式只关心一件事：**类或对象怎么拼**。同样是"加功能"，有的模式选择继承，有的选择组合；同样是"简化调用"，有的加一层壳，有的共享一份数据。

一句话记住这一族：**结构型 = 怎么优雅地接起来。**

## 2. 适配器 Adapter

**意图**：把不兼容的接口转成调用方期望的接口。

**代码**：

```java
interface Printer {
    void print(String text);
}

class LegacyPrinter {
    void printText(String text) {
        System.out.println("legacy: " + text);
    }
}

class PrinterAdapter implements Printer {
    private final LegacyPrinter legacy;

    PrinterAdapter(LegacyPrinter legacy) {
        this.legacy = legacy;
    }

    public void print(String text) {
        legacy.printText(text);        // 转一下
    }
}
```

用的时候：

```java
Printer printer = new PrinterAdapter(new LegacyPrinter());
printer.print("report");
```

**什么时候用**：接入老代码/第三方 SDK，不想改调用方，也不想改被接入方。

**坑**：**优先用对象适配（组合），少用类适配（继承）**——Java 单继承，继承方式会锁死父类。

## 3. 桥接 Bridge

**意图**：把"抽象"和"实现"拆成两个独立变化的维度。

**代码**：形状 × 渲染器，两个维度各自扩展：

```java
interface Renderer {
    void drawCircle(int radius);
}

class VectorRenderer implements Renderer {
    public void drawCircle(int radius) {
        System.out.println("vector circle r=" + radius);
    }
}

class RasterRenderer implements Renderer {
    public void drawCircle(int radius) {
        System.out.println("raster circle r=" + radius);
    }
}

abstract class Shape {
    protected final Renderer renderer;

    protected Shape(Renderer renderer) {
        this.renderer = renderer;
    }

    abstract void draw();
}

class Circle extends Shape {
    private final int radius;

    Circle(Renderer renderer, int radius) {
        super(renderer);
        this.radius = radius;
    }

    void draw() {
        renderer.drawCircle(radius);
    }
}
```

用的时候：

```java
Shape a = new Circle(new VectorRenderer(), 5);
Shape b = new Circle(new RasterRenderer(), 5);
a.draw();
b.draw();
```

**什么时候用**：两个维度都在变（形状和渲染方式、消息类型和发送渠道），用继承会变成 M×N 个类。

**坑**：只有一个维度在变时，桥接是过度设计。

## 4. 组合 Composite

**意图**：把"单个对象"和"对象组合"当同一种东西处理（树形结构）。

**代码**：

```java
import java.util.ArrayList;
import java.util.List;

interface Node {
    long size();
}

class FileNode implements Node {
    private final long bytes;

    FileNode(long bytes) {
        this.bytes = bytes;
    }

    public long size() {
        return bytes;
    }
}

class DirNode implements Node {
    private final List<Node> children = new ArrayList<>();

    DirNode add(Node node) {
        children.add(node);
        return this;
    }

    public long size() {
        long total = 0;
        for (Node child : children) {
            total += child.size();          // 递归，不用判断类型
        }
        return total;
    }
}
```

用的时候：

```java
DirNode root = new DirNode();
root.add(new FileNode(100)).add(new DirNode().add(new FileNode(50)));
System.out.println(root.size());          // 150
```

**什么时候用**：树形数据（文件系统、组织架构、UI 组件树），调用方不想区分"叶子"和"容器"。

**坑**：递归深度大时会栈溢出；叶子节点上不该出现的 `add/remove` 要么抛异常，要么拆接口。

## 5. 装饰器 Decorator

**意图**：不改变原对象的前提下，动态叠加功能。

**代码**：

```java
interface Coffee {
    double cost();

    String desc();
}

class Espresso implements Coffee {
    public double cost() {
        return 2.0;
    }

    public String desc() {
        return "espresso";
    }
}

abstract class CoffeeDecorator implements Coffee {
    protected final Coffee inner;

    protected CoffeeDecorator(Coffee inner) {
        this.inner = inner;
    }
}

class Milk extends CoffeeDecorator {
    Milk(Coffee inner) {
        super(inner);
    }

    public double cost() {
        return inner.cost() + 0.5;
    }

    public String desc() {
        return inner.desc() + " + milk";
    }
}

class Sugar extends CoffeeDecorator {
    Sugar(Coffee inner) {
        super(inner);
    }

    public double cost() {
        return inner.cost() + 0.2;
    }

    public String desc() {
        return inner.desc() + " + sugar";
    }
}
```

用的时候：

```java
Coffee coffee = new Sugar(new Milk(new Espresso()));
System.out.println(coffee.desc() + " = " + coffee.cost());
```

**什么时候用**：功能可以自由组合、不该用继承堆子类。Java 里最典型的实现就是 `java.io.InputStream` 那一串（`BufferedInputStream(new FileInputStream(...))`）。

**坑**：装饰器包多了调试难（栈很深）；每个装饰器都要实现同一个接口，接口一改全要改。

## 6. 外观 Facade

**意图**：给复杂子系统一个简单入口。

**代码**：

```java
class Inventory {
    void reserve(String sku) {
        System.out.println("reserve " + sku);
    }
}

class Payment {
    void charge(String user, double amount) {
        System.out.println("charge " + amount + " for " + user);
    }
}

class Shipping {
    void ship(String sku) {
        System.out.println("ship " + sku);
    }
}

class OrderFacade {
    private final Inventory inventory = new Inventory();
    private final Payment payment = new Payment();
    private final Shipping shipping = new Shipping();

    void placeOrder(String user, String sku, double amount) {
        inventory.reserve(sku);
        payment.charge(user, amount);
        shipping.ship(sku);
    }
}
```

用的时候：

```java
new OrderFacade().placeOrder("alice", "SKU-1", 99.0);
```

**什么时候用**：一次业务流程要调好几个子系统，调用方不想知道顺序和细节。

**坑**：外观会变成"什么都往里塞"的上帝类——它只该做**编排**，别把业务逻辑也写进去。

## 7. 享元 Flyweight

**意图**：共享大量细粒度对象的"不变部分"，节省内存。

**代码**：文档里的字符——字符+字体是可共享的内部状态，位置是外部状态：

```java
import java.util.HashMap;
import java.util.Map;

final class Glyph {
    private final char ch;
    private final String font;

    Glyph(char ch, String font) {
        this.ch = ch;
        this.font = font;
    }

    void draw(int x, int y) {                // 位置从外部传进来
        System.out.println("draw " + ch + " at " + x + "," + y + " font=" + font);
    }
}

final class GlyphFactory {
    private final Map<String, Glyph> pool = new HashMap<>();

    Glyph get(char ch, String font) {
        String key = ch + "@" + font;
        return pool.computeIfAbsent(key, k -> new Glyph(ch, font));
    }

    int size() {
        return pool.size();
    }
}
```

用的时候：

```java
GlyphFactory factory = new GlyphFactory();
factory.get('A', "sans").draw(0, 0);
factory.get('A', "sans").draw(10, 20);
System.out.println("pool size = " + factory.size());   // 1
```

**什么时候用**：大量重复的、可共享的小对象，且能明确区分"内部状态"和"外部状态"。

**坑**：把外部状态塞进享元就失去意义；池子不清理会变成内存泄漏（尤其是键不可控时）。

## 8. 代理 Proxy

**意图**：给对象加一层"访问控制"，调用方感觉不到差别。

**代码**：静态代理 + JDK 动态代理两种：

```java
interface Service {
    String work(String input);
}

class RealService implements Service {
    public String work(String input) {
        return "done:" + input;
    }
}

// 静态代理：手写一个同接口的类
class LoggingProxy implements Service {
    private final Service target;

    LoggingProxy(Service target) {
        this.target = target;
    }

    public String work(String input) {
        System.out.println("before " + input);
        String out = target.work(input);
        System.out.println("after " + out);
        return out;
    }
}
```

动态代理（运行时生成，不用为每个接口手写）：

```java
import java.lang.reflect.Proxy;

Service target = new RealService();
Service proxy = (Service) Proxy.newProxyInstance(
        Service.class.getClassLoader(),
        new Class<?>[]{Service.class},
        (p, method, args) -> {
            System.out.println("dyn before " + method.getName());
            return method.invoke(target, args);
        });
proxy.work("x");
```

**什么时候用**：懒加载、权限检查、日志、事务、远程调用——**不加到业务代码里**的横切逻辑。

**坑**：JDK 动态代理只能代理接口（类要用 CGLIB/ByteBuddy）；代理里吞异常会让调用方以为成功；自调用（`this.method()`）会绕过代理。

## 9. 选型表

| 你要解决的事 | 用 |
| --- | --- |
| 接口对不上，要转一层 | 适配器 |
| 两个维度都在变 | 桥接 |
| 树形结构，叶子容器一视同仁 | 组合 |
| 功能要动态叠加 | 装饰器 |
| 给一堆子系统一个简单入口 | 外观 |
| 大量重复小对象，内存吃紧 | 享元 |
| 加访问控制/横切逻辑 | 代理 |

## 10. 参考

- GoF《设计模式：可复用面向对象软件的基础》
- `java.lang.reflect.Proxy`、`java.lang.reflect.InvocationHandler`
- `java.io` 装饰器家族（`BufferedInputStream` 等）
</content>
