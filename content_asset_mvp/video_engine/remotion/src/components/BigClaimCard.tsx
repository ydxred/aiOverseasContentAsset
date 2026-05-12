import React from 'react';
import {theme} from '../styles/theme';

export const BigClaimCard: React.FC<{title: string; kicker?: string}> = ({title, kicker}) => {
  return (
    <div
      style={{
        position: 'absolute',
        left: 72,
        right: 72,
        top: 210,
        padding: '48px 44px',
        borderRadius: 36,
        background: `linear-gradient(135deg, ${theme.colors.panel}, #0f2845)`,
        boxShadow: `0 0 80px ${theme.colors.glow}`,
        color: theme.colors.text,
        fontFamily: theme.fontFamily
      }}
    >
      {kicker ? <div style={{fontSize: 32, color: theme.colors.accent, marginBottom: 20}}>{kicker}</div> : null}
      <div style={{fontSize: 74, fontWeight: 900, lineHeight: 1.08}}>{title}</div>
    </div>
  );
};
