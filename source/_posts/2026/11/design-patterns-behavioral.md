---
title: 设计模式（三）：行为型 11 种，用 Java 讲清楚
date: 2026-11-06 12:02:00
description: 行为型模式解决“对象之间怎么分工协作”：责任链、命令、解释器、迭代器、中介者、备忘录、观察者、状态、策略、模板方法、访问者。每节给意图、可运行的 Java 代码、什么时候用和坑。
categories:
  - 笔记
tags:
  - 设计模式
  - Java
  - 后端
cover: /img/2026/11/design-patterns-behavioral.jpg
---

## 1. 前言：行为型管什么

行为型模式只关心一件事：**对象之间怎么分工、怎么通信**。同样是"处理一个请求"，可以让对象排队传下去（责任链），也可以让状态自己决定行为（状态）；同样是"通知变化"，可以推送（观察者），也可以拉取（迭代器）。

一句话记住这一族：**行为型 = 谁在什么时候做什么。**

## 2. 责任链 Chain of Responsibility

**意图**：让多个处理者依次尝试处理请求，调用方不知道是谁处理的。

**代码**：

```java
abstract class Approver {
    protected Approver next;

    Approver setNext(Approver next) {
        this.next = next;
        return next;
    }

    void approve(int amount) {
        if (canApprove(amount)) {
            System.out.println(getClass().getSimpleName() + " approved " + amount);
        } else if (next != null) {
            next.approve(amount);
        } else {
            System.out.println("rejected " + amount);
        }
    }

    protected abstract boolean canApprove(int amount);
}

class Manager extends Approver {
    protected boolean canApprove(int amount) {
        return amount <= 1000;
    }
}

class Director extends Approver {
    protected boolean canApprove(int amount) {
        return amount <= 5000;
    }
}
```

用的时候：

```java
Approver manager = new Manager();
manager.setNext(new Director());
manager.approve(3000);
```

**什么时候用**：审批流、过滤器、异常处理链。

**坑**：链没接好会静默走到 `else` 分支（或者 NPE）；链太长时排查"到底谁处理的"很痛苦。

## 3. 命令 Command

**意图**：把"请求"封装成对象，于是请求可以排队、记录、撤销。

**代码**：

```java
import java.util.ArrayDeque;
import java.util.Deque;

interface Command {
    void execute();

    void undo();
}

class Light {
    private boolean on;

    void turnOn() {
        on = true;
        System.out.println("light on");
    }

    void turnOff() {
        on = false;
        System.out.println("light off");
    }
}

class LightOnCommand implements Command {
    private final Light light;

    LightOnCommand(Light light) {
        this.light = light;
    }

    public void execute() {
        light.turnOn();
    }

    public void undo() {
        light.turnOff();
    }
}

class Remote {
    private final Deque<Command> history = new ArrayDeque<>();

    void press(Command command) {
        command.execute();
        history.push(command);
    }

    void undo() {
        if (!history.isEmpty()) {
            history.pop().undo();
        }
    }
}
```

用的时候：

```java
Remote remote = new Remote();
remote.press(new LightOnCommand(new Light()));
remote.undo();
```

**什么时候用**：撤销/重做、任务队列、宏命令（一串命令当一个命令）。

**坑**：每个命令都要支持 `undo`，状态恢复不干净就会撤销出错。

## 4. 解释器 Interpreter

**意图**：给一门小语言定义语法，并用对象树解释它。

**代码**：只有数字、加法、乘法的表达式：

```java
import java.util.Map;

interface Expression {
    int interpret(Map<String, Integer> ctx);
}

record Num(int value) implements Expression {
    public int interpret(Map<String, Integer> ctx) {
        return value;
    }
}

record Add(Expression left, Expression right) implements Expression {
    public int interpret(Map<String, Integer> ctx) {
        return left.interpret(ctx) + right.interpret(ctx);
    }
}

record Mul(Expression left, Expression right) implements Expression {
    public int interpret(Map<String, Integer> ctx) {
        return left.interpret(ctx) * right.interpret(ctx);
    }
}
```

用的时候：

```java
Expression expr = new Add(new Num(2), new Mul(new Num(3), new Num(4)));
System.out.println(expr.interpret(Map.of()));     // 14
```

**什么时候用**：规则表达式、SQL 子集、配置 DSL。**语法简单**时才有意义。

**坑**：语法一复杂就变成"手写编译器"，性能和可维护性都不划算——那种情况直接用 ANTLR 之类。

## 5. 迭代器 Iterator

**意图**：不暴露内部结构地遍历集合。

**代码**：

```java
import java.util.Iterator;

class Range implements Iterable<Integer> {
    private final int start;
    private final int end;

    Range(int start, int end) {
        this.start = start;
        this.end = end;
    }

    public Iterator<Integer> iterator() {
        return new Iterator<>() {
            private int cur = start;

            public boolean hasNext() {
                return cur < end;
            }

            public Integer next() {
                return cur++;
            }
        };
    }
}
```

用的时候：

```java
for (int n : new Range(1, 4)) {
    System.out.println(n);      // 1 2 3
}
```

**什么时候用**：自定义集合、需要多种遍历方式、要隐藏内部存储。

**坑**：遍历过程中修改集合会 `ConcurrentModificationException`；`next()` 要按约定抛 `NoSuchElementException`。

## 6. 中介者 Mediator

**意图**：对象之间不直接通信，都交给中介者转发。

**代码**：

```java
import java.util.ArrayList;
import java.util.List;

class ChatRoom {
    private final List<User> users = new ArrayList<>();

    void join(User user) {
        users.add(user);
    }

    void send(User from, String msg) {
        for (User user : users) {
            if (user != from) {
                user.receive(from.name + ": " + msg);
            }
        }
    }
}

class User {
    final String name;
    private final ChatRoom room;

    User(String name, ChatRoom room) {
        this.name = name;
        this.room = room;
        room.join(this);
    }

    void send(String msg) {
        room.send(this, msg);
    }

    void receive(String msg) {
        System.out.println(name + " <- " + msg);
    }
}
```

用的时候：

```java
ChatRoom room = new ChatRoom();
User alice = new User("alice", room);
User bob = new User("bob", room);
alice.send("hi");
```

**什么时候用**：多个对象互相依赖、通信关系网状（聊天室、控件对话框、消息总线）。

**坑**：中介者会变成"什么都管"的上帝对象；只在一对一通信时用它是加戏。

## 7. 备忘录 Memento

**意图**：在不破坏封装的前提下，保存/恢复对象状态。

**代码**：

```java
final class Editor {
    private String text = "";

    void type(String s) {
        text += s;
    }

    Snapshot save() {
        return new Snapshot(text);
    }

    void restore(Snapshot snapshot) {
        text = snapshot.text();
    }

    String text() {
        return text;
    }

    record Snapshot(String text) { }        // 不可变快照
}
```

用的时候：

```java
Editor editor = new Editor();
editor.type("hello");
Editor.Snapshot snap = editor.save();
editor.type(" world");
System.out.println(editor.text());      // hello world
editor.restore(snap);
System.out.println(editor.text());      // hello
```

**什么时候用**：撤销、事务回滚、游戏存档。

**坑**：快照太大很吃内存，通常配合"只存差异"或限制撤销层数。

## 8. 观察者 Observer

**意图**：状态变化时通知所有订阅者，发布者和订阅者互不依赖。

**代码**：

```java
import java.util.ArrayList;
import java.util.List;

interface Listener {
    void onEvent(String event);
}

class EventBus {
    private final List<Listener> listeners = new ArrayList<>();

    void subscribe(Listener listener) {
        listeners.add(listener);
    }

    void publish(String event) {
        for (Listener listener : listeners) {
            listener.onEvent(event);
        }
    }
}
```

用的时候（`Listener` 是函数式接口，直接传 lambda）：

```java
EventBus bus = new EventBus();
bus.subscribe(e -> System.out.println("A got " + e));
bus.subscribe(e -> System.out.println("B got " + e));
bus.publish("order.created");
```

**什么时候用**：事件驱动、MVC 里的监听器、领域事件。

**坑**：一个订阅者抛异常会中断后面的通知（要么 try/catch 每个，要么异步发）；忘了退订会内存泄漏。

## 9. 状态 State

**意图**：对象行为随内部状态改变，且状态转换由状态自己驱动。

**代码**：

```java
interface OrderState {
    void pay(Order order);

    void ship(Order order);
}

class Order {
    private OrderState state = new Created();

    void setState(OrderState state) {
        this.state = state;
    }

    void pay() {
        state.pay(this);
    }

    void ship() {
        state.ship(this);
    }
}

class Created implements OrderState {
    public void pay(Order order) {
        System.out.println("paid");
        order.setState(new Paid());
    }

    public void ship(Order order) {
        throw new IllegalStateException("pay first");
    }
}

class Paid implements OrderState {
    public void pay(Order order) {
        throw new IllegalStateException("already paid");
    }

    public void ship(Order order) {
        System.out.println("shipped");
        order.setState(new Shipped());
    }
}

class Shipped implements OrderState {
    public void pay(Order order) {
        throw new IllegalStateException("already shipped");
    }

    public void ship(Order order) {
        throw new IllegalStateException("already shipped");
    }
}
```

用的时候：

```java
Order order = new Order();
order.pay();
order.ship();
```

**什么时候用**：状态多、状态转换规则复杂（订单、工单、连接状态机）。

**坑**：**状态 vs 策略**最容易混——策略是"调用方选算法"，状态是"状态自己触发转移"；状态类一多要考虑用枚举 + `switch` 简化。

## 10. 策略 Strategy

**意图**：把可替换的算法封装起来，运行时切换。

**代码**：

```java
import java.math.BigDecimal;

interface PricingStrategy {
    BigDecimal price(BigDecimal base);
}

class NormalPricing implements PricingStrategy {
    public BigDecimal price(BigDecimal base) {
        return base;
    }
}

class VipPricing implements PricingStrategy {
    public BigDecimal price(BigDecimal base) {
        return base.multiply(new BigDecimal("0.8"));
    }
}

class Cart {
    private PricingStrategy strategy = new NormalPricing();

    void setStrategy(PricingStrategy strategy) {
        this.strategy = strategy;
    }

    BigDecimal total(BigDecimal base) {
        return strategy.price(base);
    }
}
```

用的时候：

```java
Cart cart = new Cart();
System.out.println(cart.total(new BigDecimal("100")));   // 100
cart.setStrategy(new VipPricing());
System.out.println(cart.total(new BigDecimal("100")));   // 80.0
```

**什么时候用**：支付方式、计价规则、排序算法、压缩算法。

**坑**：策略类一多，`if/else` 会变成 `Map<String, Strategy>` 的注册表——注册表要有人维护默认值。

## 11. 模板方法 Template Method

**意图**：父类定流程骨架，子类只填可变步骤。

**代码**：

```java
abstract class DataImporter {
    public final void run() {          // final：骨架不许子类改
        open();
        parse();
        save();
        close();
    }

    protected abstract void open();

    protected abstract void parse();

    protected void save() {
        System.out.println("save default");
    }

    protected void close() {
        System.out.println("close");
    }
}

class CsvImporter extends DataImporter {
    protected void open() {
        System.out.println("open csv");
    }

    protected void parse() {
        System.out.println("parse csv");
    }

    protected void save() {
        System.out.println("save rows");
    }
}
```

用的时候：

```java
new CsvImporter().run();
```

**什么时候用**：流程固定、步骤有小差异（导入、构建、初始化）。

**坑**：继承把子类和父类绑死，步骤一变全受影响；能用组合 + 策略就别硬用继承。

## 12. 访问者 Visitor

**意图**：在不修改元素类的前提下，给它们加新操作。

**代码**：

```java
interface Expr {
    void accept(Visitor visitor);
}

record Num(int value) implements Expr {
    public void accept(Visitor visitor) {
        visitor.visit(this);
    }
}

record Add(Expr left, Expr right) implements Expr {
    public void accept(Visitor visitor) {
        visitor.visit(this);
    }
}

interface Visitor {
    void visit(Num num);

    void visit(Add add);
}

class EvalVisitor implements Visitor {
    private int acc;

    public void visit(Num num) {
        acc = num.value();
    }

    public void visit(Add add) {
        add.left().accept(this);
        int left = acc;
        add.right().accept(this);
        acc = left + acc;
    }

    int result() {
        return acc;
    }
}
```

用的时候：

```java
EvalVisitor visitor = new EvalVisitor();
new Add(new Num(2), new Num(3)).accept(visitor);
System.out.println(visitor.result());     // 5
```

**什么时候用**：结构稳定、操作经常新增（AST 求值/打印/校验、报表导出）。

**坑**：加一个新元素类型要改所有 Visitor——访问者对"新增元素"不友好，和 `instanceof` 链相比只是把判断集中了。Java 21 的 `sealed interface` + 模式匹配 `switch` 能替代一部分访问者场景。

## 13. 选型表

| 你要解决的事 | 用 |
| --- | --- |
| 请求要沿链传递、调用方不关心谁处理 | 责任链 |
| 请求要能排队/撤销/记录 | 命令 |
| 给一门简单语法求值 | 解释器 |
| 隐藏集合内部结构来遍历 | 迭代器 |
| 多对象网状通信要解耦 | 中介者 |
| 要保存/恢复状态 | 备忘录 |
| 状态变化要通知多处 | 观察者 |
| 行为随状态变、转换复杂 | 状态 |
| 算法要可替换 | 策略 |
| 流程固定、步骤有差异 | 模板方法 |
| 结构稳定、操作常新增 | 访问者 |

## 14. 参考

- GoF《设计模式：可复用面向对象软件的基础》
- Java 21 `sealed`、`record`、模式匹配 `switch`（可替代部分访问者/状态实现）
</content>
