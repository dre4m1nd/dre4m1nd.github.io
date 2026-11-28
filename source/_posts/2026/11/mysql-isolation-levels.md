---
title: "MySQL 四档隔离级别跑了一遍：RR 下的幻读和间隙锁，比想象中具体"
slug: mysql-isolation-levels
date: 2026-11-28 11:02:13
description: "在 MySQL 8.4.7 上用两个会话把四档隔离级别逐项跑了一遍：RU 能读到未提交的 100，回滚后这个值从未存在过；RR 的快照读看不见新插入的行，但紧接着的 UPDATE 却影响了 2 行；同样的 SELECT ... FOR UPDATE，二级索引等值锁住间隙、无索引列锁住全表、主键等值只锁一行；三组 data_locks 原始输出摆在正文里。"
categories:
  - 技术
tags:
  - MySQL 隔离级别
cover: /img/2026/11/mysql-isolation-levels.jpg
---

> 「MySQL 默认 REPEATABLE READ，所以不会有幻读」这句话在面试里能过关，在线上会出事。幻读在 RR 下确实被挡住了——但只挡**快照读**。同一个事务里只要出现一条 `UPDATE`、`DELETE` 或 `SELECT ... FOR UPDATE`，它读的就是最新提交版本，新行立刻现身，而且连间隙一起锁住。
>
> 这篇用两个会话把四档隔离级别逐项跑了一遍，是 [Spring 事务传播那篇](/2026/11/spring-transaction-propagation/)的下一层：那篇讲应用层的事务边界，这篇讲存储层的锁和快照。所有结论都对应正文里的原始输出：`performance_schema.data_locks` 的锁清单、`INSERT` 被挡住的实际耗时、以及 InnoDB 自己打印的死锁报告。
>
> 环境：MySQL 8.4.7（官方 zip 版，端口 3307），`transaction_isolation = REPEATABLE-READ`，`innodb_lock_wait_timeout = 50`，全部跑在本机 Windows 上。

## 1. 结论先行

同一张表、两条会话，四档隔离级别跑下来：

| 现象 | READ UNCOMMITTED | READ COMMITTED | REPEATABLE READ | SERIALIZABLE |
| --- | --- | --- | --- | --- |
| 脏读（读到未提交的写） | **能读到**（100） | 读不到（1） | 读不到 | 读不到 |
| 不可重复读（同事务两次读不同） | 能 | **能**（2 → 200） | 不能（2 → 2） | 不能 |
| 幻读（同事务两次读行数不同） | 能 | **能**（1 → 2） | 快照读不能，**当前读能**（1 → 2） | 不能 |
| 间隙锁 | 无 | **无** | 有 | 有 |

三句话说完：

1. **RR 的读是快照，写是当前读。** 快照读永远停在事务开始那一刻；`UPDATE`/`FOR UPDATE` 永远看最新提交，还要给扫到的范围加锁。两者在同一个事务里混用，就会看到「先 1 行后 2 行」。
2. **间隙锁只在 RR 及以上存在。** 同一条 `SELECT ... FOR UPDATE`，RR 下挡住别人的 `INSERT` 一秒直到报 1205，RC 下 3ms 就插进去了。
3. **锁多大，取决于访问路径，不取决于你写了什么条件。** 二级索引等值 → 锁记录 + 间隙；无索引列 → 全表所有记录 + supremum；主键等值 → 只锁那一行。

## 2. 实验怎么搭的

本机 Docker 起不来（引擎管道没就绪），直接用 MySQL 官方的免安装 zip：

```bash
# 解压后初始化，root 空口令，端口避开默认的 3306
bin/mysqld.exe --initialize-insecure --basedir=<解压目录> --datadir=<数据目录>
bin/mysqld.exe --port=3307 --mysqlx=0 --console
```

表结构刻意保持最小，只留三个字段和一条二级索引：

```sql
CREATE TABLE t (
  id INT PRIMARY KEY,
  k  INT NOT NULL,
  v  INT NOT NULL,
  KEY idx_k (k)
) ENGINE=InnoDB;

INSERT INTO t VALUES (1,1,1),(2,2,2),...,(10,10,10);
```

两个会话都用 `BEGIN` 显式开事务，中间用 `COMMIT`/`ROLLBACK` 控制边界；要观察「被挡住」的会话统一设 `innodb_lock_wait_timeout = 1`，免得等满 50 秒。

## 3. 脏读：RU 读到了一个从未存在过的值

```sql
-- A
BEGIN; UPDATE t SET v=100 WHERE id=1;      -- 还没提交
-- B（READ UNCOMMITTED）
BEGIN; SELECT v FROM t WHERE id=1;
```

`B` 读到 **100**。同一个时刻换一个 RC 会话去读，读到的是 **1**。

接着 `A` 执行 `ROLLBACK`，`B` 在同一事务里再读一次：

```text
    SQL> ROLLBACK
  -- A 回滚后，B 再读一次：这个 100 从未存在过
    SQL> SELECT v FROM t WHERE id=1
    v
    1
```

**100 这个值从未在任何时刻被提交过。** 读到它的事务如果拿它去算库存、算余额，结果就是错的，而且事后无从追溯——因为它没进过任何日志。

## 4. 不可重复读：差的不是一个开关，是一条快照

同样的剧本，只换隔离级别：`A` 改值并提交，`B` 在事务内读两次。

```text
  -- 隔离级别 READ COMMITTED
    SELECT v FROM t WHERE id=2   -> 2
    UPDATE t SET v=200 WHERE id=2; COMMIT;
    SELECT v FROM t WHERE id=2   -> 200

  -- 隔离级别 REPEATABLE READ
    SELECT v FROM t WHERE id=2   -> 2
    UPDATE t SET v=200 WHERE id=2; COMMIT;
    SELECT v FROM t WHERE id=2   -> 2
```

RC 每次读都新建快照，所以看得到别人的提交；RR 在**事务第一次读**时建快照，之后一直用它。这里没有锁参与，纯粹是快照生命周期的差别。

## 5. 幻读：快照读看不见，当前读不仅看见还锁住

这是 RR 最容易被讲错的地方。先插入一行新数据并提交，再在 RR 事务里读：

```text
    BEGIN
    SELECT COUNT(*) FROM t WHERE k=5;   -> 1
    -- 另一个事务 INSERT (11,5,11) 并 COMMIT
    SELECT COUNT(*) FROM t WHERE k=5;   -> 1        ← 快照读，看不见
    UPDATE t SET v=v+1 WHERE k=5;       -> (2 rows affected)
    SELECT COUNT(*) FROM t WHERE k=5;   -> 2        ← 同一个事务里，幻读出现了
```

`UPDATE` 影响 2 行——它用的是当前读，看得到刚提交的那一行，并且把它锁住。**这条 UPDATE 之后，事务的快照被自己的写"污染"了：再读就看到 2 行。**

同样的序列在 RC 下更直接：第二次 `SELECT COUNT(*)` 就是 2，不需要写操作来触发。

所以「RR 没有幻读」的准确说法是：**RR 的一致性读没有幻读，当前读有。** 而当前读包括 `SELECT ... FOR UPDATE`、`SELECT ... LOCK IN SHARE MODE`、`UPDATE`、`DELETE`——业务代码里到处都是。

## 6. 间隙锁：三种 WHERE，三种加锁范围

`SELECT ... FOR UPDATE` 在 RR 下加的是 next-key lock（记录锁 + 前面的间隙）。锁多大范围，取决于优化器选了哪条访问路径。三组实测：

### 6.1. 二级索引等值：锁记录 + 间隙

```sql
BEGIN; SELECT * FROM t WHERE k=5 FOR UPDATE;
```

```text
    INDEX_NAME | LOCK_TYPE | LOCK_MODE      | LOCK_DATA
    PRIMARY    | RECORD    | X,REC_NOT_GAP  | 5
    idx_k      | RECORD    | X,GAP          | 6, 6
    idx_k      | RECORD    | X              | 5, 5
```

除了命中行本身，`idx_k` 上还锁住了 `k=5` 之后到 `k=6` 之间的间隙。此时另一个会话插入 `(20,5,20)`：

```text
    -> 被挡住：(1205, 'Lock wait timeout exceeded; try restarting transaction')
    -> 等待 1.01 s 后放弃
```

**插入的是 id=20 的新行，和现有行毫无关系，照样被挡住**——因为 `k=5` 落在被锁的间隙里。

### 6.2. 无索引列：锁住全表所有记录 + supremum

同样的语句换成没有索引的列：

```sql
BEGIN; SELECT * FROM t WHERE v=5 FOR UPDATE;
```

```text
    INDEX_NAME | LOCK_TYPE | LOCK_MODE | LOCK_DATA
    PRIMARY    | RECORD    | X         | supremum pseudo-record
    PRIMARY    | RECORD    | X         | 1
    PRIMARY    | RECORD    | X         | 2
    ...（10 行全部）
    PRIMARY    | RECORD    | X         | 10
```

10 行的表，锁了 10 行 + supremum，等于锁表。插入 `(21,99,99)` 同样 1 秒后 1205。

**「条件里没写索引列」不会让锁变小，只会让它变成全表。**

### 6.3. 主键等值：只锁一行，插入不受影响

```sql
BEGIN; SELECT * FROM t WHERE id=5 FOR UPDATE;
```

```text
    PRIMARY | RECORD | X,REC_NOT_GAP | 5
```

只有一条记录锁，没有间隙。插入 `(22,5,22)`：

```text
    -> 插入成功，耗时 3 ms
```

### 6.4. 对照组：同样的语句在 RC 下

```text
    idx_k   | RECORD | X,REC_NOT_GAP | 5, 5
    PRIMARY | RECORD | X,REC_NOT_GAP | 5
    -> INSERT (20,5,20) 插入成功，耗时 3 ms
```

RC 干脆不锁间隙。**这就是同一段代码在 RC 下并发更高、在 RR 下更容易死锁的根源**——不是配置魔法，是锁的形状变了。

## 7. 死锁：反序更新，1 秒内必然撞上

两个事务按相反顺序更新两行：

```sql
-- A: BEGIN; UPDATE t SET v=v+1 WHERE id=1;  然后 UPDATE ... WHERE id=2
-- B: BEGIN; UPDATE t SET v=v+1 WHERE id=2;  然后 UPDATE ... WHERE id=1
```

```text
  A: 更新 id=2 成功（无人死锁）
  B: 更新 id=1 失败 (1213, 'Deadlock found when trying to get lock; try restarting transaction')
```

`A` 的第二次更新先拿到锁，`B` 的第二次更新形成环——InnoDB 立刻检测到，选一个事务回滚。`SHOW ENGINE INNODB STATUS` 里的报告结尾是：

```text
*** WE ROLL BACK TRANSACTION (2)
```

值得注意的是：**这不是异常配置导致的，是 RR 下记录锁的必然结果。** 业务里凡是「批量更新两行以上」，只要不同事务的顺序不一致，就有概率撞上；解法只有两个——统一加锁顺序，或者接受重试。

## 8. 常见坑

- **`REPEATABLE READ` ≠ 没有幻读。** 一致性读没有，当前读有。统计类查询如果和写操作在同一个事务里，两次结果可能不同。
- **`SELECT ... FOR UPDATE` 是当前读**，它会看到别人刚提交的行，也会锁住扫描到的间隙。把它当「加个锁再读」用，等于把 RR 的间隙锁全部打开。
- **没走索引的 `UPDATE`/`DELETE` 会锁全表。** 实测 10 行的表锁出 10 条记录锁 + supremum；线上百万行的表就是一场灾难。
- **RC 没有间隙锁**，同样的代码在 RC 下锁范围小得多。要不要改隔离级别，取决于你能不能接受不可重复读和幻读。
- **`innodb_lock_wait_timeout` 默认 50 秒。** 排查锁冲突时先把它调小，否则一次复现要等一分钟。
- **死锁不是 bug 是协议**：`1213` 要当可重试错误处理，捕获后重跑整个事务，而不是只重跑最后一条 SQL。

## 9. 选型：业务代码该用哪一档

| 场景 | 建议 | 理由 |
| --- | --- | --- |
| 默认 OLTP，读写混合 | RR（MySQL 默认） | 快照读免锁、语句级一致性够用；代价是要理解间隙锁 |
| 高并发写入、锁冲突频繁 | RC | 没有间隙锁，死锁概率显著下降；代价是幻读和不可重复读 |
| 对账、报表、跨表一致性 | RR + 显式 `FOR UPDATE` 或串行化 | 需要当前读语义时别指望快照 |
| 明确要求可串行 | SERIALIZABLE | 读写都加锁，性能最差，只在必要时用 |

## 10. 重点总结

- **RR 的读有两套语义**：快照读停在事务开始那一刻，当前读（`UPDATE`/`FOR UPDATE`）永远看最新提交并加间隙锁。混用就会在同事务里看到「先 1 后 2」。
- **间隙锁只存在于 RR 及以上**：同一条 `SELECT ... FOR UPDATE`，RR 挡插入 1.01s 后 1205，RC 3ms 放行。
- **加锁范围由访问路径决定**：二级索引等值锁记录 + 间隙，无索引列锁全表 + supremum，主键等值只锁一行。
- **反序更新必然死锁**：`1213` 是可重试错误，正确处理是重跑整个事务。
- **读到过不等于存在过**：RU 下的脏读值可能在事后完全没有痕迹，这类值不能用于任何决策。

## 11. 参考

- [MySQL 8.4 Reference Manual — Transaction Isolation Levels](https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html)
- [MySQL 8.4 Reference Manual — InnoDB Locking](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking.html)
- [MySQL 8.4 Reference Manual — Locking Reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html)
