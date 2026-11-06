#!/usr/bin/env node
/*
 Performance and mobile check of the viewer (requirements: 60 FPS desktop,
 30+ FPS mobile, mobile compatibility).

   node perf_test.js --viewer work/viewer/viewer-standalone.html [--three-dir DIR] [--out perf.json]

 Runs the 360° orbit for 6 s in a desktop window and in phone emulation
 (iPhone 13, portrait and landscape), records frames per second, draw calls
 and triangles, and checks that the page has no errors and no horizontal
 overflow on the phone. In a container without a GPU, Chromium renders on
 the CPU (SwiftShader), so the FPS here is a floor, not what a real device
 gets; the draw-call and triangle budget is the portable part:
 under ~300 calls and ~1.5 M triangles is comfortable for phones.
*/
const { chromium, devices } = require('playwright');
const fs = require('fs'), path = require('path');
const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, arr) => { if (v.startsWith('--')) a.push([v.slice(2), arr[i + 1]]); return a; }, []));
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'] });
  const gpu = await (async () => { const p = await b.newPage(); const r = await p.evaluate(() => { const c = document.createElement('canvas').getContext('webgl'); const d = c && c.getExtension('WEBGL_debug_renderer_info'); return d ? c.getParameter(d.UNMASKED_RENDERER_WEBGL) : 'unknown'; }); await p.close(); return r; })();
  const runs = [
    ['desktop 1440x900', { viewport: { width: 1440, height: 900 } }],
    ['iPhone 13 portrait', devices['iPhone 13']],
    ['iPhone 13 landscape', devices['iPhone 13 landscape']],
  ];
  const out = { renderer: gpu, software_gpu: /swiftshader|llvmpipe|software/i.test(gpu), runs: [] };
  for (const [name, opt] of runs) {
    const ctx = await b.newContext(opt); const p = await ctx.newPage(); const errors = [];
    p.on('pageerror', e => errors.push(String(e)));
    if (args['three-dir']) for (const [k, v] of Object.entries({ 'three.min.js': 'build/three.min.js', 'OrbitControls.js': 'examples/js/controls/OrbitControls.js', 'RoomEnvironment.js': 'examples/js/environments/RoomEnvironment.js' }))
      await p.route('**/' + k, r => r.fulfill({ path: path.join(path.resolve(args['three-dir']), v), contentType: 'application/javascript' }));
    await p.goto('file://' + path.resolve(args.viewer));
    await p.waitForFunction(() => window.ADT && window.ADT.perf, null, { timeout: 60000 });
    const r = await p.evaluate(() => ADT.perf(6));
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    const shot = path.join(path.dirname(path.resolve(args.out || 'perf.json')), `perf-${name.replace(/\W+/g, '-')}.png`);
    await p.screenshot({ path: shot });
    out.runs.push({ name, ...r, fps: Math.round(r.fps * 10) / 10, horizontal_overflow: overflow, errors, screenshot: path.basename(shot) });
    await ctx.close();
  }
  await b.close();
  fs.writeFileSync(args.out || 'perf.json', JSON.stringify(out, null, 2));
  for (const r of out.runs) console.log(`${r.name.padEnd(22)} ${String(r.fps).padStart(6)} fps  calls ${r.calls}  tris ${r.triangles}  overflow ${r.horizontal_overflow}  errors ${r.errors.length}`);
  console.log('renderer:', gpu);
})().catch(e => { console.error(e); process.exit(1); });
