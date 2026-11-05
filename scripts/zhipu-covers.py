# scripts/zhipu-covers.py
# 用智谱 CogView-4 重做博客封面（只要一个 API Key，不用双密钥）
# 价格 ¥0.06/张，23 张约 ¥1.4
#
# 用法（PowerShell）：
#   $env:ZHIPU_API_KEY = "xxxx.xxxx"
#   python scripts/zhipu-covers.py                    # 全部
#   python scripts/zhipu-covers.py --only cover-hono  # 指定几张
#   python scripts/zhipu-covers.py --dry-run          # 先试一张
#
# 拿 key：https://open.bigmodel.cn/  →  右上角「API Keys」

import io
import json
import os
import sys
import time
import urllib.request
import urllib.error

API = 'https://open.bigmodel.cn/api/paas/v4/images/generations'
MODEL = 'cogview-4'
SIZE = '1024x1024'      # CogView-4 支持 1024x1024 / 768x1024 / 1024x768 / 1440x720 / 720x1440

KEY = os.environ.get('ZHIPU_API_KEY', '')

PROMPTS = {
    'banner': 'abstract illustration of a glowing terminal window with layered code streams flowing into a connected node network, dark navy background, violet and teal gradient, subtle grid texture, cinematic depth, clean modern tech aesthetic, no text',
    'cover-binary': 'abstract illustration of a glowing magnifying glass hovering above a sorted number line with a highlighted midpoint, dark navy background, violet and teal gradient, precision search concept, no text',
    'cover-kmp': 'abstract illustration of a glowing needle passing through a haystack of floating letters with a pattern array behind it, dark navy background, violet and teal gradient, string matching concept, no text',
    'cover-quicksort': 'abstract illustration of a glowing pivot element splitting an array into left and right partitions with sweeping motion arrows, dark navy background, violet and teal gradient, sorting concept, no text',
    'cover-compare': 'abstract illustration of four glowing pillars of different heights standing side by side for comparison, dark navy background, violet and teal gradient, no text',
    'cover-express': 'abstract illustration of a minimal glowing web server with a single route path and request response arrows, dark navy background, violet and teal gradient, no text',
    'cover-hono': 'abstract illustration of a glowing feather made of light with tiny floating server nodes around it, dark navy background, violet and teal gradient, edge computing concept, no text',
    'cover-fastify': 'abstract illustration of a glowing lightning bolt striking through a database schema diagram, dark navy background, violet and teal gradient, speed and validation concept, no text',
    'cover-koa': 'abstract illustration of glowing concentric onion layers with request and response arrows spiraling inward and outward, dark navy background, violet and teal gradient, middleware layers concept, no text',
    'cover-nestjs': 'abstract illustration of glowing nested hexagonal modules forming a structured architecture, dark navy background, violet and teal gradient, modular design concept, no text',
    'cover-prisma': 'abstract illustration of a glowing database cylinder with a floating schema definition card above it, dark navy background, violet and teal gradient, data modeling concept, no text',
    'cover-drizzle': 'abstract illustration of a glowing SQL query being assembled from glowing table blocks, dark navy background, violet and teal gradient, query builder concept, no text',
    'cover-mybatis': 'abstract illustration of a glowing elephant silhouette formed by light lines above an XML document, dark navy background, violet and teal gradient, java persistence concept, no text',
    'cover-zod': 'abstract illustration of a glowing shield with a checkmark surrounded by floating schema field labels, dark navy background, violet and teal gradient, validation concept, no text',
    'cover-linux': 'abstract illustration of a glowing terminal window with command lines and a small penguin silhouette, dark navy background, violet and teal gradient, shell concept, no text',
    'cover-cipherlens': 'abstract illustration of a magnifying glass examining a padlock surrounded by cipher symbols, dark navy background, violet and teal gradient, security analysis concept, no text',
    'cover-code-review': 'abstract illustration of a glowing funnel filtering code fragments down to a small group of human reviewers, dark navy background, violet and teal gradient, automated filtering concept, no text',
    'agent-state-machines': 'abstract illustration of glowing state machine nodes connected by transition arrows in a layered flow diagram, dark navy background, violet and teal gradient, deterministic scaffolding concept, no text',
    'ai-critical-thinking': 'abstract illustration of a human eye next to a glowing neural network brain, dark navy background, violet and teal gradient, critical thinking concept, no text',
    'super-agent-designs': 'abstract illustration of a central glowing hub dispatching tasks to many small worker nodes in a two-layer architecture, dark navy background, violet and teal gradient, orchestration concept, no text',
    'cover-code': 'abstract illustration of glowing code brackets, a terminal window and geometric shapes, dark navy background, violet and teal gradient, general tech aesthetic, no text',
    'cover-notes': 'abstract illustration of glowing notebook pages with abstract code and diagram marks, dark navy background, violet and teal gradient, notes concept, no text',
    'cover-tools': 'abstract illustration of glowing tool icons arranged in a neat grid, dark navy background, violet and teal gradient, tooling concept, no text',
}


def generate(prompt, size=SIZE):
    body = json.dumps({'model': MODEL, 'prompt': prompt, 'size': size}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(API, data=body, method='POST', headers={
        'Authorization': 'Bearer ' + KEY,
        'Content-Type': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode('utf-8'))


def download(url, dest):
    with urllib.request.urlopen(url, timeout=180) as r:
        data = r.read()
    with open(dest, 'wb') as f:
        f.write(data)
    return len(data)


def main():
    if not KEY:
        print('错误：缺少智谱 API Key。PowerShell 里先设置：')
        print('  $env:ZHIPU_API_KEY = "你的key"')
        print('拿 key：https://open.bigmodel.cn/  →  右上角「API Keys」')
        sys.exit(1)

    args = sys.argv[1:]
    only = args[args.index('--only') + 1].split(',') if '--only' in args else None
    size = args[args.index('--size') + 1] if '--size' in args else SIZE
    dry = '--dry-run' in args

    targets = [k for k in PROMPTS if not only or k in only]
    if dry:
        targets = targets[:1]

    os.makedirs('source/img', exist_ok=True)
    ok = fail = 0

    for slug in targets:
        dest = 'source/img/%s.jpg' % slug
        try:
            resp = generate(PROMPTS[slug], size)
            data = resp.get('data') or []
            if not data or not data[0].get('url'):
                raise RuntimeError(json.dumps(resp, ensure_ascii=False)[:200])
            n = download(data[0]['url'], dest)
            ok += 1
            print('OK  ', slug, '(%dKB)' % (n // 1024))
            time.sleep(0.4)
        except urllib.error.HTTPError as e:
            fail += 1
            print('FAIL', slug, e.code, e.read()[:200].decode('utf-8', 'ignore'))
        except Exception as e:
            fail += 1
            print('FAIL', slug, str(e)[:200])

    print('\n完成：%d 成功 / %d 失败' % (ok, fail))
    if ok:
        print('下一步：python scripts/resize-covers.py')


if __name__ == '__main__':
    main()
