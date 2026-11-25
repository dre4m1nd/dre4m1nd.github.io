# tools/prepublish.py
# 发布前一站式自检：把两个工作流里重复了 7 遍的那份发布清单收成一处。
#
# 只做「确定性检查」——能机器判定的，全在这里；需要人/agent 判断的
# （目测封面、写 commit message、等 CI、线上抽查）仍留在工作流里。
#
# 跑的四步（任一失败即中止，返回 1）：
#   1. frontmatter 校验        tools/check-frontmatter.py
#   2. 分类一致性              _config.yml 的 category_map ↔ 文章实际分类 ↔ home_top 卡片 path
#   3. 构建                    npx hexo clean && npx hexo generate
#   4. 站内死链                tools/check-links.py
#
# 用法：
#   python tools/prepublish.py            # 全量（发布前跑这个）
#   python tools/prepublish.py --fast     # 只跑 1、2，跳过构建和死链（改完 frontmatter 快速自查）
#   python tools/prepublish.py -v         # 透传 --verbose 给子检查
#
# 为什么是 py 而不是写进 workflow：两个工作流（写新文章 / 整理旧文章）
# 的发布阶段本来是同一份清单写了两遍，改一次规则要改两处、漏一处就不一致。
# 收进这里之后，改规则只改这一个文件，两个工作流都只写一行调用。

import argparse
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

# Windows 控制台默认 GBK，子进程输出里偶尔带无法映射的字符会让 print 直接抛
# UnicodeEncodeError。这里统一放宽成替换，别让编码问题冒充成检查失败。
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def run(label, cmd, cwd=REPO, quiet=False):
    """跑一条命令，返回 (ok, output)。"""
    print('\n── %s ──' % label)
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True,
                           text=True, encoding='utf-8', errors='replace')
    except Exception as e:
        print('  无法执行: %s' % e)
        return False, str(e)
    out = (p.stdout or '') + (p.stderr or '')
    if not quiet:
        print(out.rstrip())
    return p.returncode == 0, out


def read(path):
    return open(os.path.join(REPO, path), encoding='utf-8').read()


def parse_category_map():
    """从 _config.yml 的 category_map: 块里取 中文 → 英文。"""
    text = read('_config.yml')
    m = re.search(r'^category_map:[ \t]*$', text, re.M)
    if not m:
        return {}
    out = {}
    for line in text[m.end():].splitlines():
        if not line.strip():
            continue
        mm = re.match(r'^\s{2,}(\S+?):[ \t]*(\S+)[ \t]*$', line)
        if not mm:
            break  # 出了这个块
        out[mm.group(1).strip('"\'')] = mm.group(2).strip('"\'')
    return out


def post_categories():
    """扫描所有文章的 categories，返回 {分类名: [文件相对路径]}。"""
    root = os.path.join(REPO, 'source', '_posts')
    found = {}
    for dirpath, _, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith('.md'):
                continue
            path = os.path.join(dirpath, name)
            text = open(path, encoding='utf-8').read()
            if not text.startswith('---'):
                continue
            parts = text.split('---', 2)
            if len(parts) < 3:
                continue
            fm = parts[1]
            m = re.search(r'^categories:[ \t]*(.*)$', fm, re.M)
            if not m:
                continue
            inline = m.group(1).strip()
            cats = []
            if inline.startswith('[') and inline.endswith(']'):
                cats = [x.strip().strip('"\'') for x in inline[1:-1].split(',') if x.strip()]
            elif inline:
                cats = [inline.strip('"\'')]
            else:
                for line in fm[m.end():].splitlines():
                    mm = re.match(r'\s*-\s+(.+)$', line)
                    if mm:
                        cats.append(mm.group(1).strip().strip('"\''))
                    elif line.strip():
                        break
            rel = os.path.relpath(path, REPO).replace('\\', '/')
            for c in cats:
                found.setdefault(c, []).append(rel)
    return found


def home_top_category_paths():
    """从 _config.anzhiyu.yml 取 home_top 里所有 /categories/xxx/ 的 path。"""
    text = read('_config.anzhiyu.yml')
    m = re.search(r'^home_top:[ \t]*$', text, re.M)
    if not m:
        return []
    block = text[m.end():]
    end = re.search(r'^\S', block, re.M)
    if end:
        block = block[:end.start()]
    return re.findall(r'path:[ \t]*/categories/([^/\s]+)/', block)


def check_categories(verbose=False):
    """分类一致性：文章用的分类都要在 category_map 里；home_top 卡片 path 要用映射后的英文名。"""
    print('\n── 分类一致性 ──')
    errors = []
    cmap = parse_category_map()
    if not cmap:
        print('  _config.yml 里没找到 category_map')
        return False

    used = post_categories()
    for cat, files in sorted(used.items()):
        if cat not in cmap:
            errors.append('分类「%s」不在 category_map 里（%s）→ 会生成 /categories/%s/ 野分类页'
                          % (cat, files[0], cat))

    english = set(cmap.values())
    for seg in home_top_category_paths():
        if seg not in english:
            errors.append('_config.anzhiyu.yml 的 home_top 卡片 path 用了 /categories/%s/，'
                          '但 category_map 里没有映射到「%s」的英文名 → 首页卡片 404'
                          % (seg, seg))

    if verbose:
        print('  category_map: %s' % ', '.join('%s→%s' % kv for kv in sorted(cmap.items())))
        print('  文章在用: %s' % ', '.join('%s(%d篇)' % (c, len(f)) for c, f in sorted(used.items())))
        print('  首页卡片 categories 路径: %s' % (home_top_category_paths() or '无'))

    if errors:
        for e in errors:
            print('  ERROR ' + e)
        return False
    print('  OK：%d 个分类全部有映射，首页卡片路径无悬空' % len(used))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fast', action='store_true', help='只查 frontmatter 和分类，不构建')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    steps = []  # [(名字, 是否通过)]

    ok, _ = run('1/4 frontmatter 校验',
                '"%s" tools/check-frontmatter.py%s' % (PY, ' -v' if args.verbose else ''))
    steps.append(('frontmatter', ok))
    if not ok:
        return finish(steps)

    steps.append(('分类一致性', check_categories(args.verbose)))
    if not steps[-1][1]:
        return finish(steps)

    if args.fast:
        return finish(steps)

    ok, _ = run('3/4 构建', 'npx hexo clean && npx hexo generate')
    steps.append(('构建', ok))
    if not ok:
        return finish(steps)

    ok, _ = run('4/4 站内死链',
                '"%s" tools/check-links.py%s' % (PY, ' -v' if args.verbose else ''))
    steps.append(('死链', ok))
    return finish(steps)


def finish(steps):
    print('\n══ 结果 ══')
    for name, ok in steps:
        print('  %-14s %s' % (name, '通过' if ok else '失败'))
    all_ok = all(ok for _, ok in steps)
    print('  → %s' % ('可以提交' if all_ok else '有失败项，改掉再来'))
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
