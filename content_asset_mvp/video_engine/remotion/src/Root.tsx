import React from 'react';
import {Composition} from 'remotion';
import {DouyinExplainer} from './compositions/DouyinExplainer';
import {theme} from './styles/theme';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="DouyinExplainer"
      component={DouyinExplainer}
      durationInFrames={900}
      fps={30}
      width={theme.width}
      height={theme.height}
      defaultProps={{
        title: 'Overseas AI Radar',
        subtitles: []
      }}
    />
  );
};
