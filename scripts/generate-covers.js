// scripts/generate-covers.js
// 用 Qwen/Qwen-Image 重做博客封面（比 Z-Image-Turbo 精细）
//
// 用法（PowerShell）：
//   $env:SF_KEY = "sk-xxxx"
//   node scripts/generate-covers.js                     # 全部
//   node scripts/generate-covers.js --only cover-hono   # 指定几张
//
// 生成后是 1280x960 原图，需要再跑 python scripts/resize-covers.py 压缩。

const fs = require('fs');
const https = require('https');

const KEY = process.env.SF_KEY;
const API = 'https://api.siliconflow.cn/v1/images/generations';
const MODEL = 'Qwen/Qwen-Image';

// 每篇一个专属 prompt：风格统一（深海军蓝底 + 紫青渐变 + 抽象科技插画 + 无文字），主题各异
const PROMPTS = {
  'banner': 'wide panoramic abstract illustration of a glowing terminal window and layered code streams flowing into a network of connected nodes, dark navy background, violet and teal gradient, subtle grid texture, clean modern tech aesthetic, cinematic depth, no text',
  'cover-binary': 'abstract illustration of a glowing magnifying glass over a sorted number line with a highlighted midpoint, dark navy background, violet and teal gradient, search and precision concept, no text',
  'cover-kmp': 'abstract illustration of a needle with a pattern array passing through a haystack of glowing letters, dark navy background, violet and teal gradient, string matching concept, no text',
  'cover-quicksort': 'abstract illustration of a glowing pivot element dividing an array into left and right partitions with sweeping arrows, dark navy background, violet and teal gradient, sorting concept, no text',
  'cover-compare': 'abstract illustration of four distinct glowing pillars of different heights and colors side by side, dark navy background, violet and teal gradient, comparison concept, no text',
  'cover-express': 'abstract illustration of a glowing minimal web server with a single route path and request response arrows, dark navy background, violet and teal gradient, minimal concept, no text',
  'cover-hono': 'abstract illustration of a glowing feather made of light with tiny server nodes floating around it, dark navy background, violet and teal gradient, edge computing concept, no text',
  'cover-fastify': 'abstract illustration of a glowing lightning bolt striking through a database schema diagram, dark navy background, violet and teal gradient, speed and validation concept, no text',
  'cover-koa': 'abstract illustration of glowing concentric onion layers with request response arrows spiraling inward and outward, dark navy background, violet and teal gradient, middleware layers concept, no text',
  'cover-nestjs': 'abstract illustration of glowing nested hexagonal modules forming a structured architecture, dark navy background, violet and teal gradient, modular concept, no text',
  'cover-prisma': 'abstract illustration of a glowing database cylinder with a schema definition card floating above it, dark navy background, violet and teal gradient, data modeling concept, no text',
  'cover-drizzle': 'abstract illustration of a glowing SQL query being built from glowing table blocks, dark navy background, violet and teal gradient, query builder concept, no text',
  'cover-mybatis': 'abstract illustration of a glowing elephant silhouette formed by light lines over an XML document, dark navy background, violet and teal gradient, java persistence concept, no text',
  'cover-zod': 'abstract illustration of a glowing shield with a checkmark and schema fields floating around it, dark navy background, violet and teal gradient, validation concept, no text',
  'cover-linux': 'abstract illustration of a glowing terminal window with command lines and a penguin silhouette, dark navy background, violet and teal gradient, shell concept, no text',
  'cover-cipherlens': 'abstract illustration of a magnifying glass examining a padlock with cipher symbols, dark navy background, violet and teal gradient, security analysis concept, no text',
  'cover-code-review': 'abstract illustration of a glowing funnel filtering code fragments down to a small group of human reviewers, dark navy background, violet and teal gradient, automated filtering concept, no text',
  'agent-state-machines': 'abstract illustration of glowing state machine nodes connected by transition arrows in a layered flow, dark navy background, violet and teal gradient, deterministic scaffolding concept, no text',
  'ai-critical-thinking': 'abstract illustration of a human eye beside a glowing brain network, dark navy background, violet and teal gradient, critical thinking concept, no text',
  'super-agent-designs': 'abstract illustration of a central glowing hub dispatching tasks to many small worker nodes in a two-layer architecture, dark navy background, violet and teal gradient, orchestration concept, no text',
  'cover-code': 'abstract illustration of glowing code brackets, terminal window and geometric shapes on dark navy, violet and teal gradient, general tech aesthetic, no text',
  'cover-notes': 'abstract illustration of glowing notebook pages with abstract code and diagram marks, dark navy background, violet and teal gradient, notes concept, no text',
  'cover-tools': 'abstract illustration of glowing tool icons arranged in a grid, dark navy background, violet and teal gradient, tooling concept, no text',
};

function post(body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = https.request(API, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json' },
    }, (res) => {
      let buf = '';
      res.on('data', (c) => buf += c);
      res.on('end', () => {
        try { resolve(JSON.parse(buf)); } catch (e) { reject(new Error(buf.slice(0, 200))); }
      });
    });
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

function download(url, dest) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return download(res.headers.location, dest).then(resolve, reject);
      }
      const f = fs.createWriteStream(dest);
      res.pipe(f);
      f.on('finish', () => f.close(() => resolve(dest)));
      f.on('error', reject);
    }).on('error', reject);
  });
}

async function main() {
  if (!KEY) {
    console.error('错误：没设 SF_KEY。PowerShell 里先跑：  $env:SF_KEY = "sk-xxxx"');
    process.exit(1);
  }

  const only = process.argv.includes('--only')
    ? process.argv[process.argv.indexOf('--only') + 1].split(',')
    : null;

  const targets = Object.keys(PROMPTS).filter(k => !only || only.includes(k));
  let ok = 0, fail = 0;

  for (const slug of targets) {
    const dest = 'source/img/' + slug + '.jpg';
    try {
      const d = await post({
        model: MODEL,
        prompt: PROMPTS[slug],
        image_size: '1280x960',
        num_inference_steps: 25,
        batch_size: 1,
      });
      if (!d.images || !d.images[0]) throw new Error(JSON.stringify(d).slice(0, 150));
      await download(d.images[0].url, dest);
      ok++;
      console.log('OK  ', slug);
    } catch (e) {
      fail++;
      console.log('FAIL', slug, String(e.message || e).slice(0, 120));
    }
  }
  console.log('\n完成:', ok, '成功 /', fail, '失败');
}

main();
