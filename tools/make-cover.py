# tools/make-cover.py
# 用 PIL 合成博客封面：白底 + 框架 logo + 标题 + 副标题
# 纯本地生成，不依赖浏览器/API
#
# 用法：
#   python tools/make-cover.py --logo a.png --title Koa --sub "从洋葱模型到可上线工程" --out source/img/cover-koa.jpg
#   python tools/make-cover.py --logo a.png --title Koa --sub "..." --tag "技术 · Backend" --no 03

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 960
BLUE = (66, 90, 239)
INK = (31, 45, 61)
GREY = (133, 133, 133)
LIGHT = (238, 238, 238)

# Windows 字体候选
FONT_BOLD = [
    'C:/Windows/Fonts/msyhbd.ttc',
    'C:/Windows/Fonts/msyh.ttc',
    'C:/Windows/Fonts/simhei.ttf',
]
FONT_REG = [
    'C:/Windows/Fonts/msyh.ttc',
    'C:/Windows/Fonts/simhei.ttf',
]
FONT_MONO = [
    'C:/Windows/Fonts/msyh.ttc',
    'C:/Windows/Fonts/simhei.ttf',
]


def pick(cands, size):
    for p in cands:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def trim(im):
    """裁掉白色边框"""
    im = im.convert('RGBA')
    bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
    diff = Image.alpha_composite(bg, im).convert('RGB')
    # 找非白边界
    px = diff.load()
    w, h = diff.size
    left, top, right, bottom = w, h, 0, 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if r < 245 or g < 245 or b < 245:
                if x < left: left = x
                if x > right: right = x
                if y < top: top = y
                if y > bottom: bottom = y
    if right <= left or bottom <= top:
        return im
    return im.crop((left, top, right + 1, bottom + 1))


def fit(im, max_w, max_h):
    r = min(max_w / im.width, max_h / im.height)
    return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)


def draw_center_text(draw, text, font, fill, y, width=W):
    box = draw.textbbox((0, 0), text, font=font)
    tw = box[2] - box[0]
    draw.text(((width - tw) / 2, y), text, font=font, fill=fill)
    return box[3] - box[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--logo', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--sub', default='')
    ap.add_argument('--tag', default='技术 · Backend')
    ap.add_argument('--no', default='')
    ap.add_argument('--out', required=True)
    ap.add_argument('--logo-height', type=int, default=300)
    args = ap.parse_args()

    canvas = Image.new('RGB', (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    # logo
    logo = None
    if os.path.exists(args.logo):
        raw = Image.open(args.logo)
        logo = trim(raw)
        logo = fit(logo, 620, args.logo_height)

    title_font = pick(FONT_BOLD, 132)
    sub_font = pick(FONT_REG, 36)
    tag_font = pick(FONT_MONO, 20)
    no_font = pick(FONT_BOLD, 96)

    # 垂直排布：logo + 60 + title + 24 + sub + 52 + rule
    gap1, gap2, gap3 = 60, 24, 52
    logo_h = logo.height if logo else 0
    t_box = draw.textbbox((0, 0), args.title, font=title_font)
    title_h = t_box[3] - t_box[1]
    s_box = draw.textbbox((0, 0), args.sub, font=sub_font) if args.sub else (0, 0, 0, 0)
    sub_h = s_box[3] - s_box[1] if args.sub else 0
    total = logo_h + gap1 + title_h + (gap2 + sub_h if args.sub else 0) + gap3 + 4
    y = (H - total) // 2

    if logo:
        canvas.paste(logo, ((W - logo.width) // 2, y), logo if logo.mode == 'RGBA' else None)
        y += logo_h + gap1

    draw_center_text(draw, args.title, title_font, INK, y)
    y += title_h + 14

    if args.sub:
        y += gap2
        draw_center_text(draw, args.sub, sub_font, GREY, y)
        y += sub_h

    y += gap3
    draw.rectangle([(W - 120) // 2, y, (W + 120) // 2, y + 4], fill=BLUE)

    # 左上角标签
    if args.tag:
        pad_x, pad_y = 16, 8
        tb = draw.textbbox((0, 0), args.tag, font=tag_font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        x0, y0 = 64, 56
        draw.rounded_rectangle([x0, y0, x0 + tw + pad_x * 2, y0 + th + pad_y * 2 + 6],
                               radius=4, outline=(205, 214, 250), width=1)
        draw.text((x0 + pad_x, y0 + pad_y), args.tag, font=tag_font, fill=BLUE)

    # 右下角序号
    if args.no:
        nb = draw.textbbox((0, 0), args.no, font=no_font)
        draw.text((W - 72 - (nb[2] - nb[0]), H - 56 - (nb[3] - nb[1]) - 10),
                  args.no, font=no_font, fill=LIGHT)

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    canvas.save(args.out, 'JPEG', quality=88, optimize=True, progressive=True)
    print('saved', args.out, canvas.size, os.path.getsize(args.out) // 1024, 'KB')


if __name__ == '__main__':
    main()
