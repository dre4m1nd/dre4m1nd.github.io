// scripts/post-badge.js
// 根据文章 frontmatter 的 handwritten 字段，给文章页 <body> 打标记，
// 再由 source/css/custom.css 决定底部展示「原创」还是「AI 辅助生成」。
//   未设置 handwritten（默认） -> is-ai-assisted  -> 展示「AI 辅助生成」
//   handwritten: true         -> is-original      -> 展示主题原生的「原创」
// 注意：不修改 themes/ 下任何文件，只用项目级 scripts 扩展。
hexo.extend.filter.register('after_render:html', function (str, data) {
  const page = data && data.page
  if (!page || page.layout !== 'post') return str

  const cls = page.handwritten === true ? 'is-original' : 'is-ai-assisted'

  return str.replace(/(<body\b[^>]*>)/, function (bodyTag) {
    if (/class=/.test(bodyTag)) {
      return bodyTag.replace(/class="([^"]*)"/, 'class="$1 ' + cls + '"')
    }
    return bodyTag.replace(/<body\b/, '<body class="' + cls + '"')
  })
})
