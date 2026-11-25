# tools/check-frontmatter.py
# 发布前校验文章 frontmatter，挡住「能构建但结果不对」的那类错误。
# 这些错误 hexo 不会报、check-links 也抓不到：
#   - date 与文件所在年月文件夹不一致 → URL 在 /2026/11/，归档却归到 2026/01，首页排序沉底
#   - date 只写日期 → 同日多篇顺序由文件遍历决定，不可预测
#   - categories 写了五类以外的词 → 多出一个不在 category_map 里的野分类页
#   - 缺 description / tags / cover
#   - 重复的 slug / title
#
# 用法：
#   python tools/check-frontmatter.py            # 有错误返回 1
#   python tools/check-frontmatter.py -v         # 附上警告明细
#
# 断开/警告分开：ERROR 阻断发布，WARN 只提示。

import argparse
import glob
import os
import re
import sys
from collections import defaultdict

CATEGORIES = ['技术', '笔记', '架构', '概念', '实践']
REQUIRED = ['title', 'date', 'description', 'categories', 'tags', 'cover']
DATE_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?')


def split_frontmatter(text):
    if not text.startswith('---'):
        return None, text
    parts = text.split('---', 2)
    if len(parts) < 3:
        return None, text
    return parts[1], parts[2]


def scalar(fm, key):
    m = re.search(r'^%s:[ \t]*(.*)$' % re.escape(key), fm, re.M)
    return m.group(1).strip().strip('"\'') if m else None


def list_items(fm, key):
    """解析 key 下面那串 `- item` 行"""
    m = re.search(r'^%s:[ \t]*(.*)$' % re.escape(key), fm, re.M)
    if not m:
        return None
    inline = m.group(1).strip()
    if inline.startswith('[') and inline.endswith(']'):
        return [x.strip().strip('"\'') for x in inline[1:-1].split(',') if x.strip()]
    if inline:
        return [inline.strip('"\'')]
    items = []
    for line in fm[m.end():].splitlines():
        if not line.strip():
            continue
        mm = re.match(r'\s*-\s+(.+)$', line)
        if mm:
            items.append(mm.group(1).strip().strip('"\''))
        else:
            break
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='source/_posts')
    ap.add_argument('--site', default='source')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print('没找到 %s' % args.root)
        return 1

    errors = []
    warns = []
    slugs = defaultdict(list)
    titles = defaultdict(list)
    checked = 0

    for path in sorted(glob.glob(os.path.join(args.root, '**', '*.md'), recursive=True)):
        rel = os.path.relpath(path, '.').replace('\\', '/')
        text = open(path, encoding='utf-8').read()
        fm, body = split_frontmatter(text)
        if fm is None:
            errors.append('%s: 没有 frontmatter' % rel)
            continue
        checked += 1

        draft = (scalar(fm, 'published') or '').lower() == 'false'

        for key in REQUIRED:
            if not re.search(r'^%s:' % re.escape(key), fm, re.M):
                errors.append('%s: 缺字段 %s' % (rel, key))

        # date: 格式 + 必须带时间 + 必须与文件夹年月一致
        raw = scalar(fm, 'date') or ''
        m = DATE_RE.match(raw)
        if not m:
            errors.append('%s: date 格式不对（应为 YYYY-MM-DD HH:MM:SS，实际 %r）' % (rel, raw))
        else:
            year, month = m.group(1), m.group(2)
            if not m.group(4):
                warns.append('%s: date 缺时间（建议写 %s-%s-%s 12:00:00，同日多篇排序才稳定）'
                             % (rel, year, month, m.group(3)))
            folder = os.path.dirname(rel).replace('\\', '/')
            mm = re.search(r'/(\d{4})/(\d{2})$', folder)
            if mm and (mm.group(1), mm.group(2)) != (year, month):
                errors.append(
                    '%s: date 是 %s-%s，但文件在 %s/%s 文件夹 —— URL 和归档会分家'
                    % (rel, year, month, mm.group(1), mm.group(2)))

        # categories: 必须恰好一个，且属于五类
        cats = list_items(fm, 'categories')
        if cats is None or not cats:
            errors.append('%s: categories 为空' % rel)
        else:
            if len(cats) > 1:
                errors.append('%s: categories 只能一个（实际 %s）' % (rel, ' / '.join(cats)))
            for c in cats:
                if c not in CATEGORIES:
                    errors.append('%s: 非法分类「%s」（只能 %s）' % (rel, c, ' / '.join(CATEGORIES)))

        tags = list_items(fm, 'tags') or []
        if not tags:
            errors.append('%s: tags 为空' % rel)
        elif len(tags) > 4:
            warns.append('%s: tags 有 %d 个，约定是 2-3 个（专栏 3-4）' % (rel, len(tags)))
        for t in tags:
            # 架构 既是分类也是主题标签（词表里本来就有），不在这里禁
            if t in ('技术', '笔记', '概念', '实践'):
                errors.append('%s: 分类名「%s」不能当标签用' % (rel, t))

        desc = scalar(fm, 'description') or ''
        if not desc:
            errors.append('%s: description 为空' % rel)

        # cover: 必须指向 source 下真实存在的文件
        cover = scalar(fm, 'cover') or ''
        if cover:
            local = os.path.join(args.site, cover.lstrip('/'))
            if not os.path.exists(local):
                errors.append('%s: cover 指向的文件不存在（%s）' % (rel, cover))
        elif draft:
            warns.append('%s: 草稿没有 cover（发布前记得补）' % rel)

        # 摘要：frontmatter 之后第一个 ## 之前应有 `> ` 引用块
        if not re.search(r'^\s*>', body, re.M):
            warns.append('%s: 正文开头没有 `> ` 摘要块' % rel)

        slug = os.path.splitext(os.path.basename(path))[0]
        slugs[slug].append(rel)
        title = scalar(fm, 'title') or ''
        if title:
            titles[title].append(rel)

    for slug, paths in slugs.items():
        if len(paths) > 1:
            errors.append('重复 slug「%s」: %s' % (slug, ', '.join(paths)))
    for title, paths in titles.items():
        if len(paths) > 1:
            errors.append('重复 title「%s」: %s' % (title, ', '.join(paths)))

    for e in errors:
        print('ERROR %s' % e)
    if args.verbose:
        for w in warns:
            print('WARN  %s' % w)

    print('\n检查 %d 篇，错误 %d 条，警告 %d 条' % (checked, len(errors), len(warns)))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
