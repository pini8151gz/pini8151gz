#!/usr/bin/env node
/*
 Step 7b – stills and films from the same verified model, rendered by the
 viewer itself in headless Chromium (Playwright) and encoded with ffmpeg.

   node render_views.js --viewer work/viewer/viewer-standalone.html --out work/renders \
        [--three-dir /path/to/three/package] [--size 1600x1000] [--fps 24] [--max-rooms 8] [--no-video]

 Writes:
   axonometric-furnished.png      furnished axonometric, walls cut at 1.4 m
   axonometric-closed.png         same view, full-height walls
   top-dimensioned-3d.png         orthographic top view with the dimensions layer
   interiors/NN-<type>.png        eye-level stills (1.6 m) of each furnished space
   clips/NN-*.mp4                 one moving shot per space (slow push-in)
   walkthrough.mp4                cinematic film: aerial descent → every space,
                                  joined with cross-fades → top view with dimensions

 --three-dir: a local copy of three@0.128.0 (npm pack three@0.128.0) when the
 CDN is not reachable; requests for three.min.js, OrbitControls.js and
 RoomEnvironment.js are then served from it.
 Rendering is real-time WebGL (here a software GPU): good light, shadows and
 environment reflections, not path-traced photorealism. Say so to the user.
*/
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, arr) => {
  if (v.startsWith('--')) a.push([v.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
  return a;
}, []));
if (!args.viewer || !args.out) { console.error('usage: --viewer viewer-standalone.html --out dir'); process.exit(2); }
const [W, H] = (args.size || '1280x800').split('x').map(Number);
const FPS = +(args.fps || 24);
const MAXR = +(args['max-rooms'] || 8);
const out = path.resolve(args.out);
for (const d of ['', 'interiors', 'clips', 'frames']) fs.mkdirSync(path.join(out, d), { recursive: true });

const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
const lerp = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);

(async () => {
  const browser = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  if (args['three-dir']) {
    const td = path.resolve(args['three-dir']);
    const map = { 'three.min.js': 'build/three.min.js', 'OrbitControls.js': 'examples/js/controls/OrbitControls.js',
      'RoomEnvironment.js': 'examples/js/environments/RoomEnvironment.js' };
    for (const [k, v] of Object.entries(map))
      await page.route('**/' + k, r => r.fulfill({ path: path.join(td, v), contentType: 'application/javascript' }));
  }
  await page.goto('file://' + path.resolve(args.viewer));
  await page.waitForFunction(() => window.ADT && window.ADT.frame, null, { timeout: 60000 });
  await page.evaluate(() => { ADT.ui(false); });
  const shot = async (file) => { await page.evaluate(() => ADT.frame()); await page.screenshot({ path: file, timeout: 120000 }); };

  // ---- axonometric (furnished) and top with dimensions
  await page.evaluate(() => { ADT.layers(false, true); ADT.axo(Math.PI * 0.25, Math.PI * 0.2, 1.4); });
  await shot(path.join(out, 'axonometric-furnished.png'));
  // zoomed axonometric around the densest furnished area (one wing / apartment)
  const region = await page.evaluate(() => {
    const pts = ADT.furniture().flatMap(f => f.parts);
    let best = null;
    for (const p of pts) { const n = pts.filter(q => Math.abs(q[0] - p[0]) < 6 && Math.abs(q[1] - p[1]) < 6).length; if (!best || n > best.n) best = { n, p }; }
    return best ? [best.p[0] - 7, best.p[1] - 7, best.p[0] + 7, best.p[1] + 7] : null;
  });
  if (region) {
    await page.evaluate((r) => { ADT.axo(Math.PI * 0.25, Math.PI * 0.22, 1.4, r); }, region);
    await shot(path.join(out, 'axonometric-furnished-detail.png'));
  }
  await page.evaluate(() => { ADT.axo(Math.PI * 0.25, Math.PI * 0.2, null); });
  await shot(path.join(out, 'axonometric-closed.png'));
  await page.evaluate(() => { ADT.layers(true, true); ADT.axo(0, Math.PI / 2 - 1e-4, 1.2); });
  await shot(path.join(out, 'top-dimensioned-3d.png'));
  await page.evaluate(() => ADT.layers(false, true));

  // ---- eye-level poses: computed in build_model.py from each space's own floor
  const poses = await page.evaluate((maxr) => {
    const v = ADT.views();
    const byT = {}; v.forEach(x => (byT[x.type] = byT[x.type] || []).push(x));
    const order = ['living', 'bedroom', 'kitchen', 'saferoom'].filter(k => byT[k]);
    const rr = []; for (let i = 0; rr.length < v.length; i++) for (const k of order) if (byT[k][i]) rr.push(byT[k][i]);
    return rr.slice(0, maxr);
  }, MAXR);

  const frames = path.join(out, 'frames');
  const clips = [];
  const enc = (dir, file) => execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(FPS), '-i', path.join(dir, '%05d.jpg'),
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-movflags', '+faststart', file]);
  const clean = dir => { for (const f of fs.readdirSync(dir)) fs.unlinkSync(path.join(dir, f)); };

  // stills
  await page.evaluate(() => ADT.interior(true));
  for (let i = 0; i < poses.length; i++) {
    const p = poses[i];
    await page.evaluate(([c, t]) => ADT.persp(c, t, 62), [p.cam, p.target]);
    await shot(path.join(out, 'interiors', `${String(i + 1).padStart(2, '0')}-${p.type}.png`));
  }

  if (!args['no-video']) {
    const C = await page.evaluate(() => ADT.center), R = await page.evaluate(() => ADT.radius);
    await page.evaluate(() => ADT.interior(false));
    // aerial descent: orbit from high and far to a low three-quarter view
    clean(frames);
    let n = Math.round(FPS * 5);
    for (let f = 0; f < n; f++) {
      const t = ease(f / (n - 1)), a = Math.PI * (0.15 + 0.35 * t);
      const cam = [C[0] + Math.sin(a) * R * (1.0 - .35 * t), C[1] + R * (0.9 - .5 * t), C[2] + Math.cos(a) * R * (1.0 - .35 * t)];
      await page.evaluate(([c, tg]) => ADT.persp(c, tg, 45), [cam, C]);
      await page.evaluate(() => ADT.frame()); await page.screenshot({ path: path.join(frames, String(f).padStart(5, '0') + '.jpg'), type: 'jpeg', quality: 92, timeout: 120000 });
    }
    const aerial = path.join(out, 'clips', '00-aerial.mp4'); enc(frames, aerial); clips.push(aerial);
    // one slow push-in per space
    await page.evaluate(() => ADT.interior(true));
    for (let i = 0; i < poses.length; i++) {
      const p = poses[i]; clean(frames); n = Math.round(FPS * 4);
      const start = p.cam, end = lerp(p.cam, [p.target[0], p.cam[1], p.target[2]], 0.28);
      for (let f = 0; f < n; f++) {
        const t = ease(f / (n - 1));
        const tg = [p.target[0] + Math.sin(t * Math.PI) * 0.25, p.target[1], p.target[2]];
        await page.evaluate(([c, g]) => ADT.persp(c, g, 62), [lerp(start, end, t), tg]);
        await page.evaluate(() => ADT.frame()); await page.screenshot({ path: path.join(frames, String(f).padStart(5, '0') + '.jpg'), type: 'jpeg', quality: 92, timeout: 120000 });
      }
      const file = path.join(out, 'clips', `${String(i + 1).padStart(2, '0')}-${p.type}.mp4`); enc(frames, file); clips.push(file);
    }
    // closing: top view with dimensions, slow zoom out
    clean(frames); n = Math.round(FPS * 3);
    await page.evaluate(() => { ADT.interior(false); ADT.layers(true, true); });
    for (let f = 0; f < n; f++) {
      await page.evaluate((t) => { ADT.axo(0, Math.PI / 2 - 1e-4, 1.2); }, f / (n - 1));
      await page.evaluate(() => ADT.frame()); await page.screenshot({ path: path.join(frames, String(f).padStart(5, '0') + '.jpg'), type: 'jpeg', quality: 92, timeout: 120000 });
    }
    const top = path.join(out, 'clips', '99-top.mp4'); enc(frames, top); clips.push(top);
    clean(frames);
    // join with cross-fades
    const durs = clips.map(c => parseFloat(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', c]).toString()));
    const XF = 0.8; let filt = '', last = '[0:v]', off = 0;
    for (let i = 1; i < clips.length; i++) {
      off += durs[i - 1] - XF;
      const lab = i === clips.length - 1 ? '[v]' : `[x${i}]`;
      filt += `${last}[${i}:v]xfade=transition=fade:duration=${XF}:offset=${off.toFixed(3)}${lab};`;
      last = lab;
    }
    const inputs = clips.flatMap(c => ['-i', c]);
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...inputs, '-filter_complex', filt.replace(/;$/, ''), '-map', '[v]',
      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-movflags', '+faststart', path.join(out, 'walkthrough.mp4')]);
  }
  fs.rmSync(frames, { recursive: true, force: true });
  fs.writeFileSync(path.join(out, 'renders.json'), JSON.stringify({ size: [W, H], fps: FPS, poses, errors,
    note: 'Real-time WebGL renders of the verified model; furniture and finishes are VISUAL ONLY.' }, null, 2));
  console.log(`renders: ${poses.length} interiors, video=${!args['no-video']}, errors=${errors.length}`);
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
