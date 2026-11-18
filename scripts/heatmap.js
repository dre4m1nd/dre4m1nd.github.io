// scripts/heatmap.js
// 构建时生成「文章热力图」侧栏卡片（GitHub 风格：按天统计文章数），
// 通过 after_render:html 过滤器注入为侧栏的独立顶级卡片（在 sticky_layout 之前）。
// 零前端依赖：纯 HTML/CSS，日期与篇数写在 title 提示里。
// 有新文章时重新构建即自动更新，无需维护任何页面。

'use strict';

const MARKER = '<div class="sticky_layout">';
const WEEKS = 25; // 近 25 周（约半年，适配窄侧栏，无滚动）

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

  // 从今天往回 WEEKS 周，起点对齐到周日
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = new Date(today);
  start.setDate(start.getDate() - (WEEKS * 7 - 1));
  start.setDate(start.getDate() - start.getDay());

  const cells = [];
  let rangeTotal = 0;
  const cur = new Date(start);
  while (cur <= today) {
    const key = localKey(cur);
    const c = dayCount.get(key) || 0;
    if (c) rangeTotal += c;
    const level = c === 0 ? 0 : Math.min(4, c);
    const tip = key + ' · ' + (c ? c + ' 篇' : '无文章');
    cells.push('<i class="hm l' + level + '" title="' + tip + '"></i>');
    cur.setDate(cur.getDate() + 1);
  }
  // 末尾补齐到整周（未来日期用空格占位）
  while (cells.length % 7 !== 0) {
    cells.push('<i class="hm empty"></i>');
  }

  const card =
    '<div class="card-widget card-heatmap" id="card-heatmap">' +
      '<div class="item-headline">' +
        '<i class="anzhiyufont anzhiyu-icon-chart-line"></i>' +
        '<span>文章热力图</span>' +
      '</div>' +
      '<div class="heatmap-grid">' + cells.join('') + '</div>' +
      '<div class="heatmap-footer">' +
        '<span class="heatmap-total">近 ' + Math.round(WEEKS / 4.345) + ' 个月 ' + rangeTotal + ' 篇</span>' +
        '<span class="heatmap-legend"><span>少</span>' +
          '<i class="hm l0"></i><i class="hm l1"></i><i class="hm l2"></i><i class="hm l3"></i><i class="hm l4"></i>' +
        '<span>多</span></span>' +
      '</div>' +
    '</div>';

  return str.replace(MARKER, card + MARKER);
});
