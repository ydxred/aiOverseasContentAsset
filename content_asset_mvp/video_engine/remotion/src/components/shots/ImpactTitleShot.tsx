import React from 'react';
import {AbsoluteFill} from 'remotion';
import {theme} from '../../styles/theme';
import {SectionLabel} from '../SectionLabel';
import type {ShotTemplateProps} from './types';

// Heavy multi-direction stroke + drop shadow keeps the headline readable
// against any photo / thumbnail backdrop. Same recipe as SubtitleLayer.
const HEADLINE_TEXT_SHADOW = [
  '-3px -3px 0 #000',
  '3px -3px 0 #000',
  '-3px 3px 0 #000',
  '3px 3px 0 #000',
  '0 -3px 0 #000',
  '0 3px 0 #000',
  '-3px 0 0 #000',
  '3px 0 0 #000',
  '0 8px 30px rgba(0,0,0,0.85)',
  '0 0 40px rgba(0,0,0,0.55)',
].join(', ');

export const ImpactTitleShot: React.FC<ShotTemplateProps> = ({shot, title, shotIndex = 0}) => {
  const text = shot?.screen_text || title;
  const labelName = shot?.english_label || 'Definition';
  const labelStyle = shot?.label_style || 'comment';

  return (
    <AbsoluteFill style={{fontFamily: theme.fonts.ui, color: theme.colors.text}}>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />

      <div
        style={{
          position: 'absolute',
          left: 56,
          right: 56,
          top: 320,
          bottom: 380,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
        }}
      >
        <div style={{display: 'flex', alignItems: 'stretch', gap: 28}}>
          <div
            style={{
              width: 8,
              borderRadius: 4,
              background: `linear-gradient(180deg, ${theme.colors.secondary}, ${theme.colors.primary})`,
              boxShadow: `0 0 22px ${theme.colors.secondarySoft}`,
            }}
          />
          <div style={{flex: 1}}>
            <div
              style={{
                fontFamily: theme.fonts.mono,
                fontSize: 30,
                color: theme.colors.secondary,
                marginBottom: 26,
                letterSpacing: 0.5,
                textShadow: '0 2px 12px rgba(0,0,0,0.85)',
              }}
            >
              # def {labelName.toLowerCase().replace(/\s+/g, '_')}() -&gt;
            </div>
            <div
              style={{
                fontSize: 116,
                lineHeight: 1.04,
                fontWeight: 950,
                color: theme.colors.text,
                textShadow: HEADLINE_TEXT_SHADOW,
                wordBreak: 'break-word',
              }}
            >
              {text}
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
