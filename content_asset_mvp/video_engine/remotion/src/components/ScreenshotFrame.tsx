import React from 'react';
import {theme} from '../styles/theme';

export const ScreenshotFrame: React.FC<{src?: string; caption?: string}> = ({src, caption}) => {
  return (
    <div
      style={{
        position: 'absolute',
        left: 78,
        right: 78,
        top: 620,
        height: 560,
        borderRadius: 32,
        background: theme.colors.panel,
        border: `3px solid ${theme.colors.accent}`,
        overflow: 'hidden',
        fontFamily: theme.fontFamily
      }}
    >
      {src ? (
        <img src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      ) : (
        <div style={{display: 'grid', placeItems: 'center', height: '100%', color: theme.colors.muted, fontSize: 34}}>
          Evidence visual placeholder
        </div>
      )}
      {caption ? (
        <div style={{position: 'absolute', left: 28, right: 28, bottom: 24, color: theme.colors.text, fontSize: 30}}>
          {caption}
        </div>
      ) : null}
    </div>
  );
};
