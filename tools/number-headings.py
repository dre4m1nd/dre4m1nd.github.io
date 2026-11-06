#!/usr/bin/env python
# tools/number-headings.py
# 给 Hexo 文章的大小标题自动加序号：## 改成「1. 标题」、### 改成「1.1 标题」，
# 支持任意层级（#### → 1.1.1），幂等（重跑不会重复加号）。
#
# 用法：
#   python tools/number-headings.py source/_posts/2026/11/fastapi-intro.md
#   python tools/number-headings.py source/_posts/**/*.md   # 多文件
#
# 规则：只处理代码围栏（```）之外的标题行；跳过 frontmatter；
#       不处理 # 一级标题（文章标题）和 5 级以上的标题。

import argparse
import re
import sys

MAX_DEPTH = 4          # 给 2~4 级标题编号（1. / 1.1 / 1.1.1）
STRIP_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")   # 去掉已有的「1. 」「1.1 」前缀


def number_headings(text: str) -> str:
    counters = [0] * (MAX_DEPTH + 1)     # counters[depth]
    in_code = False
    frontmatter_done = False
    out = []

    for line in text.splitlines():
        stripped = line.lstrip()
        # 代码围栏开关（行首三个反引号，可能有语言名）
        if stripped.startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue

        # 跳过 frontmatter（文件开头的两个 --- 之间）
        if not frontmatter_done:
            if stripped == "---":
                frontmatter_done = True
            out.append(line)
            continue

        m = re.match(r"^(#{2,4})\s+(\S.*)$", line)
        if m:
            depth = len(m.group(1))
            title = m.group(2)
            title = STRIP_RE.sub("", title)          # 去旧序号，保证幂等

            for d in range(depth + 1, MAX_DEPTH + 1):
                counters[d] = 0                       # 重置更深层
            counters[depth] += 1

            num = ".".join(str(counters[d]) for d in range(2, depth + 1))
            out.append(f"{'#' * depth} {num}. {title}")
        else:
            out.append(line)

    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def main():
    ap = argparse.ArgumentParser(description="给 Hexo 文章标题加序号（幂等）")
    ap.add_argument("paths", nargs="+", help="markdown 文件路径")
    ap.add_argument("--check", action="store_true",
                    help="只检查是否已经编号，不改文件；有未编号标题则返回 1")
    args = ap.parse_args()

    rc = 0
    for path in args.paths:
        text = open(path, encoding="utf-8").read()
        numbered = number_headings(text)
        if args.check:
            # 检查是否还有未编号的 2~4 级标题
            has_unnumbered = False
            for line in numbered.splitlines():
                m = re.match(r"^#{2,4}\s+\S", line)
                if m and not re.match(r"^#{2,4}\s+\d", m.group(0)):
                    has_unnumbered = True
            if has_unnumbered:
                print(f"[未编号] {path}")
                rc = 1
            continue
        if numbered != text:
            open(path, "w", encoding="utf-8").write(numbered)
            print(f"[已编号] {path}")
        else:
            print(f"[无需改动] {path}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
