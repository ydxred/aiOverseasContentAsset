import {Config} from '@remotion/cli/config';
import os from 'node:os';

/**
 * Local / CI render speed defaults.
 *
 * - JPEG sequence frames are much faster to encode/decode than PNG.
 * - x264 `fast` trades a bit of compression efficiency for shorter mux time.
 * - `if-possible` uses NVENC/VAAPI when ffmpeg supports it (WSL may still fall
 *   back to software — that is fine).
 * - Concurrency scales with CPU but is capped to avoid typical WSL OOMs.
 *
 * CLI flags always override these settings. For a slower, heavier export:
 *   npx remotion render ... --video-image-format=png --x264-preset=medium \\
 *     --hardware-acceleration=disable
 */
const cores = Math.max(1, os.cpus().length);
const concurrency = Math.min(10, Math.max(3, Math.ceil(cores * 0.6)));

Config.setConcurrency(concurrency);
Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(88);
Config.setX264Preset('fast');
Config.setHardwareAcceleration('if-possible');
