import React from 'react';
import {AbsoluteFill} from 'remotion';

/**
 * Two thin dark gradient bars at the top and bottom of the canvas.
 *
 * Sits between the fullscreen evidence layer and the shot foreground (text,
 * subtitles, brand mark). Without this, white subtitles sometimes land on a
 * bright sky / face and become unreadable; with it, the top logo and bottom
 * subtitle band always sit on guaranteed dark pixels.
 *
 *  - ``top``: protects logo / SectionLabel.
 *  - ``bottom``: protects subtitle band.
 *  - ``middle``: optional centre dim used by motion-graphics shots
 *    (KeywordPunch / Judgement) that need extra contrast for huge type.
 */
export const EdgeGradient: React.FC<{
  topHeightPct?: number;
  bottomHeightPct?: number;
  /** When >0, applies a flat overlay across the whole canvas (0..1). */
  middleDim?: number;
}> = ({topHeightPct = 10, bottomHeightPct = 22, middleDim = 0}) => {
  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      {middleDim > 0 ? (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: `rgba(0,0,0,${Math.max(0, Math.min(1, middleDim))})`,
          }}
        />
      ) : null}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 0,
          height: `${topHeightPct}%`,
          background:
            'linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.3) 55%, rgba(0,0,0,0) 100%)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          height: `${bottomHeightPct}%`,
          background:
            'linear-gradient(0deg, rgba(0,0,0,0.78) 0%, rgba(0,0,0,0.5) 45%, rgba(0,0,0,0.2) 75%, rgba(0,0,0,0) 100%)',
        }}
      />
    </AbsoluteFill>
  );
};
