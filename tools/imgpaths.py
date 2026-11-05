# tools/imgpaths.py
# 封面落盘目录的推导规则（两个封面脚本共用）
#
#   cover: /img/<年>/<月>/<key>.jpg   ← 文章封面，跟着它所属文章的年/月目录走
#   source/img/common/<key>.jpg       ← 站点级图片（默认封面、banner），不跟文章
#
# 依据是「哪篇文章引用了这张图」，所以文章挪文件夹、改年月，封面目录会自动跟上；
# 只有新文章还没写 frontmatter 时才需要 --dir 手动指定。

import glob
import os

IMG_DIR = 'source/img'
COMMON_DIR = os.path.join(IMG_DIR, 'common')
POSTS_DIR = 'source/_posts'


def cover_dir(key, posts_dir=POSTS_DIR):
    """返回 key 这张封面该落到的目录：文章所在年/月，找不到文章则 common"""
    for f in glob.glob(os.path.join(posts_dir, '*', '*', '*.md')):
        try:
            txt = open(f, encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        if '%s.jpg' % key in txt:
            rel = os.path.relpath(f, posts_dir)
            year, month = rel.split(os.sep)[:2]
            return os.path.join(IMG_DIR, year, month)
    return COMMON_DIR
