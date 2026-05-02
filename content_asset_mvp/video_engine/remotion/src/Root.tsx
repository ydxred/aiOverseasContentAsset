import React from 'react';
import {Composition} from 'remotion';
import {DouyinExplainer, DouyinExplainerProps} from './compositions/DouyinExplainer';
import {theme} from './styles/theme';

const fps = 30;

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="DouyinExplainer"
      component={DouyinExplainer}
      durationInFrames={900}
      fps={fps}
      width={theme.width}
      height={theme.height}
      calculateMetadata={({props}) => {
        const durationSeconds = Number((props as DouyinExplainerProps).durationSeconds || 30);
        return {
          durationInFrames: Math.max(90, Math.ceil(durationSeconds * fps))
        };
      }}
      defaultProps={{
        title: 'Overseas AI Radar',
        durationSeconds: 30,
        subtitles: []
      }}
    />
  );
};
