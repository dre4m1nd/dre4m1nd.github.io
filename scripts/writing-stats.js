// scripts/writing-stats.js
// 构建时生成「写作动态」卡片（本月更新篇数 / 连续写作天数 / 最近更新时间），
// 注入 hero 区分类卡容器内，原分类卡由 CSS 隐藏。
// 数据全部来自文章列表，发新文章重新构建即自动更新，零维护。

'use strict';

const MARKER = '<div class="categoryGroup">';

function pad2(n) {
  return String(n).padStart(2, '0');
}

function localKey(d) {
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
}

hexo.extend.filter.register('after_render:html', function (str) {
  if (!str.includes(MARKER)) return str;

  const posts = hexo.locals.get('posts').toArray();
  const now = new Date();

  // 本月更新
  const monthCount = posts.filter((p) => {
    const d = p.date;
    return d.year() === now.getFullYear() && d.month() === now.getMonth();
  }).length;

  // 连续写作：从今天（无文章则从昨天）往回数连续有文章的天数
  const days = new Set(posts.map((p) => p.date.format('YYYY-MM-DD')));
  let streak = 0;
  const cur = new Date();
  cur.setHours(0, 0, 0, 0);
  if (!days.has(localKey(cur))) cur.setDate(cur.getDate() - 1);
  while (days.has(localKey(cur))) {
    streak++;
    cur.setDate(cur.getDate() - 1);
  }

  // 最近更新 + 跳转目标
  let last = '—';
  let newestPath = '/archives/';
  if (posts.length) {
    const newest = posts.reduce((a, b) => (a.date.valueOf() > b.date.valueOf() ? a : b));
    last = newest.date.format('MM-DD');
    newestPath = '/' + newest.path;
  }
  const monthPath = '/archives/' + now.getFullYear() + '/' + pad2(now.getMonth() + 1) + '/';

  const card =
    '<div class="writing-stats">' +
      '<a class="ws-item ws-month" href="' + monthPath + '"><i class="fa-regular fa-calendar"></i><div class="ws-text"><span class="ws-num">' + monthCount + '</span><span class="ws-label">本月更新</span></div><i class="ws-arrow fa-solid fa-arrow-right"></i></a>' +
      '<a class="ws-item ws-streak" href="/archives/"><i class="fa-solid fa-fire"></i><div class="ws-text"><span class="ws-num">' + streak + '</span><span class="ws-label">连续写作</span></div><i class="ws-arrow fa-solid fa-arrow-right"></i></a>' +
      '<a class="ws-item ws-last" href="' + newestPath + '"><i class="fa-regular fa-clock"></i><div class="ws-text"><span class="ws-num ws-date">' + last + '</span><span class="ws-label">最近更新</span></div><i class="ws-arrow fa-solid fa-arrow-right"></i></a>' +
    '</div>';

  return str.replace(MARKER, MARKER + card);
});
