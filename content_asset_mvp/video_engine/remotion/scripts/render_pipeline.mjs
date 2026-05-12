#!/usr/bin/env node
/**
 * One-shot Remotion render: bundle once, then produce video + cover still.
 *
 * The CLI ``npx remotion render`` and ``npx remotion still`` each rebuild the
 * entire webpack bundle (~70-80s on this machine), which roughly doubles the
 * end-to-end render time for free. This script wires up the Node API so the
 * bundle is built exactly once and reused for both outputs.
 *
 * Usage:
 *   node scripts/render_pipeline.mjs \\
 *     --composition DouyinExplainer \\
 *     --props /path/to/remotion_props.json \\
 *     --out /tmp/foo.mp4 \\
 *     --cover /tmp/foo.png \\
 *     [--cover-frame 30]
 */
import {bundle} from '@remotion/bundler';
import {
  getCompositions,
  renderMedia,
  renderStill,
  selectComposition,
} from '@remotion/renderer';
import os from 'node:os';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const argv = process.argv.slice(2);
const args = {};
for (let i = 0; i < argv.length; i += 1) {
  const k = argv[i];
  if (k.startsWith('--')) {
    const key = k.slice(2);
    const v = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : 'true';
    args[key] = v;
    if (v !== 'true') i += 1;
  }
}

const composition = args.composition || 'DouyinExplainer';
const propsPath = args.props;
const outVideo = args.out;
const outCover = args.cover;
const coverFrame = Number(args['cover-frame'] || 30);

// Quality tier policy:
//
//   release  (default, publish):
//     - native composition resolution (1920x1080 / 1080x1920)
//     - native fps (30)
//     - x264 preset = medium  (good size/quality tradeoff)
//     - jpeg quality 88
//
//   draft (preview iteration):
//     - half-resolution scale (0.5x)  -> each frame is 1/4 the pixel work
//     - fps stays at 30  (so audio/subtitle timing math is untouched)
//     - x264 preset = ultrafast       (~3-5x encoder speed-up)
//     - jpeg quality 70  (frames are throwaway anyway)
//
// We deliberately keep fps untouched: changing it would desync the audio
// track and the burned-in word-level subtitles, which all assume the
// composition's authored fps.
//
// CLI overrides win — passing --x264-preset explicitly overrides tier policy.
const qualityTier = (args['quality-tier'] || 'release').toLowerCase();
if (qualityTier !== 'draft' && qualityTier !== 'release') {
  console.error(`--quality-tier must be 'draft' or 'release', got '${qualityTier}'`);
  process.exit(2);
}
const tierDefaults = qualityTier === 'draft'
  ? {format: 'jpeg', x264: 'ultrafast', jpegQ: 70, scale: 0.5}
  : {format: 'jpeg', x264: 'medium',    jpegQ: 88, scale: 1};

const requestedFormat = (args['video-image-format'] || tierDefaults.format).toLowerCase();
const requestedX264 = args['x264-preset'] || tierDefaults.x264;
const requestedJpegQuality = Number(args['jpeg-quality'] || tierDefaults.jpegQ);

if (!propsPath || !outVideo || !outCover) {
  console.error('Required: --props <path> --out <mp4> --cover <png>');
  process.exit(2);
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const remotionRoot = path.resolve(__dirname, '..');
const entryPoint = path.join(remotionRoot, 'src', 'index.ts');

const inputProps = JSON.parse(readFileSync(propsPath, 'utf8'));

// Concurrency tuning.
//
// Old setting was ``Math.min(10, Math.max(3, ceil(cores * 0.6)))`` — the
// hard cap of 10 came from the Remotion docs as a safe default but it
// silently caps any 16-core+ box. On a 24-core / 16GB box we measured 12
// minutes per render at concurrency=10; lifting it to ~80% of the cores
// (and respecting REMOTION_CONCURRENCY override) drops the same render to
// ~6 minutes. We still leave headroom for the OS and the parent Python
// process so we don't thrash.
//
// Rough per-Chromium-instance memory cost is 400-700MB. The system check
// below keeps us from blowing past 75% of total RAM if someone runs this
// on a 4GB VM.
const cores = Math.max(1, os.cpus().length);
const totalMemMB = Math.round(os.totalmem() / 1024 / 1024);
const memBudgetMB = Math.floor(totalMemMB * 0.75);
const memCappedConcurrency = Math.max(2, Math.floor(memBudgetMB / 700));
const envOverride = Number(process.env.REMOTION_CONCURRENCY || 0);
const cpuTarget = Math.max(3, Math.floor(cores * 0.8));
const concurrency = envOverride > 0
  ? envOverride
  : Math.min(cpuTarget, memCappedConcurrency, 32);
console.log(
  `[render_pipeline] concurrency=${concurrency}  (cores=${cores} ` +
  `mem_budget=${memBudgetMB}MB cpu_target=${cpuTarget} ` +
  `mem_cap=${memCappedConcurrency}${envOverride > 0 ? ` override=${envOverride}` : ''})`
);

const tBundleStart = Date.now();
console.log(`[render_pipeline] bundling once (entry=${entryPoint})...`);
const serveUrl = await bundle({
  entryPoint,
  webpackOverride: (cfg) => cfg,
});
console.log(`[render_pipeline] bundled in ${Math.round((Date.now() - tBundleStart) / 1000)}s -> ${serveUrl}`);

console.log('[render_pipeline] resolving compositions ...');
const target = await selectComposition({
  serveUrl,
  id: composition,
  inputProps,
});
console.log(
  `[render_pipeline]   ${target.id}: ${target.width}x${target.height} ${target.fps}fps ${target.durationInFrames} frames`
);

const tVideoStart = Date.now();
console.log(
  `[render_pipeline] rendering ${composition} -> ${outVideo} ` +
  `(tier=${qualityTier} scale=${tierDefaults.scale} preset=${requestedX264} jpegQ=${requestedJpegQuality})`
);
let lastPctLogged = -10;
await renderMedia({
  serveUrl,
  composition: target,
  codec: 'h264',
  outputLocation: outVideo,
  inputProps,
  imageFormat: requestedFormat,
  jpegQuality: requestedJpegQuality,
  x264Preset: requestedX264,
  scale: tierDefaults.scale,
  hardwareAcceleration: 'if-possible',
  concurrency,
  overwrite: true,
  onProgress: ({renderedFrames, encodedFrames, stitchStage}) => {
    const total = target.durationInFrames;
    const pct = Math.floor((renderedFrames / total) * 100);
    if (pct >= lastPctLogged + 10 || stitchStage === 'muxing') {
      lastPctLogged = pct;
      process.stdout.write(
        `\r[render_pipeline]   rendered ${renderedFrames}/${total} (${pct}%) encoded=${encodedFrames} stage=${stitchStage}    `
      );
    }
  },
});
process.stdout.write('\n');
console.log(`[render_pipeline] video done in ${Math.round((Date.now() - tVideoStart) / 1000)}s`);

const tStillStart = Date.now();
console.log(`[render_pipeline] rendering still frame ${coverFrame} -> ${outCover}`);
await renderStill({
  serveUrl,
  composition: target,
  output: outCover,
  inputProps,
  frame: coverFrame,
  imageFormat: 'png',
  scale: tierDefaults.scale,
  overwrite: true,
});
console.log(`[render_pipeline] still done in ${Math.round((Date.now() - tStillStart) / 1000)}s`);

const totalSec = Math.round((Date.now() - tBundleStart) / 1000);
console.log(`[render_pipeline] total ${totalSec}s`);
