import React from 'react';
import {staticFile} from 'remotion';
import {theme} from '../styles/theme';

export const ScreenshotFrame: React.FC<{src?: string; caption?: string; role?: string}> = ({src, caption, role}) => {
  const isFocusedCapture = role?.includes('browser_focus');
  const transformOrigin = role?.includes('docs') ? 'top left' : 'top center';
  const focusLabel = focusCopy(role);

  return (
    <div
      style={{
        position: 'absolute',
        left: 28,
        right: 28,
        top: 396,
        height: 800,
        borderRadius: 32,
        background: theme.colors.panel,
        border: `3px solid ${theme.colors.accent}`,
        overflow: 'hidden',
        fontFamily: theme.fontFamily,
        boxShadow: `0 0 68px ${theme.colors.glow}`
      }}
    >
      {src ? (
        <img
          src={toAssetSource(src)}
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            background: '#ffffff',
            transform: isFocusedCapture ? 'scale(1.06)' : 'scale(1.72)',
            transformOrigin,
            filter: 'contrast(1.08) saturate(1.04)'
          }}
        />
      ) : (
        <div style={{display: 'grid', placeItems: 'center', height: '100%', color: theme.colors.muted, fontSize: 34}}>
          Evidence visual placeholder
        </div>
      )}
      <div
        style={{
          position: 'absolute',
          left: 34,
          top: 34,
          padding: '13px 18px',
          borderRadius: 999,
          background: 'rgba(6,18,31,0.78)',
          border: '2px solid rgba(56,189,248,0.85)',
          color: theme.colors.text,
          fontSize: 26,
          fontWeight: 850
        }}
      >
        {focusLabel}
      </div>
      <div
        style={{
          position: 'absolute',
          left: role?.includes('quickstart') || role?.includes('cli') ? 88 : 76,
          top: role?.includes('demo') ? 176 : 124,
          width: role?.includes('releases') ? 560 : 690,
          height: role?.includes('repo') ? 160 : 230,
          borderRadius: 24,
          border: '7px solid rgba(56,189,248,0.92)',
          boxShadow: '0 0 0 9999px rgba(2,6,23,0.16), 0 0 36px rgba(56,189,248,0.42)',
          pointerEvents: 'none'
        }}
      />
      {caption ? (
        <div
          style={{
            position: 'absolute',
            left: 28,
            right: 28,
            bottom: 24,
            padding: '14px 18px',
            borderRadius: 18,
            background: 'rgba(15, 23, 42, 0.78)',
            color: theme.colors.text,
            fontSize: 28,
            lineHeight: 1.18
          }}
        >
          {caption}
        </div>
      ) : null}
    </div>
  );
};

const focusCopy = (role?: string) => {
  if (role?.includes('demo')) {
    return '看 Demo：真实场景';
  }
  if (role?.includes('quickstart')) {
    return '看 Quickstart：上手门槛';
  }
  if (role?.includes('cli')) {
    return '看 CLI：自动化入口';
  }
  if (role?.includes('releases')) {
    return '看 Release：项目活跃度';
  }
  return '看核心证据';
};

const toAssetSource = (src: string) => {
  if (src.startsWith('http') || src.startsWith('data:') || src.startsWith('file:')) {
    return src;
  }
  return staticFile(src);
};
