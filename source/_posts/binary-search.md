---
title: 二分笔记：从边界写法到二分答案
date: 2026-10-28 22:30:00
description: 二分查找最容易错在区间定义和边界更新。这篇把三种模板、四种变体、死循环的成因讲清楚，再给出二分答案的通用套路和 5 道例题。
categories:
  - 技术
tags:
  - 算法
  - 二分
cover: /img/cover-binary.jpg
---

## 二分到底在做什么

二分不是"在有序数组里找数"，而是：**在答案空间上，用一个单调的判定把范围砍一半。**

所以它能用的前提只有两个：

1. **单调性**：随着下标/答案值增大，判定结果只会从 `false` 翻成 `true` 一次（或反过来）
2. **判定够便宜**：能在 `O(1)` 或 `O(log)` 级别判断"当前点在目标的哪一侧"

只要满足这两条，数组是否有序、甚至有没有数组，都不重要 —— 这就是"二分答案"能成立的原因。

{% note blue 'anzhiyufont anzhiyu-icon-circle-info' %}
一句话总结：**二分 = 维护一个"答案一定还在里面"的区间，每次砍一半。**
{% endnote %}

## 三种模板，先选一种

所有二分错误的根源都是**区间定义和循环条件不一致**。动手前先明确：区间是闭的还是左闭右开的。

### 模板 A：闭区间 `[left, right]`

```java
int left = 0, right = n - 1;
while (left <= right) {              // 区间非空才继续
    int mid = left + (right - left) / 2;
    if (nums[mid] == target) return mid;
    else if (nums[mid] < target) left = mid + 1;
    else right = mid - 1;            // 两边都跳过 mid，所以 mid 已经被排除
}
return -1;
```

`left <= right` 对应"闭区间"，`left = mid + 1` / `right = mid - 1` 对应"`mid` 已经判断过、可以排除"。这两件事必须配套。

### 模板 B：左闭右开 `[left, right)`

```java
int left = 0, right = n;             // right 取不到
while (left < right) {               // 区间为空时 left == right
    int mid = left + (right - left) / 2;
    if (nums[mid] < target) left = mid + 1;
    else right = mid;                // mid 仍可能是答案，不能减一
}
return left;                         // 循环结束时 left 就是第一个 >= target 的位置
```

这个模板天生就是 `lower_bound`：**退出时 `left` 是第一个不满足"小于 target"的位置**。

### 模板 C：二分答案

```java
int lo = 最小可能答案, hi = 最大可能答案;
while (lo < hi) {
    int mid = lo + (hi - lo) / 2;
    if (check(mid)) hi = mid;        // mid 可行，答案不超过 mid
    else lo = mid + 1;               // mid 不可行，答案至少 mid + 1
}
return lo;                           // 最小的可行解
```

求"最大可行解"时把方向反过来，并且 `mid` 要**上取整**：

```java
while (lo < hi) {
    int mid = lo + (hi - lo + 1) / 2;   // 上取整，否则 lo = mid 会死循环
    if (check(mid)) lo = mid;           // mid 可行，答案至少 mid
    else hi = mid - 1;
}
return lo;
```

`lo = mid` 配下取整 = 死循环（`lo`、`hi` 相邻时 `mid` 永远等于 `lo`，区间不再收缩）。**这是二分答案最常见的一行 bug。**

## 四种变体，一张表记住

| 要找的东西 | 判定条件 | 返回 |
| --- | --- | --- |
| 精确值 | `a[mid] == target` | `mid`，找不到返回 `-1` |
| 第一个 `>= target` | `a[mid] >= target` 就往左收 | `left` |
| 第一个 `> target` | `a[mid] > target` 就往左收 | `left` |
| 最后一个 `<= target` | 等价于"第一个 `> target` 的位置减一" | `left - 1` |

后三种都能用模板 B 一个骨架写出来，只改一个比较符号：

```java
// 第一个 >= target
int l = 0, r = a.length;
while (l < r) {
    int mid = l + (r - l) / 2;
    if (a[mid] < target) l = mid + 1;
    else r = mid;
}
return l;

// 第一个 > target：只把 < 改成 <=
if (a[mid] <= target) l = mid + 1;
else r = mid;
```

## 四个最容易踩的坑

- **`mid` 溢出**：`(left + right) / 2` 在 `left + right > Integer.MAX_VALUE` 时变成负数，用 `left + (right - left) / 2`。
- **区间定义和更新不配套**：闭区间配 `<=`，左闭右开配 `<`；混用必错。
- **死循环**：`lo = mid` / `right = mid` 配错取整方向。
- **`Arrays.binarySearch` 的返回值**：找不到时返回 `-(插入点) - 1`，不是 `-1`，直接拿来当下标会数组越界。

## 例题

### 1. 二分查找（LeetCode 704）

裸模板 A：

```java
class Solution {
    public int search(int[] nums, int target) {
        int left = 0, right = nums.length - 1;
        while (left <= right) {
            int mid = left + (right - left) / 2;
            if (nums[mid] == target) return mid;
            else if (nums[mid] < target) left = mid + 1;
            else right = mid - 1;
        }
        return -1;
    }
}
```

- **时间**：`O(log n)`　**空间**：`O(1)`

### 2. 在排序数组中查找元素的第一个和最后一个位置（LeetCode 34）

两个边界 = 两次 `lower_bound`：

```java
class Solution {
    public int[] searchRange(int[] nums, int target) {
        int first = lowerBound(nums, target);
        if (first == nums.length || nums[first] != target) {
            return new int[]{-1, -1};
        }
        int last = upperBound(nums, target) - 1;
        return new int[]{first, last};
    }

    // 第一个 >= target
    private int lowerBound(int[] a, int target) {
        int l = 0, r = a.length;
        while (l < r) {
            int mid = l + (r - l) / 2;
            if (a[mid] < target) l = mid + 1;
            else r = mid;
        }
        return l;
    }

    // 第一个 > target
    private int upperBound(int[] a, int target) {
        int l = 0, r = a.length;
        while (l < r) {
            int mid = l + (r - l) / 2;
            if (a[mid] <= target) l = mid + 1;
            else r = mid;
        }
        return l;
    }
}
```

这里特意没用 `lowerBound(target + 1)` 找右边界：`target` 是 `Integer.MAX_VALUE` 时会溢出。

- **时间**：`O(log n)`　**空间**：`O(1)`

### 3. 搜索旋转排序数组（LeetCode 33）

数组被旋转后整体不再有序，但**任意切一刀，至少有一半是有序的**。先判断哪半有序，再看 `target` 在不在那一半里：

```java
class Solution {
    public int search(int[] nums, int target) {
        int l = 0, r = nums.length - 1;
        while (l <= r) {
            int mid = l + (r - l) / 2;
            if (nums[mid] == target) return mid;
            if (nums[l] <= nums[mid]) {                       // 左半段有序
                if (nums[l] <= target && target < nums[mid]) r = mid - 1;
                else l = mid + 1;
            } else {                                          // 右半段有序
                if (nums[mid] < target && target <= nums[r]) l = mid + 1;
                else r = mid - 1;
            }
        }
        return -1;
    }
}
```

- **时间**：`O(log n)`　**空间**：`O(1)`

### 4. 爱吃香蕉的珂珂（LeetCode 875）—— 二分答案

问"最小速度"，而"以速度 `k` 能不能在 `h` 小时内吃完"是单调的：`k` 越大越容易完成。于是对**速度**二分：

```java
class Solution {
    public int minEatingSpeed(int[] piles, int h) {
        int lo = 1, hi = 0;
        for (int p : piles) hi = Math.max(hi, p);   // 答案一定在 [1, 最大堆]
        while (lo < hi) {
            int mid = lo + (hi - lo) / 2;
            if (canFinish(piles, mid, h)) hi = mid;  // 可行就试着更小
            else lo = mid + 1;
        }
        return lo;
    }

    private boolean canFinish(int[] piles, int k, int h) {
        long hours = 0;                              // 用 long 防溢出
        for (int p : piles) hours += (p + k - 1) / k;
        return hours <= h;
    }
}
```

- **时间**：`O(n log max(piles))`　**空间**：`O(1)`

### 5. 在 D 天内送达包裹的能力（LeetCode 1011）—— 二分答案

和上一题一模一样的骨架，只是判定函数换成"按容量 `cap` 装，需要几天"：

```java
class Solution {
    public int shipWithinDays(int[] weights, int days) {
        int lo = 0, hi = 0;
        for (int w : weights) {
            lo = Math.max(lo, w);   // 下界：至少装得下最重的那个
            hi += w;                // 上界：一天全装走
        }
        while (lo < hi) {
            int mid = lo + (hi - lo) / 2;
            if (canShip(weights, mid, days)) hi = mid;
            else lo = mid + 1;
        }
        return lo;
    }

    private boolean canShip(int[] weights, int cap, int days) {
        int need = 1, cur = 0;
        for (int w : weights) {
            if (cur + w > cap) {    // 装不下就开新的一天
                need++;
                cur = 0;
            }
            cur += w;
        }
        return need <= days;
    }
}
```

- **时间**：`O(n log sum(weights))`　**空间**：`O(1)`

## 二分答案的做题步骤

1. **确定答案是什么**：速度、容量、时间、长度……（不是数组下标）
2. **写出 `check(x)`**：`x` 可行的充要条件，复杂度一般 `O(n)`
3. **确认单调性**：`x` 变大，`check` 只会从 `false` 变 `true`（或反过来）
4. **定上下界**：下界取"理论最小"，上界取"一定可行"，宁可宽一点也不要想漏
5. **选模板**：求最小可行用下取整，求最大可行用上取整

## 易错点清单

- `mid` 用 `left + (right - left) / 2`，不要 `(left + right) / 2`
- 闭区间 / 左闭右开选定后，循环条件和 `mid` 更新必须配套
- `lo = mid` 一定配上取整 `(hi - lo + 1) / 2`
- 累加型 `check`（小时数、总和）用 `long`
- 二分答案的上下界别收太紧，`lo` 取不到可行解会直接返回错误值
- `Arrays.binarySearch` 找不到时返回 `-(插入点) - 1`

## 参考

- [二分查找 - 维基百科](https://zh.wikipedia.org/wiki/%E4%BA%8C%E5%88%86%E6%90%9C%E5%B0%8B%E6%BC%94%E7%AE%97%E6%B3%95)
- 《算法竞赛进阶指南》0x04 二分
