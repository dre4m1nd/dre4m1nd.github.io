// scripts/heatmap.js
// 构建时生成「文章热力图」侧栏卡片（仿 GitHub 贡献图布局）：
// 行 = 星期（周日在上），列 = 周；顶部月份标签、左侧星期标签、底部 Less→More 图例。
// 通过 after_render:html 过滤器注入为侧栏独立顶级卡片（sticky_layout 之前）。
// 零前端依赖：纯 HTML/CSS，日期与篇数写在 title 提示里。发新文章重新构建即自动更新。

'use strict';

const MARKER = '<div class="sticky_layout">';
const WEEKS = 25; // 近 25 周（约半年）

function pad2(n) {
  return String(n).padStart(2, '0');
}

function localKey(d) {
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
}

hexo.extend.filter.register('after_render:html', function (str) {
  if (!str.includes(MARKER)) return str;

  const posts = hexo.locals.get('posts').toArray();
  const dayCount = new Map();
  for (const p of posts) {
    const d = new Date(p.date.valueOf());
    const key = localKey(d);
    dayCount.set(key, (dayCount.get(key) || 0) + 1);
  }

  // 起点：WEEKS 周前，对齐到周日
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = new Date(today);
  start.setDate(start.getDate() - (WEEKS * 7 - 1));
  start.setDate(start.getDate() - start.getDay());

  // 按列（周）组织，每列 7 天（周日→周六）
  const weeks = [];
  const cur = new Date(start);
  while (cur <= today) {
    const week = [];
    for (let i = 0; i < 7; i++) {
      if (cur > today) {
        week.push(null);
      } else {
        const key = localKey(cur);
        week.push({ key: key, c: dayCount.get(key) || 0 });
      }
      cur.setDate(cur.getDate() + 1);
    }
    weeks.push(week);
  }

  // 区间总篇数
  let rangeTotal = 0;
  for (const w of weeks) {
    for (const d of w) {
      if (d && d.c) rangeTotal += d.c;
    }
  }

  // 月份标签：列内出现某月 1 号就在该列标月份
  const monthHtml = weeks
    .map(function (w) {
      for (const d of w) {
        if (d && d.key.slice(8) === '01') {
          return '<span>' + parseInt(d.key.slice(5, 7), 10) + '月</span>';
        }
      }
      return '<span></span>';
    })
    .join('');

  // 格子（列优先顺序，与 grid-auto-flow: column 对应）
  const cells = [];
  for (const w of weeks) {
    for (const d of w) {
      if (!d) {
        cells.push('<i class="hm empty"></i>');
        continue;
      }
      const level = d.c === 0 ? 0 : Math.min(4, d.c);
      const tip = d.key + ' · ' + (d.c ? d.c + ' 篇' : '无文章');
      cells.push('<i class="hm l' + level + '" title="' + tip + '"></i>');
    }
  }

  const card =
    '<div class="card-widget card-heatmap" id="card-heatmap">' +
      '<div class="item-headline">' +
        '<i class="anzhiyufont anzhiyu-icon-chart-line"></i>' +
        '<span>文章热力图</span>' +
      '</div>' +
      '<div class="heatmap">' +
        '<div class="heatmap-weekdays">' +
          '<span></span><span>一</span><span></span><span>三</span><span></span><span>五</span><span></span>' +
        '</div>' +
        '<div class="heatmap-main">' +
          '<div class="heatmap-months">' + monthHtml + '</div>' +
          '<div class="heatmap-grid">' + cells.join('') + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="heatmap-footer">' +
        '<span class="heatmap-total">近 ' + Math.round(WEEKS / 4.345) + ' 个月 ' + rangeTotal + ' 篇</span>' +
        '<span class="heatmap-legend"><span>少</span>' +
          '<i class="hm l0"></i><i class="hm l1"></i><i class="hm l2"></i><i class="hm l3"></i><i class="hm l4"></i>' +
        '<span>多</span></span>' +
      '</div>' +
    '</div>';

  return str.replace(MARKER, card + MARKER);
});