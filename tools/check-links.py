# tools/check-links.py
# 构建后自查站内死链：扫描 public/ 下所有 HTML 的 href/src="/..."，逐个对照落盘文件。
# 只要有一条站内链接指向不存在的文件就返回 1，方便接进发布流程当下线闸门。
#
# 用法：
#   python tools/check-links.py           # 只报死链 + 统计
#   python tools/check-links.py -v        # 附上每个死链被哪些页面引用
#   python tools/check-links.py --root public
#
# 跳过：//协议相对、#锚点、mailto:、javascript:、tel:、data:，以及所有外部 http(s)

import argparse
import os
import re
import sys
import urllib.parse

SKIP_PREFIX = ('//', '#', 'mailto:', 'javascript:', 'tel:', 'data:')
LINK_RE = re.compile(r'(?:href|src)="([^"]+)"')


def collect(root):
    """返回 {站内链接: {引用它的页面}}"""
    links = {}
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not name.endswith('.html'):
                continue
            page = os.path.join(dirpath, name)
            try:
                html = open(page, encoding='utf-8', errors='ignore').read()
            except OSError:
                continue
            for m in LINK_RE.finditer(html):
                href = m.group(1)
                if not href.startswith('/') or href.startswith(SKIP_PREFIX):
                    continue
                rel = os.path.relpath(page, root).replace('\\', '/')
                links.setdefault(href, set()).add(rel)
    return links


def resolve(root, href):
    """把站内链接映射到 public/ 下的候选文件路径"""
    path = urllib.parse.unquote(href.split('#')[0].split('?')[0])
    if not path:
        return True
    clean = path.lstrip('/')
    cands = [os.path.join(root, clean, 'index.html')] if path.endswith('/') else [
        os.path.join(root, clean),
        os.path.join(root, clean, 'index.html'),
    ]
    return any(os.path.exists(c) for c in cands)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='public')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print('没找到 %s，先跑 npx hexo generate' % args.root)
        return 1

    links = collect(args.root)
    broken = {h: pages for h, pages in links.items() if not resolve(args.root, h)}

    for href in sorted(broken):
        if args.verbose:
            pages = sorted(broken[href])
            print('BROKEN %-46s <- %s%s' % (href, ', '.join(pages[:3]),
                                            ' …+%d' % (len(pages) - 3) if len(pages) > 3 else ''))
        else:
            print('BROKEN %s' % href)

    print('\n站内链接 %d 条，死链 %d 条' % (len(links), len(broken)))
    return 1 if broken else 0


if __name__ == '__main__':
    sys.exit(main())
