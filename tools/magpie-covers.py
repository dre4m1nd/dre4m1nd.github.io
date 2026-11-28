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
# 生成模型：默认 workbuddy-ai/hy-image-3.5（2026-11 实测：loomy/* 全 406、openrouter/* 全 402，
# workbuddy 两条通道可用），可用 --model 覆盖；不使用腾讯系模型（OpenRouter 系列区域受限不可用）。
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
         'clean bright light background, the illustration set on a plain light background '
         'with a clear band of background color around the subject on all four sides, '
         'minimal flat vector illustration, concrete recognizable objects in a clear real-world scene '
         '(a machine, a device, a tool, physical props), never abstract node graphs, arrows, or color-block patterns, '
         'clear wide composition, the subject centered and prominent with a balanced margin, '
         'entire composition fully visible inside the frame, centered, nothing cropped, '
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
    'pi-policy-gate': 'POLICY',
    'spring-filter-interceptor': 'FILTER',
    'json-family-protocols': 'JSON',
    'agent-memory-components': 'MEMORY',
    'agent-state-machines': 'STATE',
    'ai-critical-thinking': 'READ',
    'cover-code-review': 'REVIEW',
    'super-agent-designs': 'AGENT',
    'agents-going-async': 'ASYNC',
    'design-patterns-creational': 'CREATE',
    'design-patterns-behavioral': 'BEHAVE',
    'design-patterns-structural': 'STRUCT',
    'cover-binary': 'SEARCH',
    'cover-cipherlens': 'SECURITY',
    'cover-kmp': 'KMP',
    'cover-quicksort': 'SORT',
    'claude-docs-chaos-loop': 'CHAOS',
    'agent-session-concurrency': 'SESSION',
    'spring-transaction-propagation': 'TX',
    'mcp-transports': 'MCP',
    'mcp-server': 'SERVER',
    'virtual-threads': 'JAVA',
    'multi-agent-worktree': 'GIT',
    'spring-aop-proxy': 'AOP',
    'jvm-gc-g1-zgc': 'GC',
    'java-locks': 'LOCK',
    'node-event-loop': 'LOOP',
    'git-rebase-vs-merge': 'REBASE',
    'mysql-isolation-levels': 'MYSQL',
    'mcp-client': 'CLIENT',
    'agent-tool-idempotency': 'RETRY',
}

# ── 底部小标题（TEXTS 里的 key = PROMPTS 里的 key）──
TEXTS = {
    'pi-agent-loop':         'Agent 循环',
    'pi-model-layer':        '模型调用层',
    'pi-tool-pipeline':      '工具管道',
    'pi-message-system':     '消息系统',
    'pi-context-engineering':     '上下文工程',
    'agent-memory-components':     'Agent 记忆',
    'pi-session-tree':     '会话管理',
    'pi-extension-events':     '扩展与事件',
    'pi-tui-rendering':     '终端渲染',
    'pi-policy-gate':     '权限闸门',
    'spring-filter-interceptor':     '过滤器与拦截器',
    'json-family-protocols':     'JSON 家族辨析',
    'agent-state-machines':     'Agent 状态机',
    'ai-critical-thinking':     '批判性思考',
    'cover-code-review':     '代码审查',
    'super-agent-designs':     'Super Agent',
    'agents-going-async':     '异步编排',
    'design-patterns-creational':     '创建型模式',
    'design-patterns-behavioral':     '行为型模式',
    'design-patterns-structural':     '结构型模式',
    'cover-binary':     '二分查找',
    'cover-cipherlens':     '项目拆解',
    'cover-kmp':     'KMP 算法',
    'cover-quicksort':     '快速排序',
    'claude-docs-chaos-loop':     '混沌循环',
    'agent-session-concurrency':     '会话并发',
    'spring-transaction-propagation':     '事务传播',
    'mcp-transports':     'MCP 传输层',
    'mcp-server':     'MCP 服务端',
    'virtual-threads':     '虚拟线程',
    'multi-agent-worktree':     '多 Agent 工作区',
    'spring-aop-proxy':     'AOP 代理边界',
    'jvm-gc-g1-zgc':     'GC 停顿对比',
    'java-locks':     '并发锁实测',
    'node-event-loop':     '事件循环',
    'git-rebase-vs-merge':     '分支整合',
    'mysql-isolation-levels':     '事务隔离',
    'mcp-client':     'MCP 客户端',
    'agent-tool-idempotency':     '工具幂等',
}

PROMPTS = {
    'pi-agent-loop':    'minimal composition, a small golden gear with a smooth flywheel driving a tiny chain, an engine in motion concept, warm wood tones and cream background, ' + STYLE,
    'pi-model-layer':    'minimal composition, a translator figure at a small desk working on one document, multi-format translation concept, warm wood tones and cream background, ' + STYLE,
    'pi-tool-pipeline':    'flat vector illustration of a neat workbench with a simple robotic arm holding a wrench above a small workpiece, a few hand tools (screwdriver, wrench, pliers) neatly arranged beside it, tool use concept, warm wood workbench tones, ' + STYLE,
    'pi-message-system':    'flat vector illustration of a single open envelope floating in the center of a plain background, slightly open to reveal a richly detailed inner document with colorful stamps and handwritten notes, a single centered subject with generous empty space around all edges, warm cream paper tones, ' + STYLE,
    'pi-context-engineering':    'minimal composition, a paper funnel pressing a stack of loose documents down into one small neat summary card, context compression concept, warm cream paper tones, ' + STYLE,
    'pi-session-tree':    'minimal composition, a single bare stylized tree with symmetrically branching wooden branches and small round warm-colored fruits (amber, terracotta, olive) hanging at each branch tip, growth and branching concept, on a pure white background, bright white, ' + STYLE,
    'pi-extension-events':    'minimal composition, a small vintage wooden radio with a few hanging amber light bulbs connected by thin wires, signal and connection concept, warm amber glow, on a pure white background, bright white, ' + STYLE,
    'pi-tui-rendering':    'minimal composition, a small old-style desktop computer with a green-screen display showing neat monochrome text lines on it, warm beige retro computer tones, ' + STYLE,
    'pi-policy-gate':    'minimal composition, a sturdy small wooden gate with a brass padlock and a stack of stamped paper passes on a side table, access control and audit concept, warm brass and wood tones, on a pure white background, bright white, ' + STYLE,
    'spring-filter-interceptor':    'minimal composition, a small wooden sieve with a mesh screen beside a small wooden turnstile gate, filtering and gating concept, warm wood and brass tones, on a pure white background, bright white, ' + STYLE,
    'json-family-protocols':    'minimal composition, a wooden shelf with five small differently shaped glass jars, each jar holding a different kind of warm-colored small items (paper slips, wooden beads, brass gears, rubber stamps), sorting and comparing concept, on a pure white background, bright white, ' + STYLE,
    'agent-state-machines':    'minimal composition, a small mechanical relay control panel with a few levers and warm indicator lights, deterministic control concept, on a pure white background, bright white, ' + STYLE,
    'ai-critical-thinking':    'minimal composition, a person sitting at a small desk reading an open book under a warm desk lamp, deep thinking concept, warm wood desk tones, on a pure white background, bright white, ' + STYLE,
    'cover-code-review':    'minimal composition, a paper checklist with a magnifying glass and a red rubber stamp resting on it, review concept, warm cream paper tones, on a pure white background, bright white, ' + STYLE,
    'super-agent-designs':    'minimal composition, a small self-driving rover with sensors on a little track, autonomous system concept, warm metal and wood tones, on a pure white background, bright white, ' + STYLE,
    'agents-going-async':    'minimal composition, a small control desk with one big screen and one small worker device side by side connected by a cable, coordination concept, warm wood desk tones, on a pure white background, bright white, ' + STYLE,
    'design-patterns-creational':    'minimal composition, a small factory machine with a conveyor belt carrying small products off the end, creation concept, warm metal and wood tones, on a pure white background, bright white, ' + STYLE,
    'agent-memory-components':    'minimal composition, a small cute robot at a small desk sorting a stack of memory cards into a wooden filing cabinet, agent memory organizing concept, warm wood cabinet tones and warm metal robot tones, on a pure white background, bright white, ' + STYLE,
    'design-patterns-behavioral':    'minimal composition, a row of small brown birds perched side by side on a short wooden branch, coordinated group concept, warm wood branch tones, on a pure white background, bright white, ' + STYLE,
    'cover-binary':    'minimal composition, a small brass balance scale with two pans holding tiny weights, searching and comparing concept, warm brass and wood tones, on a pure white background, bright white, ' + STYLE,
    'cover-cipherlens':    'minimal composition, a small brass padlock with a key and a wooden lockbox, security concept, warm brass and wood tones, on a pure white background, bright white, ' + STYLE,
    'cover-kmp':    'minimal composition, a magnifying glass examining a long strip of paper with small pattern marks, pattern matching concept, warm cream paper tones, on a pure white background, bright white, ' + STYLE,
    'cover-quicksort':    'minimal composition, a row of wooden blocks sorted by height from short to tall on a table, sorting concept, warm wood block tones, on a pure white background, bright white, ' + STYLE,
    'claude-docs-chaos-loop':    'minimal composition, a small cute robot holding a mallet testing a row of small wooden server boxes, one box rattling, stress testing concept, warm beige and wood tones, on a pure white background, bright white, ' + STYLE,
    'agent-session-concurrency':    'flat vector illustration of a narrow single-plank wooden footbridge over a small dry ditch, with one small wooden handcart waiting at each end facing the bridge, the two carts clearly too wide to pass each other, a few loose planks and a coil of rope on the ground beside it, single-file access concept, warm oak and terracotta tones, ' + STYLE,
    'spring-transaction-propagation':    'flat vector illustration of a small wooden balance scale with two pans, one pan holding a stack of paper ledgers and a brass pen, the other pan holding a few brass coins, the scale resting on a plain surface, commitment concept, warm wood and brass tones, ' + STYLE,
    'mcp-transports':    'flat vector illustration of a short open wooden pipe with a folded paper document sliding in through one end and sliding out the opposite end, a small brass toggle beside the pipe, two-way message exchange concept, warm wood and brass tones, ' + STYLE,
    'mcp-server':    'flat vector illustration on a pure white background, a three-tier wooden tool rack resting on a pale wooden workbench, the rack centered and taking up the middle of the frame, a clear margin of white background around all four sides, nothing touching the frame edges, a hammer resting on the top shelf, a coiled measuring tape on the middle shelf, a small neat stack of paper sticky notes on the bottom shelf, three kinds of capability neatly organized concept, warm wood and paper tones, ' + STYLE,
    'virtual-threads':    'flat vector illustration on a pure white background, a wooden dock centered with many small wooden rowboats tied side by side along it in a neat row, and only two larger wooden boats moored further out beyond the dock, a clear margin of white background around all four sides, nothing touching the frame edges, crowded dock with plenty of room concept, warm wood and cream tones, ' + STYLE,
    'multi-agent-worktree':    'flat vector illustration on a pure white background, two small wooden workbenches placed side by side, each with its own vise and hand tools, an open toolbox sitting between them, the benches centered with a clear margin of white background around all four sides, nothing touching the frame edges, separate workspaces sharing supplies concept, warm oak and brass tones, ' + STYLE,
    'spring-aop-proxy':    'flat vector illustration on a pure white background, a small wooden hand puppet wearing a simple blue apron standing on a plain wooden stool in front of an empty chair, the puppet centered and taking up the middle of the frame, a clear margin of white background around all four sides, nothing touching the frame edges, a stand-in speaking for someone else concept, warm wood and cloth tones, ' + STYLE,
    'jvm-gc-g1-zgc':    'flat vector illustration on a pure white background, a small straw broom sweeping crumpled paper scraps across a pale wooden floor toward a low metal dustpan, the broom and dustpan centered with a clear margin of white background around all four sides, nothing touching the frame edges, clearing away scraps with different effort levels concept, warm straw and wood tones, ' + STYLE,
    'java-locks':    'flat vector illustration on a pure white background, four small wooden doors set in a row along the same wall, each door fitted with a different brass latch and handle, the row of doors centered with a clear margin of white background around all four sides, nothing touching the frame edges, four different gates to the same room concept, warm oak and brass tones, ' + STYLE,
    'node-event-loop':    'flat vector illustration on a pure white background, a small wooden spinning wheel with cream thread wound around its rim, standing on a plain surface, the spinning wheel centered with a clear margin of white background around all four sides, nothing touching the frame edges, one continuous loop of turns concept, warm wood and cream tones, ' + STYLE,
    'git-rebase-vs-merge':    'flat vector illustration on a pure white background, a small wooden card holder with a neat row of blank index cards, a hand sliding one fresh card into the middle of the row, the holder centered with a clear margin of white background around all four sides, nothing touching the frame edges, rearranging a stack into a clean order concept, warm paper and oak tones, ' + STYLE,
    'mysql-isolation-levels':    'flat vector illustration on a pure white background, a small wooden shop counter with an open paper ledger and a brass inkpot, two brass padlocks lying beside the ledger one closed and one open, the counter centered with a clear margin of white background around all four sides, nothing touching the frame edges, guarding the same record with different strengths concept, warm oak and brass tones, ' + STYLE,
    'mcp-client':    'flat vector illustration on a pure white background, a small vintage wooden telephone switchboard with two short cables plugged into its front panel and a brass earpiece hanging beside it, the switchboard centered with a clear margin of white background around all four sides, nothing touching the frame edges, the calling side of a conversation concept, warm oak and brass tones, ' + STYLE,
    'agent-tool-idempotency':    'flat vector illustration on a pure white background, a small brass cash register on a shop counter with a long paper receipt curling out of its side and a second identical receipt lying beside it, the register centered with a clear margin of white background around all four sides, nothing touching the frame edges, the same charge printed twice concept, warm brass and cream paper tones, ' + STYLE,
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
                    warn.append('构图贴边?(留白%.1f%%，暖色台面会顶满外接框，需目测确认)' % (margin * 100))
                print('OK   %-30s %s %3dKB 亮度%.0f 留白%.0f%%%s%s%s' % (
                    dest.replace('\\', '/'), size, kb, mean, margin * 100,
                    ('  [注意] ' + '、'.join(warn) + '，改 prompt 重跑该张') if warn else '',
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
