import React from 'react';
import {theme} from '../styles/theme';

type ChromeKind = 'terminal' | 'browser' | 'jupyter';

const TITLE_BAR_HEIGHT = 64;

const renderTrafficLights = () => (
  <div style={{display: 'flex', gap: 10, alignItems: 'center'}}>
    <span
      style={{
        width: 18,
        height: 18,
        borderRadius: '50%',
        background: '#FF5F57',
        boxShadow: '0 0 0 1px rgba(0,0,0,0.18) inset'
      }}
    />
    <span style={{width: 18, height: 18, borderRadius: '50%', background: '#FEBC2E'}} />
    <span style={{width: 18, height: 18, borderRadius: '50%', background: '#28C840'}} />
  </div>
);

const renderBrowserBar = (title: string) => (
  <div
    style={{
      flex: 1,
      marginLeft: 22,
      marginRight: 22,
      height: 36,
      borderRadius: 18,
      background: '#0B0E13',
      border: `1px solid ${theme.colors.panelBorder}`,
      display: 'flex',
      alignItems: 'center',
      padding: '0 18px',
      color: theme.colors.textSoft,
      fontFamily: theme.fonts.mono,
      fontSize: 18,
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      letterSpacing: 0.4
    }}
  >
    <span style={{color: theme.colors.muted, marginRight: 10}}>https://</span>
    {title}
  </div>
);

const renderTerminalBar = (title: string, kind: ChromeKind) => (
  <div
    style={{
      flex: 1,
      marginLeft: 22,
      color: theme.colors.textSoft,
      fontFamily: theme.fonts.mono,
      fontSize: 20,
      letterSpacing: 0.4,
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis'
    }}
  >
    {kind === 'jupyter' ? (
      <>
        <span style={{color: theme.colors.warning, marginRight: 10}}>jupyter</span>
        <span style={{color: theme.colors.muted, marginRight: 6}}>~</span>
        {title}
      </>
    ) : (
      <>
        <span style={{color: theme.colors.muted, marginRight: 6}}>—</span>
        {title}
        <span style={{color: theme.colors.muted, marginLeft: 6}}>—</span>
      </>
    )}
  </div>
);

export const TerminalChrome: React.FC<{
  kind?: ChromeKind;
  title: string;
  children: React.ReactNode;
  innerStyle?: React.CSSProperties;
  glowColor?: string;
}> = ({kind = 'terminal', title, children, innerStyle, glowColor}) => {
  const borderGlow = glowColor || theme.colors.primarySoft;
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        borderRadius: 22,
        overflow: 'hidden',
        background: theme.colors.panel,
        border: `1px solid ${theme.colors.panelBorder}`,
        boxShadow: `0 24px 80px rgba(0,0,0,0.55), 0 0 0 1px ${borderGlow}`,
        display: 'flex',
        flexDirection: 'column'
      }}
    >
      <div
        style={{
          height: TITLE_BAR_HEIGHT,
          background: 'linear-gradient(180deg, #1F242B 0%, #161B22 100%)',
          borderBottom: `1px solid ${theme.colors.panelBorder}`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 22px',
          flexShrink: 0
        }}
      >
        {renderTrafficLights()}
        {kind === 'browser'
          ? renderBrowserBar(title)
          : renderTerminalBar(title, kind)}
      </div>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          background: theme.colors.background,
          overflow: 'hidden',
          position: 'relative',
          ...innerStyle
        }}
      >
        {children}
      </div>
    </div>
  );
};

export const CHROME_TITLE_BAR_HEIGHT = TITLE_BAR_HEIGHT;
