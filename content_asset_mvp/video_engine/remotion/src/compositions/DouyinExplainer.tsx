import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import {BigClaimCard} from '../components/BigClaimCard';
import {Cover} from '../components/Cover';
import {ScreenshotFrame} from '../components/ScreenshotFrame';
import {SubtitleCue, SubtitleLayer} from '../components/SubtitleLayer';
import {theme} from '../styles/theme';

export type DouyinExplainerProps = {
  title?: string;
  durationSeconds?: number;
  audioPath?: string;
  subtitles?: SubtitleCue[];
  evidenceImage?: string;
};

export const DouyinExplainer: React.FC<DouyinExplainerProps> = ({
  title = 'AI product signal worth watching',
  audioPath,
  subtitles = [],
  evidenceImage
}) => {
  return (
    <AbsoluteFill style={{backgroundColor: theme.colors.background}}>
      <Sequence from={0} durationInFrames={90}>
        <Cover title={title} />
      </Sequence>
      <Sequence from={90}>
        <BigClaimCard title={title} kicker="v6 industrial slice" />
        <ScreenshotFrame src={evidenceImage} caption="Evidence and product context" />
      </Sequence>
      <SubtitleLayer subtitles={subtitles} />
      {audioPath ? <Audio src={toAssetSource(audioPath)} /> : null}
    </AbsoluteFill>
  );
};

const toAssetSource = (src: string) => {
  if (src.startsWith('http') || src.startsWith('data:') || src.startsWith('file:')) {
    return src;
  }
  return staticFile(src);
};
