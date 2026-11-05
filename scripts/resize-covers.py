# scripts/resize-covers.py
# 把 source/img 下的封面压到 900 宽（封面比例 4:3），减小体积
#
# 用法：python scripts/resize-covers.py
# 可选：python scripts/resize-covers.py --only cover-hono,cover-koa

import io
import os
import sys
import glob

TARGET_W = 900
QUALITY = 85
IMG_DIR = 'source/img'

only = None
if '--only' in sys.argv:
    only = sys.argv[sys.argv.index('--only') + 1].split(',')

# 封面文件：cover-*.jpg、banner.jpg，以及几篇专题封面
names = []
for p in glob.glob(os.path.join(IMG_DIR, '*.jpg')):
    base = os.path.splitext(os.path.basename(p))[0]
    if base.startswith('cover-') or base in ('banner', 'agent-state-machines',
                                             'ai-critical-thinking', 'super-agent-designs'):
        names.append(p)
if only:
    wanted = set(only)
    names = [p for p in names if os.path.splitext(os.path.basename(p))[0] in wanted]

if not names:
    print('没找到要处理的图片')
    sys.exit(0)

try:
    from PIL import Image
except ImportError:
    print('错误：需要 Pillow。先跑：  pip install Pillow')
    sys.exit(1)

print('处理', len(names), '张')
for p in sorted(names):
    before = os.path.getsize(p)
    im = Image.open(p).convert('RGB')
    if im.width > TARGET_W:
        im = im.resize((TARGET_W, round(im.height * TARGET_W / im.width)), Image.LANCZOS)
    im.save(p, 'JPEG', quality=QUALITY, optimize=True, progressive=True)
    after = os.path.getsize(p)
    print('  %-28s %6dKB -> %5dKB' % (os.path.basename(p), before // 1024, after // 1024))

print('完成')
