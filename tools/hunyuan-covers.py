# tools/hunyuan-covers.py
# 用腾讯 TokenHub 混元 hy-image-v3.5-preview 生成博客封面
#
# 只负责「没有官方 logo 可用」的文章（算法、AI 笔记、项目拆解、默认封面）；
# 框架/工具类文章的封面走 tools/make-covers.py（白底 + 官方 logo），两边共用同一套主题配色。
#
# 配色硬约束（和主题一致）：白底 #FFFFFF、主色蓝 #425AEF、辅色青 #00c4b6，
# 生成后自动压到 900x675（4:3）quality 85。
# 落盘目录：文章封面 source/img/<年>/<月>/，站点级图片 source/img/common/
# （按「哪篇文章引用了这张封面」自动定位，见 tools/imgpaths.py；文章还没写
#   frontmatter 时加 --dir <目录>）
#
# 前提：去 https://console.cloud.tencent.com/tokenhub/inference 开通后付费
# （首次会有免费额度，或直接按量计费）
#
# 用法：
#   $env:HUNYUAN_API_KEY = "sk-NzawHDAIHMqxhqhn93tXMj1JW8omLdd810HjeYa2DNvljuAa"   # 也可不设，脚本里已带 key
#   python tools/hunyuan-covers.py                  # 全部
#   python tools/hunyuan-covers.py --only cover-kmp # 指定几张
#   python tools/hunyuan-covers.py --only <key> --dir source/img/2026/12
#   python tools/hunyuan-covers.py --dry-run        # 只试第一张


import json
import os
import sys
import time
import urllib.request
import urllib.error

from imgpaths import cover_dir

from PIL import Image

# API 配置
API_URL = 'https://tokenhub.tencentmaas.com/v1/wand/hunyuan-image/v35-generation'
MODEL = 'hy-image-v3.5-preview'
KEY = os.environ.get('HUNYUAN_API_KEY', 'sk-NzawHDAIHMqxhqhn93tXMj1JW8omLdd810HjeYa2DNvljuAa')

# 生成尺寸 1280x960（4:3），落盘统一压到 900x675
SIZE = '1280x960'
OUT_W, OUT_H = 900, 675
QUALITY = 85

# 风格模板：白底 + 主题蓝/青，扁平极简，无文字（保证和 logo 封面同一观感）
STYLE = ('pure white background, bright blue #425AEF and cyan #00c4b6 only, no beige, no warm tones, '
         'minimal flat vector illustration, zoomed out wide shot, entire composition fully visible '
         'inside the frame, centered with wide margins on all sides, nothing cropped, '
         'no 3d render, no photorealistic, no text, no letters, no watermark, no signature')

PROMPTS = {
    # ── 算法笔记 ──
    'cover-binary':    'abstract illustration of a magnifying glass hovering above a sorted row of dots with a highlighted midpoint, precision binary search concept, ' + STYLE,
    'cover-kmp':       'abstract illustration of a chain of beads being compared by a sliding pointer that never moves backward, string matching concept, ' + STYLE,
    'cover-quicksort': 'abstract illustration of columns of blocks splitting around a highlighted pivot with sweeping arrows on both sides, quicksort partition concept, ' + STYLE,
    # ── 项目拆解 ──
    'cover-cipherlens':'flat vector illustration of a magnifying glass examining a padlock surrounded by cipher symbols and code brackets, security analysis concept, pure white background, bright blue #425AEF and cyan #00c4b6 only, minimal flat shapes, no 3d, no photorealistic, no beige or warm tones, no text, no letters, no watermark',
    # ── AI 笔记 ──
    'ai-critical-thinking':   'flat vector icon of a human head profile drawn as a simple line-art outline containing a glowing network of nodes, three gears beside it with one gear highlighted, critical thinking concept, pure white background, bright blue #425AEF and cyan #00c4b6 only, minimal flat shapes, no 3d, no photorealistic, no gray statue, no beige or warm tones, no text, no letters, no watermark',
    'agent-state-machines':   'flat vector diagram of four small circular states connected in a closed loop by curved arrows, one circle filled solid blue as the current state, others outlined, deterministic state machine concept, zoomed out wide shot, entire diagram fully visible inside the frame, centered with wide margins, pure white background, bright blue #425AEF and cyan #00c4b6 only, minimal flat shapes, no 3d, no tree, no photorealistic, no beige or warm tones, no text, no letters, no watermark',
    'cover-code-review':      'flat vector illustration of curly code brackets flowing down into a funnel and out into a rounded checklist card with a checkmark, automated code review concept, zoomed out wide shot, entire composition fully visible inside the frame, centered with wide margins, pure white background, bright blue #425AEF and cyan #00c4b6 only, minimal flat shapes, no 3d, no photorealistic, no beige or warm tones, no text, no letters, no watermark',
    'super-agent-designs':    'flat vector illustration of a central glowing hub dispatching tasks along thin arrows to many small worker nodes arranged in two layers, orchestration concept, pure white background, bright blue #425AEF and cyan #00c4b6 only, minimal flat shapes, no 3d, no photorealistic, no beige or warm tones, no text, no letters, no watermark',
    # ── 默认封面（frontmatter 没写 cover 时随机用）──
    'cover-code':   'flat vector illustration of a pair of curly code brackets in solid blue with a small cyan terminal window below, general tech aesthetic, pure white background, bright blue #425AEF and cyan #00c4b6 only, minimal flat shapes, no 3d, no photorealistic, no beige or warm tones, no text, no letters, no watermark',
    'cover-notes':  'abstract illustration of floating notebook pages with abstract diagram marks and code brackets, notes concept, ' + STYLE,
    'cover-tools':  'abstract illustration of a wrench, gears and tool icons arranged in a neat grid, tooling concept, ' + STYLE,
}


def generate(prompt, size=SIZE):
    body = {
        'model': MODEL,
        'messages': [{
            'role': 'user',
            'content': [{'type': 'text', 'text': prompt}],
        }],
        'size': size,
    }
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data, method='POST', headers={
        'Authorization': 'Bearer ' + KEY,
        'Content-Type': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode('utf-8'))


def extract_image_url(resp):
    """从响应里提取图片 URL（兼容多种结构）"""
    # 1. assembled_history（v3.5-preview 思考型模型）
    for turn in resp.get('assembled_history', []):
        content = turn.get('content')
        if isinstance(content, list):
            for c in content:
                if c.get('type') == 'image_url':
                    u = c['image_url'].get('url')
                    if u:
                        return u
    # 2. OpenAI 风格
    for d in resp.get('data') or []:
        if d.get('url') or d.get('b64_json'):
            return d
    # 3. images 数组
    for d in resp.get('images') or []:
        if d.get('url') or d.get('b64_json'):
            return d
    return None


def save(out_path, data):
    """下载（或 base64 解码）→ 压到 900x675 落盘，返回 (尺寸, KB, 平均亮度, 内容留白比例)"""
    import base64
    import io
    if isinstance(data, dict) and data.get('b64_json'):
        raw = base64.b64decode(data['b64_json'])
    else:
        with urllib.request.urlopen(data if isinstance(data, str) else data.get('url'), timeout=180) as r:
            raw = r.read()

    im = Image.open(io.BytesIO(raw)).convert('RGB')
    if im.width != OUT_W:
        im = im.resize((OUT_W, round(im.height * OUT_W / im.width)), Image.LANCZOS)
    im.save(out_path, 'JPEG', quality=QUALITY, optimize=True, progressive=True)

    grey = im.convert('L')
    mean = sum(grey.getdata()) / (grey.width * grey.height)

    # 内容贴边检测：非白像素的 bbox 距四边的最小留白（占短边比例）
    box = grey.point(lambda v: 255 if v < 235 else 0).getbbox()
    margin = min(box[0], box[1], im.width - box[2], im.height - box[3]) / min(im.width, im.height) if box else 1.0
    return im.size, os.path.getsize(out_path) // 1024, mean, margin


def main():
    args = sys.argv[1:]
    only = args[args.index('--only') + 1].split(',') if '--only' in args else None
    dry = '--dry-run' in args

    targets = [k for k in PROMPTS if not only or k in only]
    if dry:
        targets = targets[:1]

    dir_arg = args[args.index('--dir') + 1] if '--dir' in args else ''

    ok = fail = 0

    for slug in targets:
        out_dir = dir_arg or cover_dir(slug)
        os.makedirs(out_dir, exist_ok=True)
        dest = os.path.join(out_dir, slug + '.jpg')
        try:
            resp = generate(PROMPTS[slug])
            data = extract_image_url(resp)
            if not data:
                raise RuntimeError(json.dumps(resp, ensure_ascii=False)[:300])
            size, kb, mean, margin = save(dest, data)
            ok += 1
            warn = []
            if mean < 200:
                warn.append('底色偏暗(亮度%.0f)' % mean)
            if margin < 0.03:
                warn.append('构图贴边(留白%.1f%%)' % (margin * 100))
            print('OK   %-30s %s %3dKB 亮度%.0f 留白%.0f%%%s' % (
                dest.replace('\\', '/'), size, kb, mean, margin * 100,
                ('  ⚠️ ' + '、'.join(warn) + '，改 prompt 重跑该张') if warn else ''))
            time.sleep(0.4)
        except urllib.error.HTTPError as e:
            fail += 1
            print('FAIL', slug, e.code, e.read().decode('utf-8', 'ignore')[:200])
        except Exception as e:
            fail += 1
            print('FAIL', slug, str(e)[:200])

    print('\n完成：%d 成功 / %d 失败' % (ok, fail))
    print('下一步：目测检查后 npx hexo clean && npx hexo generate，再 git 提交发布')

if __name__ == '__main__':
    main()
