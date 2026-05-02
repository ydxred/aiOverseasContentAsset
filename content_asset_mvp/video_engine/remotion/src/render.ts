import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import path from 'path';

type RenderArgs = {
  output: string;
  title?: string;
  audioPath?: string;
  subtitles?: unknown[];
};

export const renderDouyinExplainer = async (args: RenderArgs) => {
  const entry = path.join(process.cwd(), 'src', 'Root.tsx');
  const bundleLocation = await bundle(entry);
  const composition = await selectComposition({
    serveUrl: bundleLocation,
    id: 'DouyinExplainer',
    inputProps: args
  });
  await renderMedia({
    composition,
    serveUrl: bundleLocation,
    codec: 'h264',
    outputLocation: args.output,
    inputProps: args
  });
};

if (require.main === module) {
  const output = process.argv[2] || '../../output/remotion-preview.mp4';
  renderDouyinExplainer({output}).catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
