import React from 'react';
import {theme} from '../styles/theme';

export const Cover: React.FC<{title: string; source?: string}> = ({title, source}) => {
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        background: `radial-gradient(circle at 20% 15%, ${theme.colors.glow}, transparent 34%), ${theme.colors.background}`,
        color: theme.colors.text,
        fontFamily: theme.fontFamily,
        padding: 78,
        boxSizing: 'border-box'
      }}
    >
      <div style={{fontSize: 34, color: theme.colors.accent, fontWeight: 800}}>Overseas AI Radar</div>
      <div style={{position: 'absolute', left: 78, right: 78, top: 440, fontSize: 82, lineHeight: 1.08, fontWeight: 950}}>
        {title}
      </div>
      <div style={{position: 'absolute', left: 78, bottom: 120, fontSize: 32, color: theme.colors.muted}}>
        {source || 'Source verified package'}
      </div>
    </div>
  );
};
