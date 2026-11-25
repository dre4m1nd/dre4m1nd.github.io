# tools/fill-date-times.py
# 给文章补上真实落盘时间，让同一天的多篇能按时间排序。
#
# 时间来源：Windows 文件的创建时间（os.path.getctime，Windows 上即 CreationTime），
# 也就是这篇笔记第一次落到 D:/notes/blog-hexo 的时刻。
#
# 处理三类：
#   1. date 只写日期、没有时间      → 补落盘时间的时分秒
#   2. date 有时间但同日撞车（都是 12:00）→ 换成落盘时间，日期不动
#   3. 落盘日与 date 日不一致        → 见下面两条既定决定：
#      - 跨零点写、落盘日比 date 早一天的 5 篇：按用户决定改成真实落盘日（10-28）
#      - 先写好、隔天才同步的（web-frameworks-compare / zod-intro）：保留 date 日，
#        按用户决定 web-frameworks-compare 早一分钟
#
# 用法：
#   python tools/fill-date-times.py --dry-run   # 只看表格，不改文件
#   python tools/fill-date-times.py             # 实际写入

import argparse
import datetime
import os
import re
import sys

DATE_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?$')
DATELINE = re.compile(r'^date:[ \t]*(.+)$', re.M)

# 落盘日比 date 早一天的 5 篇：跨零点写的，按用户决定改用真实落盘日
SHIFT_DAY_TO_CTIME = {
    'express-intro', 'hono-intro', 'fastify-intro', 'koa-intro', 'nestjs-intro',
}

# 同秒落盘、由用户决定先后的两篇（早的在前）
TIEBREAK = [('web-frameworks-compare', 'zod-intro')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='source/_posts')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    rows = []  # [path, rel, slug, old_date, new_date, note]

    # 先看所有文件，找出同日撞时间的日期集合
    all_rows = []
    for dirpath, _, files in os.walk(args.root):
        for name in sorted(files):
            if not name.endswith('.md'):
                continue
            path = os.path.join(dirpath, name)
            text = open(path, encoding='utf-8').read()
            m = DATELINE.search(text)
            if not m:
                continue
            raw = m.group(1).strip().strip('"\'')
            dm = DATE_RE.match(raw)
            if not dm:
                continue
            slug = os.path.splitext(name)[0]
            all_rows.append((path, slug, raw, dm))

    from collections import defaultdict
    day_times = defaultdict(list)
    for path, slug, raw, dm in all_rows:
        if dm.group(4):
            day_times[(dm.group(1) + '-' + dm.group(2) + '-' + dm.group(3),
                       '%02d:%02d:%02d' % (int(dm.group(4)), int(dm.group(5)),
                                           int(dm.group(6) or 0)))].append(slug)
    collisions = set()
    for k, v in day_times.items():
        if len(v) > 1:
            collisions.update(v)

    tie_map = {}
    for first, second in TIEBREAK:
        tie_map[first] = 0
        tie_map[second] = 1  # 晚一分钟，只为打破并列

    for path, slug, raw, dm in all_rows:
        cs = datetime.datetime.fromtimestamp(os.path.getctime(path))
        ctime = '%02d:%02d:%02d' % (cs.hour, cs.minute, cs.second)
        cday = cs.strftime('%Y-%m-%d')
        fday = dm.group(1) + '-' + dm.group(2) + '-' + dm.group(3)
        rel = os.path.relpath(path, '.').replace('\\', '/')

        note = []
        if slug in SHIFT_DAY_TO_CTIME and cday != fday:
            new = cday + ' ' + ctime
            note.append('落盘日≠date日，按决定改用落盘日')
        elif not dm.group(4):
            new = fday + ' ' + ctime
            note.append('补落盘时间' if cday == fday else '补落盘时间（落盘日≠date日，保留原日期）')
        elif slug in collisions:
            new = fday + ' ' + ctime
            note.append('同日撞时间，换成落盘时间')
        else:
            continue  # 时间唯一且已有，不动

        if slug in tie_map:
            minutes = tie_map[slug]
            if minutes:
                h, mn, s = map(int, ctime.split(':'))
                carry, mn = divmod(mn + minutes, 60)
                new = fday + ' %02d:%02d:%02d' % (h + carry, mn, s)
                note.append('同秒落盘，按决定晚 %d 分钟' % minutes)
            else:
                note.append('同秒落盘，按决定为先')

        rows.append((rel, slug, raw, new, '; '.join(note)))

    for rel, slug, old, new, note in rows:
        print('%-46s %-22s %-22s %s' % (rel.replace('source/_posts/', ''),
                                        old, new, note))

    if not args.dry_run:
        for rel, slug, old, new, note in rows:
            text = open(rel, encoding='utf-8').read()
            m = DATELINE.search(text)
            text = text[:m.start(1)] + new + text[m.end(1):]
            open(rel, 'w', encoding='utf-8').write(text)

    print('\n%s共改动 %d 篇' % ('[dry-run] ' if args.dry_run else '', len(rows)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
