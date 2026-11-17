# tools/magpie-covers.py
# 用 Magpie 的 image MCP（tools/magpie_mcp.py）生成博客封面
#
# 只负责「没有官方 logo 可用」的文章（算法、AI 笔记、项目拆解、默认封面）；
# 框架/工具类文章的封面走 tools/make-covers.py（白底 + 官方 logo，沿用品牌色）。
#
# 配色硬约束：整体暖色自然系（木棕、奶油、米白、灰绿、陶土），严禁蓝紫主调或冷青色。
# doubao 会默认蓝紫洗，所以配色要求写两遍：STYLE 里锁一次，每条 prompt 再点名一次。
# 生成后压到 900x675（4:3）quality 85。
# 落盘目录：文章封面 source/img/<年>/<月>/，站点级图片 source/img/common/
# （按「哪篇文章引用了这张封面」自动定位，见 tools/imgpaths.py；文章还没写
#   frontmatter 时加 --dir <目录>）
#
# 生成模型：默认 loomy/doubao-seedream-5-lite（讯飞 Loomy 通道），可用 --model 覆盖；
# 不使用腾讯系模型（OpenRouter 系列区域受限不可用）。
#
# 用法：
#   python tools/magpie-covers.py                  # 全部
#   python tools/magpie-covers.py --only cover-kmp # 指定几张
#   python tools/magpie-covers.py --only <key> --dir source/img/2026/12
#   python tools/magpie-covers.py --dry-run        # 只试第一张

import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

from imgpaths import cover_dir
from magpie_mcp import MagpieImage, DEFAULT_MODEL

OUT_W, OUT_H = 900, 675
QUALITY = 85
# 风格模板：暖色自然系 + 扁平矢量，整幅完整入画。
# 文字由脚本在本地合成（不交给模型画）——本地叠字字形一定正确，不会错字。
STYLE = ('warm natural lifelike colors, earthy palette of wood brown, cream, beige, sage green, '
         'terracotta and soft warm whites, a soft cohesive palette, '
         'clean bright background with generous empty space around the subject, '
         'minimal flat vector illustration, concrete recognizable objects in a clear real-world scene '
         '(a machine, a device, a tool, physical props), never abstract node graphs, arrows, or color-block patterns, '
         'zoomed out wide shot, entire composition fully visible '
         'inside the frame, centered with wide margins on all sides, nothing cropped, '
         'no full-image blue or purple wash, no cold cyan tones, no neon colors, no muddy gray, '
         'no 3d render, no photorealistic, no text, no letters, no watermark, no signature')

# ── 图内短标签（可选；本地渲染，英文/中文都不会错字）──
# 只放 1 条、尽量短（英文单词或 2~4 个汉字），位置在左上角，和 logo 封面的分类 chip 呼应。
LABELS = {
    'pi-agent-loop': 'AGENT',
    'pi-model-layer': 'MODEL',
    'pi-tool-pipeline': 'TOOLS',
    'pi-message-system': 'MESSAGE',
    'pi-context-engineering': 'CONTEXT',
    'pi-session-tree': 'SESSION',
    'pi-extension-events': 'EVENTS',
    'pi-tui-rendering': 'RENDER',
    'json-family-protocols': 'JSON',
}

# ── 底部小标题（TEXTS 里的 key = PROMPTS 里的 key）──
TEXTS = {
    'pi-agent-loop':         'Agent 循环',
    'pi-model-layer':        '模型调用层',
    'pi-tool-pipeline':      '工具管道',
    'pi-message-system':     '消息系统',
    'pi-context-engineering':     '上下文工程',
    'pi-session-tree':     '会话管理',
    'pi-extension-events':     '扩展与事件',
    'pi-tui-rendering':     '终端渲染',
    'json-family-protocols':     'JSON 家族辨析',
}

PROMPTS = {
    'pi-agent-loop':    'minimal composition, a single small subject centered with very large empty margins on all four sides, a small golden gear with a smooth flywheel driving a tiny chain, an engine in motion concept, warm wood tones and cream background, ' + STYLE,
    'pi-model-layer':    'minimal composition, a single small subject centered with very large empty margins on all four sides, a translator figure at a small desk working on one document, multi-format translation concept, warm wood tones and cream background, ' + STYLE,
    'pi-tool-pipeline':    'flat vector illustration of a neat workbench with a simple robotic arm holding a wrench above a small workpiece, a few hand tools (screwdriver, wrench, pliers) neatly arranged beside it, tool use concept, warm wood workbench tones, ' + STYLE,
    'pi-message-system':    'flat vector illustration of a single open envelope floating in the center of a plain background, slightly open to reveal a richly detailed inner document with colorful stamps and handwritten notes, a single centered subject with generous empty space around all edges, warm cream paper tones, ' + STYLE,
    'pi-context-engineering':    'minimal composition, a single small subject centered with very large empty margins on all four sides, a paper funnel pressing a stack of loose documents down into one small neat summary card, context compression concept, warm cream paper tones, ' + STYLE,
    'pi-session-tree':    'minimal composition, a small subject centered with huge empty space on all four sides, nothing near the frame edges, a single bare stylized tree with symmetrically branching wooden branches and small round warm-colored fruits (amber, terracotta, olive) hanging at each branch tip, growth and branching concept, on a pure white background, bright white, ' + STYLE,
    'pi-extension-events':    'minimal composition, a small subject centered with huge empty space on all four sides, nothing near the frame edges, a small vintage wooden radio with a few hanging amber light bulbs connected by thin wires, signal and connection concept, warm amber glow, on a pure white background, bright white, ' + STYLE,
    'pi-tui-rendering':    'minimal composition, a single small subject centered with very large empty margins on all four sides, a small old-style desktop computer with a green-screen display showing neat monochrome text lines on it, warm beige retro computer tones, ' + STYLE,
    'json-family-protocols':    'minimal composition, a small subject centered with huge empty space on all four sides, nothing near the frame edges, a wooden shelf with five small differently shaped glass jars, each jar holding a different kind of warm-colored small items (paper slips, wooden beads, brass gears, rubber stamps), sorting and comparing concept, on a pure white background, bright white, ' + STYLE,
}

CAPTION_FONT = 'C:/Windows/Fonts/msyhbd.ttc'
CAPTION_INK = (31, 45, 61)      # #1F2D3D
CAPTION_ACCENT = (66, 90, 239)  # #425AEF


def draw_caption(im, text):
    """底部居中叠一行小标题 + 上方一条短蓝线，和 logo 封面的版式呼应"""
    font = ImageFont.truetype(CAPTION_FONT, max(26, im.width // 20))
    draw = ImageDraw.Draw(im)
    box = draw.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    x = (im.width - tw) / 2 - box[0]
    y = im.height - 12 - th - box[1]
    draw.rectangle([(im.width - 44) / 2, y - 16, (im.width + 44) / 2, y - 13], fill=CAPTION_ACCENT)
    draw.text((x, y), text, font=font, fill=CAPTION_INK)
    return im


def draw_label(im, text):
    """左上角叠一个短标签（本地渲染），和 logo 封面左上角的分类 chip 呼应"""
    scale = im.width / 900
    font = ImageFont.truetype(CAPTION_FONT, max(18, int(23 * scale)))
    draw = ImageDraw.Draw(im)
    pad_x, pad_y = int(16 * scale), int(8 * scale)
    box = draw.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    x0, y0 = int(56 * scale), int(38 * scale)
    draw.rounded_rectangle(
        [x0, y0, x0 + tw + pad_x * 2, y0 + th + pad_y * 2],
        radius=int(5 * scale), outline=(205, 214, 250), width=max(1, int(scale)))
    draw.text((x0 + pad_x - box[0], y0 + pad_y - box[1]), text, font=font, fill=(66, 90, 239))
    return im


def postprocess(raw_path, out_path, text, label):
    """下载 → 中心裁成 4:3 → 压到 900x675 → 叠小标题 → 落盘，
    返回 (尺寸, KB, 平均亮度, 内容留白比例)"""
    im = Image.open(raw_path).convert('RGB')
    # 部分模型只出方形图：中心裁成 4:3（prompt 已要求居中+宽留白，裁剪安全）
    w, h = im.size
    if w / h > OUT_W / OUT_H:
        new_w = round(h * OUT_W / OUT_H)
        x0 = (w - new_w) // 2
        im = im.crop((x0, 0, x0 + new_w, h))
    elif h / w > OUT_H / OUT_W:
        new_h = round(w * OUT_H / OUT_W)
        y0 = (h - new_h) // 2
        im = im.crop((0, y0, w, y0 + new_h))
    if im.width != OUT_W:
        im = im.resize((OUT_W, round(im.height * OUT_W / im.width)), Image.LANCZOS)

    # 指标先在插画本体上量（小标题是本地叠的，不算内容留白）
    grey = im.convert('L')
    mean = sum(grey.getdata()) / (grey.width * grey.height)
    box = grey.point(lambda v: 255 if v < 235 else 0).getbbox()
    margin = min(box[0], box[1], im.width - box[2], im.height - box[3]) / min(im.width, im.height) if box else 1.0

    if label:
        im = draw_label(im, label)
    if text:
        im = draw_caption(im, text)
    im.save(out_path, 'JPEG', quality=QUALITY, optimize=True, progressive=True)
    return im.size, os.path.getsize(out_path) // 1024, mean, margin


def main():
    args = sys.argv[1:]
    only = args[args.index('--only') + 1].split(',') if '--only' in args else None
    dry = '--dry-run' in args
    model = args[args.index('--model') + 1] if '--model' in args else DEFAULT_MODEL

    targets = [k for k in PROMPTS if not only or k in only]
    if dry:
        targets = targets[:1]

    dir_arg = args[args.index('--dir') + 1] if '--dir' in args else ''

    ok = fail = 0

    with MagpieImage() as magpie:
        for slug in targets:
            out_dir = dir_arg or cover_dir(slug)
            os.makedirs(out_dir, exist_ok=True)
            dest = os.path.join(out_dir, slug + '.jpg')
            tmp = os.path.join(out_dir, slug + '.raw.png')
            try:
                magpie.generate(PROMPTS[slug], tmp, model=model)
                size, kb, mean, margin = postprocess(tmp, dest, TEXTS.get(slug, ''), LABELS.get(slug, ''))
                ok += 1
                warn = []
                if mean < 150:
                    warn.append('底色偏暗(亮度%.0f)' % mean)
                if margin < 0.03:
                    warn.append('构图贴边(留白%.1f%%)' % (margin * 100))
                print('OK   %-30s %s %3dKB 亮度%.0f 留白%.0f%%%s%s%s' % (
                    dest.replace('\\', '/'), size, kb, mean, margin * 100,
                    ('  ⚠️ ' + '、'.join(warn) + '，改 prompt 重跑该张') if warn else '',
                    ('  小标题: ' + TEXTS.get(slug, '')) if TEXTS.get(slug) else '',
                    ('  标签: ' + LABELS.get(slug, '')) if LABELS.get(slug) else ''))
            except Exception as e:
                fail += 1
                import traceback
                traceback.print_exc()
                print('FAIL', slug, str(e)[:200])
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
            time.sleep(0.4)

    print('\n完成：%d 成功 / %d 失败' % (ok, fail))
    print('下一步：目测检查后 npx hexo clean && npx hexo generate，再 git 提交发布')


if __name__ == '__main__':
    main()
