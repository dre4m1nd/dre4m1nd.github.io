---
title: 快排笔记：二路快排与三路快排
date: 2026-10-28 23:40:00
description: 二路快排的 Lomuto 与 Hoare 两种 partition、三路快排为什么能治大量重复元素、随机化 pivot 与尾递归优化，附 Java 完整实现和 4 道例题。
categories:
  - 技术
tags:
  - 算法
  - 排序
  - 快速排序
cover: /img/cover-quicksort.jpg
---

## 快排的本质

快排只做一件事：**选一个基准值 pivot，把数组划分成"小于它 / 等于它 / 大于它"几段，然后递归处理各段。**

```
[  < pivot  |  = pivot  |  > pivot  ]
```

划分（partition）一次是 `O(n)`，平均要划 `O(log n)` 层，所以平均 `O(n log n)`。

"二路"和"三路"的区别只在**划分成几段**：

| 版本 | 划分结果 | 递归处理 |
| --- | --- | --- |
| 二路快排 | `[<= pivot]` + `[> pivot]` | 两段都要递归 |
| 三路快排 | `[< pivot]` + `[== pivot]` + `[> pivot]` | 中间那段已经就位，**不用递归** |

差别看起来很小，但在"大量重复元素"的场景下是数量级的差距，后面会说。

## 二路快排：两种 partition

### 写法一：Lomuto（单指针）

思路：用 `i` 维护"小于 pivot 的区域"的右边界，`j` 从左扫到右，遇到小的就换到左边。

```java
// 把 a[lo..hi] 以 a[hi] 为基准划分，返回基准最终下标
private int partition(int[] a, int lo, int hi) {
    int pivot = a[hi];
    int i = lo;                        // [lo, i) 区间内的元素都 < pivot
    for (int j = lo; j < hi; j++) {
        if (a[j] < pivot) {
            swap(a, i, j);
            i++;
        }
    }
    swap(a, i, hi);                    // pivot 放到分界点上
    return i;
}
```

优点：好写好记，边界不易错。
缺点：**遇到等于 pivot 的元素不动**，所以数组里有大量重复时，每次划分只能排除 pivot 一个位置，退化成 `O(n²)`。

### 写法二：Hoare（双指针，原始版本）

思路：`i` 从左往右找"大于等于 pivot"的，`j` 从右往左找"小于等于 pivot"的，两个都找到就交换。

```java
private int partition(int[] a, int lo, int hi) {
    int pivot = a[lo + (hi - lo) / 2]; // 取中间值，天然缓解有序数组退化
    int i = lo - 1, j = hi + 1;
    while (true) {
        do { i++; } while (a[i] < pivot);
        do { j--; } while (a[j] > pivot);
        if (i >= j) return j;          // 注意返回的是 j，不是 i
        swap(a, i, j);
    }
}

private void sort(int[] a, int lo, int hi) {
    if (lo >= hi) return;
    int p = partition(a, lo, hi);
    sort(a, lo, p);                    // 是 [lo, p] 和 [p+1, hi]
    sort(a, p + 1, hi);
}
```

两个容易错的地方：

- **返回值是 `j`，不是 `i`**，并且递归区间是 `[lo, p]` 和 `[p+1, hi]`（`p` 这个位置不一定是 pivot 的最终位置，别按 Lomuto 的习惯写成 `p-1`）
- 用 `do-while` 先动指针再比较，保证 pivot 本身能挡住指针

Hoare 版比 Lomuto 快在**交换次数少**（大约是 Lomuto 的 1/3），而且不会把"等于 pivot"的元素全堆到一边。

### 让快排不退化的两件事

1. **随机化 pivot**：`swap(a, lo + rnd.nextInt(hi - lo + 1), hi)`，然后照常划分。防止"已经有序"的输入退化成 `O(n²)`。
2. **小数组切插入排序**：区间长度 < 16 时直接插入排序，常数更小（Java 的 `Arrays.sort` 也是这么干的）。

## 三路快排：专治重复元素

三路划分（Dijkstra 荷兰国旗问题）把数组分成三段，用三个指针：

- `lt`：`[lo, lt)` 都 `< pivot`
- `i`：`[lt, i)` 都 `== pivot`
- `gt`：`(gt, hi]` 都 `> pivot`

`i` 从左往右走：

```java
private void sort(int[] a, int lo, int hi) {
    if (lo >= hi) return;
    int pivot = a[lo + rnd.nextInt(hi - lo + 1)];
    int lt = lo, i = lo, gt = hi;
    while (i <= gt) {
        if (a[i] < pivot) {
            swap(a, lt++, i++);        // 换到左段，lt 和 i 一起前进
        } else if (a[i] > pivot) {
            swap(a, i, gt--);          // 换到右段，i 不动（换过来的元素还没看过）
        } else {
            i++;                       // 等于 pivot，留在中间段
        }
    }
    sort(a, lo, lt - 1);               // 只递归左右两段
    sort(a, gt + 1, hi);               // 中间段 [lt, gt] 已经就位
}
```

**为什么 `i` 在 `a[i] > pivot` 时不能加一**：从 `gt` 换过来的元素还没被检查过，必须留在原地下一轮再看。这是三路快排唯一的高频错误。

`swap(a, lt++, i++)` 之所以能两个都加一，是因为 `[lt, i)` 区间里全是等于 pivot 的元素，换过来的必然是等于 pivot 的。

### 为什么三路能治重复

假设数组是 `[1,1,1,...,1]`（n 个相同值）：

- 二路：每次划分只能确定一个位置，递归 n 层 → `O(n²)`
- 三路：第一次划分就把整个数组划进"等于段"，`lt = lo`、`gt = hi`，递归的两个区间都是空的 → **一次 `O(n)` 就结束**

LeetCode 912 那种卡常数的题，用二路会被全相同数据的用例卡死，三路直接过。

## 完整实现（三路 + 随机化 + 小数组插排 + 尾递归优化）

```java
class Solution {
    private static final Random RND = new Random();

    public int[] sortArray(int[] nums) {
        sort(nums, 0, nums.length - 1);
        return nums;
    }

    private void sort(int[] a, int lo, int hi) {
        while (lo < hi) {                              // 用循环代替尾递归，栈深度 O(log n)
            if (hi - lo < 16) {
                insertionSort(a, lo, hi);
                return;
            }
            int pivot = a[lo + RND.nextInt(hi - lo + 1)];
            int lt = lo, i = lo, gt = hi;
            while (i <= gt) {
                if (a[i] < pivot) swap(a, lt++, i++);
                else if (a[i] > pivot) swap(a, i, gt--);
                else i++;
            }
            // 先递归较短的一段，长的一段用循环继续处理
            if (lt - lo < hi - gt) {
                sort(a, lo, lt - 1);
                lo = gt + 1;
            } else {
                sort(a, gt + 1, hi);
                hi = lt - 1;
            }
        }
    }

    private void insertionSort(int[] a, int lo, int hi) {
        for (int i = lo + 1; i <= hi; i++) {
            int v = a[i], j = i - 1;
            while (j >= lo && a[j] > v) {
                a[j + 1] = a[j];
                j--;
            }
            a[j + 1] = v;
        }
    }

    private void swap(int[] a, int i, int j) {
        int t = a[i];
        a[i] = a[j];
        a[j] = t;
    }
}
```

尾递归优化的意义：每层只递归较短的一半，长的用 `while` 继续，递归栈深度保证 `O(log n)`，最坏情况也不会栈溢出。

## 复杂度与性质

| | 平均 | 最坏 | 空间 | 稳定性 |
| --- | --- | --- | --- | --- |
| 二路快排（Lomuto） | `O(n log n)` | `O(n²)`（有序 + 固定 pivot / 大量重复） | `O(log n)` 栈 | 不稳定 |
| 二路快排（Hoare） | `O(n log n)` | `O(n²)` | `O(log n)` 栈 | 不稳定 |
| 三路快排 | `O(n log n)` | `O(n²)`（但全相同是 `O(n)`） | `O(log n)` 栈 | 不稳定 |

- 快排**不稳定**：划分时的交换会打乱相同元素的相对顺序
- 工程上 Java 的 `Arrays.sort(int[])` 用的是 **DualPivotQuicksort（双轴快排）**，取两个 pivot 分三段，本质是三路划分的加强版

## 例题

### 1. 颜色分类（LeetCode 75）—— 三路划分的原型

只有 0/1/2 三种值，把 pivot 固定成 1，就是纯三路划分：

```java
class Solution {
    public void sortColors(int[] nums) {
        int lt = 0, i = 0, gt = nums.length - 1;
        while (i <= gt) {
            if (nums[i] == 0) swap(nums, lt++, i++);
            else if (nums[i] == 2) swap(nums, i, gt--);
            else i++;
        }
    }

    private void swap(int[] a, int i, int j) {
        int t = a[i]; a[i] = a[j]; a[j] = t;
    }
}
```

- **时间**：`O(n)`（一趟扫完）　**空间**：`O(1)`

### 2. 排序数组（LeetCode 912）—— 直接套上面的完整实现

用二路 Lomuto 会卡在全相同的用例上（TLE），换三路就过。上面那份完整实现直接提交即可。

- **时间**：平均 `O(n log n)`　**空间**：`O(log n)`

### 3. 数组中的第 K 个最大元素（LeetCode 215）—— 快速选择

不用全排序，划分一次就能确定 pivot 的最终位置：位置对了就直接返回，只需要递归一侧，均摊 `O(n)`。

```java
class Solution {
    private static final Random RND = new Random();

    public int findKthLargest(int[] nums, int k) {
        int target = nums.length - k;          // 第 k 大 = 升序里的 n - k
        int lo = 0, hi = nums.length - 1;
        while (true) {
            int p = partition(nums, lo, hi);
            if (p == target) return nums[p];
            if (p < target) lo = p + 1;
            else hi = p - 1;
        }
    }

    private int partition(int[] a, int lo, int hi) {
        swap(a, lo + RND.nextInt(hi - lo + 1), hi);   // 随机化，防止被有序数据打爆
        int pivot = a[hi], i = lo;
        for (int j = lo; j < hi; j++) {
            if (a[j] < pivot) swap(a, i++, j);
        }
        swap(a, i, hi);
        return i;
    }

    private void swap(int[] a, int i, int j) {
        int t = a[i]; a[i] = a[j]; a[j] = t;
    }
}
```

- **时间**：平均 `O(n)`，最坏 `O(n²)`（随机化后概率极低）　**空间**：`O(1)`

### 4. 最小的 k 个数（面试题 17.14）

和上一题同一个套路，只是目标下标换成 `k - 1`，最后返回前 `k` 个：

```java
class Solution {
    private static final Random RND = new Random();

    public int[] smallestK(int[] arr, int k) {
        if (k == 0) return new int[0];
        int lo = 0, hi = arr.length - 1, target = k - 1;
        while (true) {
            int p = partition(arr, lo, hi);
            if (p == target) break;
            if (p < target) lo = p + 1;
            else hi = p - 1;
        }
        return Arrays.copyOf(arr, k);          // 前 k 个就是最小的 k 个（无序）
    }

    private int partition(int[] a, int lo, int hi) {
        swap(a, lo + RND.nextInt(hi - lo + 1), hi);
        int pivot = a[hi], i = lo;
        for (int j = lo; j < hi; j++) {
            if (a[j] < pivot) swap(a, i++, j);
        }
        swap(a, i, hi);
        return i;
    }

    private void swap(int[] a, int i, int j) {
        int t = a[i]; a[i] = a[j]; a[j] = t;
    }
}
```

注意返回的 k 个数**不保证有序**，题目只要求"最小的 k 个"，如果要升序再排一次。

## 易错点清单

- **三路划分里 `a[i] > pivot` 时 `i` 不能加一**（换过来的元素还没检查）
- **Hoare 版返回 `j`**，递归区间是 `[lo, p]` / `[p+1, hi]`，别套 Lomuto 的 `p-1`
- **没随机化 pivot**：遇到有序数组直接退化成 `O(n²)`，LeetCode 会 TLE
- **大量重复元素用二路**：同样退化，换三路
- **递归只处理长的一侧**：不加尾递归优化，最坏递归深度 `O(n)` 可能栈溢出
- **`[lt, i)` 的语义**：`lt` 指向第一个等于 pivot 的位置，`i` 指向第一个未检查的位置，两个别搞混

## 参考

- [快速排序 - 维基百科](https://zh.wikipedia.org/wiki/%E5%BF%AB%E9%80%9F%E6%8E%92%E5%BA%8F)
- [荷兰国旗问题 - 维基百科](https://zh.wikipedia.org/wiki/%E5%9B%BD%E6%97%97%E9%97%AE%E9%A2%98)
- 《算法（第 4 版）》2.3 快速排序
