import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../styles/theme';

export type SubtitleCue = {
  start: number;
  end: number;
  text: string;
  highlight_words?: string[];
  style?: string;
  safe_area?: {x: number; y: number; width: number; height: number};
};

export const SubtitleLayer: React.FC<{subtitles: SubtitleCue[]}> = ({subtitles}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const time = frame / fps;
  const cue = subtitles.find((item) => time >= item.start && time <= item.end);
  if (!cue) {
    return null;
  }
  const safeArea = cue.safe_area ?? theme.safeArea;
  const opacity = interpolate(frame, [cue.start * fps, cue.start * fps + 6], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp'
  });
  return (
    <div
      style={{
        position: 'absolute',
        left: safeArea.x,
        top: safeArea.y,
        width: safeArea.width,
        minHeight: safeArea.height,
        opacity,
        color: theme.colors.text,
        fontFamily: theme.fontFamily,
        fontSize: cue.style === 'big_claim' ? 58 : 48,
        fontWeight: 850,
        lineHeight: 1.18,
        textAlign: 'center',
        textShadow: '0 6px 18px rgba(0,0,0,0.7)'
      }}
    >
      {cue.text}
    </div>
  );
};
