---
title: KMP 算法笔记：从暴力匹配到 next 数组
date: 2026-10-28 20:00:00
description: 只抓"主串指针不回溯"这一个点讲清 KMP：next 数组的定义、手算过程、两种写法的区别，以及 LeetCode 28 的完整实现。
categories:
  - 技术
tags:
  - 算法
  - 字符串
  - KMP
---

## 为什么需要 KMP

字符串匹配的暴力做法是：主串 `S` 的每个位置都拿来和模式串 `P` 从头比一遍，失配就整体右移一位。

```java
for (int i = 0; i + m <= n; i++) {
    int j = 0;
    while (j < m && s.charAt(i + j) == p.charAt(j)) j++;
    if (j == m) return i;   // 匹配成功
}
```

最坏情况下（比如 `S = "aaaaaaab"`，`P = "aaab"`），每轮都要比到最后一个字符才失配，复杂度是 `O(n × m)`。

问题出在**失配后主串指针 `i` 也回退了**：明明前面那几个 `a` 我们已经知道是什么，却要重新比一遍。

## 核心思想

KMP 只做一件事：**失配时主串指针 `i` 不回退，只把模式串指针 `j` 往左挪。**

能这么做的原因是：失配位置之前的那段 `P[0..j-1]` 已经和主串匹配上了，如果这段字符串的**某个前缀等于它的某个后缀**，那么这段前缀天然就和主串对应位置一致，不用再比。

于是 `j` 直接跳到"最长相等前后缀"的长度处继续比较，跳过的部分一次都不重复。

{% note blue 'anzhiyufont anzhiyu-icon-circle-info' %}
一句话总结：**KMP 用模式串自己的重复信息，换掉主串的回退。**
{% endnote %}

## next 数组是什么

定义：`next[j]` = `P[0..j]` 的最长相等前后缀长度（前缀不含最后一个字符，后缀不含第一个字符）。

以 `P = "ababac"` 为例：

| 下标 j | 0 | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- | --- |
| 字符 | a | b | a | b | a | c |
| next[j] | 0 | 0 | 1 | 2 | 3 | 0 |

逐个看：

- `j = 0`：`"a"` 没有真前后缀 → `0`
- `j = 1`：`"ab"`，`"a" ≠ "b"` → `0`
- `j = 2`：`"aba"`，前缀 `"a"` = 后缀 `"a"` → `1`
- `j = 3`：`"abab"`，前缀 `"ab"` = 后缀 `"ab"` → `2`
- `j = 4`：`"ababa"`，前缀 `"aba"` = 后缀 `"aba"` → `3`
- `j = 5`：`"ababac"`，开头 `a` 结尾 `c` 对不上，退一步也没有 → `0`

注意 `next` 还有另一种常见约定：**整体右移一位、`next[0] = -1`**（很多教材和老模板）。两者只差一位，但 `j = next[j]` 和 `j = next[j - 1]` 混用就会错位，**记死一种，别混**。

## 求 next 数组

求 `next` 的过程就是**模式串自己和自己做匹配**：`i` 是"后缀"的末尾，`j` 是"前缀"的长度，同时也是下一个待比较位置。

```java
// next[j] = P[0..j] 的最长相等前后缀长度
int[] getNext(String p) {
    int m = p.length();
    int[] next = new int[m];
    next[0] = 0;
    int j = 0;                       // 当前最长相等前后缀长度
    for (int i = 1; i < m; i++) {    // i 从 1 开始，0 位置没有真前缀
        while (j > 0 && p.charAt(i) != p.charAt(j)) {
            j = next[j - 1];         // 失配：回退到次长的相等前后缀
        }
        if (p.charAt(i) == p.charAt(j)) {
            j++;                     // 前后缀长度 +1
        }
        next[i] = j;
    }
    return next;
}
```

两个细节：

- 失配回退必须用 `while`，因为可能要连着回退好几次；写成 `if` 会在 `"aabaaab"` 这类串上出错。
- `j = next[j - 1]` 里的 `j - 1` 就是"约定 1"的痕迹，换成 `next[j]` 就变成另一种写法了。

## 匹配过程

```java
public int strStr(String s, String p) {
    int n = s.length(), m = p.length();
    if (m == 0) return 0;            // 空模式串按题意返回 0
    int[] next = getNext(p);
    int j = 0;                       // 模式串当前匹配到的位置
    for (int i = 0; i < n; i++) {    // 主串指针永不回退
        while (j > 0 && s.charAt(i) != p.charAt(j)) {
            j = next[j - 1];         // 只挪 j
        }
        if (s.charAt(i) == p.charAt(j)) {
            j++;
        }
        if (j == m) {
            return i - m + 1;        // 匹配完成，返回起始下标
        }
    }
    return -1;
}
```

对照着看就很清楚：求 `next` 是"`p` 匹配 `p`"，匹配是"`p` 匹配 `s`"，两段代码几乎一模一样，只差比较的对象。

## 复杂度

- **时间**：`O(n + m)`。虽然里面有 `while` 回退，但 `j` 每次最多加 1、回退的总次数不会超过增加的次数，所以整个循环是线性的。
- **空间**：`O(m)`，存 `next` 数组。

## 一道常用结论

`next[m - 1]` 是**整个字符串的最长相等前后缀长度**，于是：

- 最小循环节长度 = `m - next[m - 1]`
- 若 `m % (m - next[m - 1]) == 0`，则字符串由该循环节重复构成 → [LeetCode 459. 重复的子字符串](https://leetcode.cn/problems/repeated-substring-pattern/)

这条结论比 KMP 本身更常考，值得单独记一笔。

## 易错点

- **两种 `next` 约定混用**：`next[0] = 0` 还是 `next[0] = -1`，`j = next[j]` 还是 `next[j - 1]`，必须整篇统一。
- **回退用 `while` 不用 `if`**：可能连续回退。
- **求 `next` 时 `i` 从 1 开始**：`i = 0` 没有真前缀，`next[0]` 恒为 0。
- **边界**：模式串为空（返回 0）、模式串比主串长（返回 -1）、只有单个字符。
- 匹配成功后如果还要找**所有**出现位置，把 `j = next[j - 1]` 继续往后走，而不是直接 `j = 0`。

## 相关题目

- [LeetCode 28. 找出字符串中第一个匹配项的下标](https://leetcode.cn/problems/find-the-index-of-the-first-occurrence-in-a-string/) —— 裸 KMP
- [LeetCode 459. 重复的子字符串](https://leetcode.cn/problems/repeated-substring-pattern/) —— 用上面的循环节结论
- [LeetCode 214. 最短回文串](https://leetcode.cn/problems/shortest-palindrome/) —— KMP 思想的变形
