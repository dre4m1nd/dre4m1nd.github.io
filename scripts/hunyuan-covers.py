# scripts/hunyuan-covers.py
# 用腾讯混元生图（极速版 TextToImageLite）重做博客封面
# 免费额度：每个接口 50 次，23 张完全够
#
# 用法（PowerShell）：
#   $env:TENCENT_SECRET_ID  = "AKIDxxxx"
#   $env:TENCENT_SECRET_KEY = "xxxx"
#   python scripts/hunyuan-covers.py                    # 全部
#   python scripts/hunyuan-covers.py --only cover-hono  # 指定几张
#   python scripts/hunyuan-covers.py --dry-run          # 只测第一张

import base64
import hashlib
import hmac
import io
import json
import os
import sys
import time
import urllib.request
import urllib.error

HOST = 'aiart.tencentcloudapi.com'
SERVICE = 'aiart'
VERSION = '2022-12-29'
ACTION = 'TextToImageLite'
REGION = 'ap-guangzhou'

SECRET_ID = os.environ.get('TENCENT_SECRET_ID', '')
SECRET_KEY = os.environ.get('TENCENT_SECRET_KEY', '')

# 每篇一个专属 prompt（中文，混元推荐中文）
PROMPTS = {
    'banner': '深邃海军蓝背景上的终端窗口与层叠代码流，汇入相互连接的节点网络，紫青渐变，微妙网格纹理，电影级景深，干净现代科技感',
    'cover-binary': '发光的放大镜悬在有序数字线上方，中点被高亮，深蓝背景，紫青渐变，精准检索的概念，无文字',
    'cover-kmp': '一根发光的针穿过由字母组成的干草堆，背后是模式数组，深蓝背景，紫青渐变，字符串匹配的概念，无文字',
    'cover-quicksort': '发光的枢轴元素把数组分成左右两区，扫掠箭头，深蓝背景，紫青渐变，排序的概念，无文字',
    'cover-compare': '四根不同高度与颜色的发光柱子并排而立，深蓝背景，紫青渐变，对比的概念，无文字',
    'cover-express': '一个极简的发光的网页服务器，只有一条路由路径和请求响应箭头，深蓝背景，紫青渐变，极简的概念，无文字',
    'cover-hono': '一根由光构成的发光羽毛，周围漂浮着微小的服务器节点，深蓝背景，紫青渐变，边缘计算的概念，无文字',
    'cover-fastify': '一道发光的闪电击穿数据库结构图，深蓝背景，紫青渐变，速度与校验的概念，无文字',
    'cover-koa': '发光的同心洋葱层，请求与响应的箭头向内向外螺旋，深蓝背景，紫青渐变，中间件分层概念，无文字',
    'cover-nestjs': '发光的嵌套六边形模块组成结构化架构，深蓝背景，紫青渐变，模块化的概念，无文字',
    'cover-prisma': '发光的数据库圆柱体，上方漂浮一张数据模型卡片，深蓝背景，紫青渐变，数据建模概念，无文字',
    'cover-drizzle': '发光的 SQL 查询由发光的表格积木搭建而成，深蓝背景，紫青渐变，查询构建器概念，无文字',
    'cover-mybatis': '发光的线条构成大象剪影，下方是一份 XML 文档，深蓝背景，紫青渐变，Java 持久层概念，无文字',
    'cover-zod': '发光的盾牌带对勾，周围漂浮着结构字段，深蓝背景，紫青渐变，校验的概念，无文字',
    'cover-linux': '发光的终端窗口，里面是命令行，旁边有企鹅剪影，深蓝背景，紫青渐变，shell 概念，无文字',
    'cover-cipherlens': '放大镜审视着一把挂锁，周围有密码符号，深蓝背景，紫青渐变，安全分析概念，无文字',
    'cover-code-review': '发光的漏斗过滤着代码碎片，底部是一小群人影，深蓝背景，紫青渐变，自动化筛选概念，无文字',
    'agent-state-machines': '发光的状态机节点由转移箭头连接成分层流程，深蓝背景，紫青渐变，确定性脚手架概念，无文字',
    'ai-critical-thinking': '一只人眼旁边是一团发光的神经网络大脑，深蓝背景，紫青渐变，批判性思考概念，无文字',
    'super-agent-designs': '中央发光的枢纽把任务派发给许多微小的工作节点，两层架构，深蓝背景，紫青渐变，编排的概念，无文字',
    'cover-code': '发光的代码括号、终端窗口与几何图形，深蓝背景，紫青渐变，通用科技美学，无文字',
    'cover-notes': '发光的笔记本纸页，上面有抽象的代码与图示符号，深蓝背景，紫青渐变，笔记概念，无文字',
    'cover-tools': '发光的各类工具图标排成网格，深蓝背景，紫青渐变，工具的概念，无文字',
}


def sha256_hex(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def hmac256(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def call_api(payload):
    """TC3-HMAC-SHA256 签名并调用"""
    body = json.dumps(payload, ensure_ascii=False)
    ts = int(time.time())
    date = time.strftime('%Y-%m-%d', time.gmtime(ts))

    # 1. 规范请求串
    ct = 'application/json; charset=utf-8'
    canonical_headers = 'content-type:%s\nhost:%s\nx-tc-action:%s\n' % (ct, HOST, ACTION.lower())
    signed_headers = 'content-type;host;x-tc-action'
    hashed_payload = sha256_hex(body)
    canonical_request = '\n'.join(['POST', '/', '', canonical_headers, signed_headers, hashed_payload])

    # 2. 待签名字符串
    credential_scope = '%s/%s/tc3_request' % (date, SERVICE)
    string_to_sign = '\n'.join([
        'TC3-HMAC-SHA256', str(ts), credential_scope, sha256_hex(canonical_request)
    ])

    # 3. 计算签名
    secret_date = hmac256(('TC3' + SECRET_KEY).encode('utf-8'), date)
    secret_service = hmac256(secret_date, SERVICE)
    secret_signing = hmac256(secret_service, 'tc3_request')
    signature = hmac.new(secret_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    # 4. 拼接 Authorization
    authorization = ('TC3-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s'
                     % (SECRET_ID, credential_scope, signed_headers, signature))

    headers = {
        'Authorization': authorization,
        'Content-Type': ct,
        'Host': HOST,
        'X-TC-Action': ACTION,
        'X-TC-Version': VERSION,
        'X-TC-Timestamp': str(ts),
        'X-TC-Region': REGION,
    }
    req = urllib.request.Request('https://' + HOST, data=body.encode('utf-8'),
                                 headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main():
    if not SECRET_ID or not SECRET_KEY:
        print('错误：缺少腾讯云凭证。PowerShell 里先设置：')
        print('  $env:TENCENT_SECRET_ID  = "AKIDxxxx"')
        print('  $env:TENCENT_SECRET_KEY = "xxxx"')
        sys.exit(1)

    args = sys.argv[1:]
    only = None
    if '--only' in args:
        only = args[args.index('--only') + 1].split(',')
    dry = '--dry-run' in args

    targets = [k for k in PROMPTS if not only or k in only]
    if dry:
        targets = targets[:1]

    os.makedirs('source/img', exist_ok=True)
    ok = fail = 0

    for slug in targets:
        dest = 'source/img/%s.jpg' % slug
        try:
            resp = call_api({
                'Prompt': PROMPTS[slug],
                'Resolution': '1280:960',      # 4:3
                'Seed': 0,
                'LogoAdd': 0,                   # 不加"AI生成"水印
                'RspImgType': 'url',
            })
            r = resp.get('Response', {})
            if r.get('Error'):
                raise RuntimeError('%s: %s' % (r['Error'].get('Code'), r['Error'].get('Message')))
            url = r.get('ResultImage')
            if not url:
                raise RuntimeError('无 ResultImage：' + json.dumps(r, ensure_ascii=False)[:150])
            with urllib.request.urlopen(url, timeout=180) as img:
                data = img.read()
            with open(dest, 'wb') as f:
                f.write(data)
            ok += 1
            print('OK  ', slug, '(%dKB)' % (len(data) // 1024))
            time.sleep(0.5)
        except urllib.error.HTTPError as e:
            fail += 1
            print('FAIL', slug, e.code, e.read()[:150].decode('utf-8', 'ignore'))
        except Exception as e:
            fail += 1
            print('FAIL', slug, str(e)[:150])

    print('\n完成：%d 成功 / %d 失败' % (ok, fail))
    if ok:
        print('\n下一步：python scripts/resize-covers.py')


if __name__ == '__main__':
    main()
