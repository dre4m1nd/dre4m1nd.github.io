# tools/make-covers.py
# 用 PIL 合成博客封面：白底 + 官方 logo + 英文名 + 中文副标题
# 纯本地生成，不依赖浏览器/生图 API。全站技术笔记统一这一套版式。
#
# 用法：
#   python tools/make-covers.py                  # 全部
#   python tools/make-covers.py --only cover-hono,cover-zod
#   python tools/make-covers.py --preview        # 只出 PNG 预览到 .tmp-img/，不覆盖 source/img
#
# logo 素材在 tools/logos/（simple-icons 的 SVG 已栅格化成同色 PNG；
# MyBatis 用官方 GitHub 头像，Koa 用官方 wordmark）

import argparse
import io
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 960          # 渲染尺寸（4:3），最后压到 OUT_W
OUT_W = 900
QUALITY = 85

BLUE = (66, 90, 239)      # 主题蓝 #425AEF
INK = (31, 45, 61)        # #1F2D3D
GREY = (138, 148, 166)
CHIP_LINE = (205, 214, 250)

LOGO_DIR = 'tools/logos'

FONT_LATIN_BOLD = ['C:/Windows/Fonts/segoeuib.ttf', 'C:/Windows/Fonts/arialbd.ttf']
FONT_CN_REG = ['C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf']
FONT_MONO = ['C:/Windows/Fonts/consola.ttf', 'C:/Windows/Fonts/consolab.ttf']


def pick(cands, size):
    for p in cands:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def load_logo(name, color):
    """读 tools/logos/<name>.png（透明底），裁边后染成 color"""
    im = Image.open(os.path.join(LOGO_DIR, name + '.png')).convert('RGBA')
    im = im.crop(im.getchannel('A').getbbox())
    if color is not None:                           # 单色重绘，保留边缘抗锯齿
        solid = Image.new('RGBA', im.size, color)
        solid.putalpha(im.getchannel('A'))
        im = solid
    return im


def fit(im, max_w, max_h):
    r = min(max_w / im.width, max_h / im.height)
    return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)


def text_w(draw, text, font):
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


def shrink_to(draw, text, cands, size, max_w):
    font = pick(cands, size)
    while size > 18 and text_w(draw, text, font) > max_w:
        size -= 2
        font = pick(cands, size)
    return font


def render(item, out_path):
    canvas = Image.new('RGB', (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    brand = item.get('color') or INK
    tag_font = pick(FONT_CN_REG, 23)

    # ── 左上角分类标签 ──
    tag = item.get('tag')
    if tag:
        pad_x, pad_y = 18, 9
        tw = text_w(draw, tag, tag_font)
        tb = draw.textbbox((0, 0), tag, font=tag_font)
        th = tb[3] - tb[1]
        x0, y0 = 64, 56
        draw.rounded_rectangle([x0, y0, x0 + tw + pad_x * 2, y0 + th + pad_y * 2 + 6],
                               radius=5, outline=CHIP_LINE, width=1)
        draw.text((x0 + pad_x, y0 + pad_y - tb[1] + 2), tag, font=tag_font, fill=BLUE)

    # ── 中部：logo（可多个）+ 英文名 + 中文副标题 + 品牌色横线 ──
    names = item.get('logos') or [item['logo']]
    color = item.get('logo_color', brand)
    if item.get('logo_color') is None and item.get('color') is None:
        color = INK
    logos = [load_logo(n, color if len(names) == 1 else (item.get('logo_color') or INK)) for n in names]

    if len(logos) == 1:
        logos = [fit(logos[0], 560, 300)]
        gap_logo = 0
    else:                                           # 多 logo 横排（如框架横评）
        logos = [fit(l, 190, 170) for l in logos]
        gap_logo = 56

    name = item.get('name', '')
    sub = item.get('sub', '')

    name_font = shrink_to(draw, name, FONT_LATIN_BOLD, 96, 900) if name else None
    sub_font = shrink_to(draw, sub, FONT_CN_REG, 42, 940) if sub else None

    gap1 = 58 if name else 96
    gap2 = 30 if sub else 0
    gap3 = 60

    nb = draw.textbbox((0, 0), name, font=name_font) if name else (0, 0, 0, 0)
    name_h = nb[3] - nb[1] if name else 0
    sb = draw.textbbox((0, 0), sub, font=sub_font) if sub else (0, 0, 0, 0)
    sub_h = sb[3] - sb[1] if sub else 0

    logo_h = max(l.height for l in logos)
    logo_w = sum(l.width for l in logos) + gap_logo * (len(logos) - 1)
    total = logo_h + gap1 + name_h + gap2 + sub_h + gap3 + 4
    y = (H - total) // 2

    x = (W - logo_w) // 2
    for l in logos:
        canvas.paste(l, (x, y + (logo_h - l.height) // 2), l)
        x += l.width + gap_logo
    y += logo_h + gap1

    if name:
        draw.text(((W - text_w(draw, name, name_font)) / 2, y - nb[1]), name, font=name_font, fill=INK)
        y += name_h + gap2

    if sub:
        draw.text(((W - text_w(draw, sub, sub_font)) / 2, y - sb[1]), sub, font=sub_font, fill=GREY)
        y += sub_h

    y += gap3
    draw.rectangle([(W - 64) // 2, y, (W + 64) // 2, y + 5], fill=brand)

    # ── 右下角域名 ──
    site = item.get('site')
    if site:
        site_font = pick(FONT_MONO, 20)
        sbx = draw.textbbox((0, 0), site, font=site_font)
        draw.text((W - 64 - (sbx[2] - sbx[0]), H - 56 - (sbx[3] - sbx[1])),
                  site, font=site_font, fill=(196, 202, 212))

    if OUT_W != W:
        canvas = canvas.resize((OUT_W, round(H * OUT_W / W)), Image.LANCZOS)
    canvas.save(out_path, 'JPEG', quality=QUALITY, optimize=True, progressive=True)
    return canvas


# ── 封面清单：key 就是 source/img/<key>.jpg ──
COVERS = {
    'cover-express': dict(logo='express', name='Express', color=INK,
                          tag='技术 · Node.js', site='expressjs.com',
                          sub='从 10 行服务到可上线的结构'),
    'cover-koa': dict(logo='koa', name='', color=INK,
                      tag='技术 · Node.js', site='koajs.com',
                      sub='从洋葱模型到可上线工程'),
    'cover-fastify': dict(logo='fastify', name='Fastify', color=INK,
                          tag='技术 · Node.js', site='fastify.dev',
                          sub='Schema 驱动：校验、序列化、钩子'),
    'cover-hono': dict(logo='hono', name='Hono', color=(227, 96, 2),
                       tag='技术 · TypeScript', site='hono.dev',
                       sub='Web 标准 + 类型安全 RPC'),
    'cover-nestjs': dict(logo='nestjs', name='NestJS', color=(224, 35, 78),
                         tag='技术 · TypeScript', site='nestjs.com',
                         sub='模块、DI、守卫、管道、拦截器'),
    'cover-prisma': dict(logo='prisma', name='Prisma', color=(45, 55, 72),
                         tag='技术 · ORM', site='prisma.io',
                         sub='Schema-first，类型安全的 Node ORM'),
    'cover-drizzle': dict(logo='drizzle', name='Drizzle', color=INK,
                          tag='技术 · ORM', site='orm.drizzle.team',
                          sub='零运行时，贴近原生 SQL'),
    'cover-zod': dict(logo='zod', name='Zod', color=(64, 138, 255),
                      tag='技术 · TypeScript', site='zod.dev',
                      sub='运行时校验 + 类型推断'),
    'cover-mybatis': dict(logo='mybatis', name='MyBatis', color=None,
                          tag='技术 · Java', site='mybatis.org',
                          sub='SQL 握在自己手里，映射交给框架'),
    'cover-linux': dict(logo='linux', name='Linux', color=INK,
                        tag='技术 · 命令行', site='linux.org',
                        sub='按场景分类的命令速查'),
    'cover-compare': dict(logos=['express', 'koa', 'fastify', 'hono', 'nestjs'],
                          name='Web Frameworks', color=BLUE,
                          tag='笔记 · 选型', site='nodejs.org',
                          sub='Express / Koa / Fastify / Hono 怎么选'),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--preview', action='store_true')
    args = ap.parse_args()

    only = {s.strip() for s in args.only.split(',') if s.strip()}
    keys = [k for k in COVERS if not only or k in only]
    if not keys:
        print('没有匹配的封面 key:', args.only)
        return 1

    out_dir = '.tmp-img' if args.preview else 'source/img'
    os.makedirs(out_dir, exist_ok=True)
    for k in keys:
        ext = 'png' if args.preview else 'jpg'
        path = os.path.join(out_dir, k + '.' + ext)
        canvas = render(COVERS[k], path)
        print('saved %-22s %s %dKB' % (os.path.basename(path), canvas.size,
                                      os.path.getsize(path) // 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
