import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../../styles/theme';
import {SectionLabel} from '../SectionLabel';
import type {ShotTemplateProps} from './types';

const sanitizeVarName = (raw: string) => {
  const ascii = raw
    .normalize('NFKD')
    .replace(/[^\x00-\x7F]/g, '')
    .replace(/[^A-Za-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toUpperCase();
  return ascii || 'KEY_INSIGHT';
};

// Match money ("¥23,967"), plain numbers with optional unit ("225k", "2M", "40分钟"),
// and percentages. Capture groups tag which kind so styling can vary.
//
// MyElc's reference video lets one number per card breathe ("¥23,967 / 年")
// so we only highlight when the text *contains* a number — we do not split
// each character into its own span, which would be unreadable at 160px.
const NUMBER_PATTERN =
  /([¥$€￥]?\d[\d,.]*[kKmMwW万亿百千％%]?[分秒年月日年岁次个项条位位美元]?(?:\s*[\/／]\s*\d[\d,.]*[年月日次分秒])?|\d+%)/;

type TextChunk = {
  text: string;
  isNumber: boolean;
};

const splitByNumbers = (raw: string): TextChunk[] => {
  const trimmed = raw.trim();
  if (!trimmed) return [{text: '', isNumber: false}];
  const match = trimmed.match(NUMBER_PATTERN);
  if (!match || match.index == null) {
    return [{text: trimmed, isNumber: false}];
  }
  const chunks: TextChunk[] = [];
  if (match.index > 0) {
    chunks.push({text: trimmed.slice(0, match.index), isNumber: false});
  }
  chunks.push({text: match[0], isNumber: true});
  const tail = trimmed.slice(match.index + match[0].length);
  if (tail) {
    chunks.push({text: tail, isNumber: false});
  }
  return chunks;
};

export const KeywordPunchShot: React.FC<ShotTemplateProps> = ({shot, shotIndex = 0}) => {
  const text = shot?.screen_text || '关键词';
  const labelName = shot?.english_label || 'spotlight';
  const labelStyle = shot?.label_style || 'cell';
  const varName = sanitizeVarName(shot?.english_label || 'KEY_INSIGHT');

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // Spring-driven rise-and-settle: lifts from 80px below + fades in, then
  // the headline breathes via a subtle scale pulse. Matches the cadence on
  // MyElc's "¥23,967 / 年" frame (25s).
  const rise = spring({frame, fps, config: {damping: 22, stiffness: 110, mass: 0.9}});
  const headlineTranslate = interpolate(rise, [0, 1], [80, 0]);
  const headlineOpacity = interpolate(rise, [0, 1], [0, 1]);
  const pulse = interpolate(frame, [18, 36, 60], [1.0, 1.04, 1.0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const chunks = splitByNumbers(text);
  const hasNumber = chunks.some((c) => c.isNumber);

  return (
    <AbsoluteFill style={{fontFamily: theme.fonts.ui, color: theme.colors.text}}>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />

      <div
        style={{
          position: 'absolute',
          left: 56,
          right: 56,
          top: 360,
          bottom: 420,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            fontFamily: theme.fonts.mono,
            fontSize: 32,
            marginBottom: 30,
            color: theme.colors.muted,
            letterSpacing: 0.6,
            opacity: 0.92,
            textShadow: '0 2px 12px rgba(0,0,0,0.85)',
          }}
        >
          <span style={{color: theme.colors.secondary}}>{varName}</span>
          <span style={{color: theme.colors.muted, margin: '0 14px'}}>=</span>
          <span style={{color: theme.colors.warning}}>"</span>
        </div>

        <div
          style={{
            opacity: headlineOpacity,
            transform: `translateY(${headlineTranslate}px) scale(${pulse})`,
            transformOrigin: 'left center',
            fontSize: 168,
            lineHeight: 1.02,
            fontWeight: 950,
            letterSpacing: 0.5,
            color: theme.colors.primary,
            // 8-direction black stroke via textShadow keeps fills intact while
            // giving the headline weight. Outer glow tightens when numbers
            // are present so the highlighted digits pop.
            textShadow: [
              '-2px -2px 0 #000',
              '2px -2px 0 #000',
              '-2px 2px 0 #000',
              '2px 2px 0 #000',
              '0 -2px 0 #000',
              '0 2px 0 #000',
              '-2px 0 0 #000',
              '2px 0 0 #000',
              `0 0 44px ${theme.colors.primarySoft}`,
              '0 10px 34px rgba(0,0,0,0.75)',
            ].join(', '),
            wordBreak: 'break-word',
          }}
        >
          {chunks.map((chunk, idx) =>
            chunk.isNumber ? (
              <span
                key={idx}
                style={{
                  color: theme.colors.warning,
                  // A slightly tighter letter spacing on digits reads as
                  // deliberate "number pop" instead of accidental kerning.
                  letterSpacing: 0,
                  textShadow: [
                    '-2px -2px 0 #000',
                    '2px -2px 0 #000',
                    '-2px 2px 0 #000',
                    '2px 2px 0 #000',
                    `0 0 38px ${theme.colors.warning}`,
                    `0 0 72px ${theme.colors.warning}`,
                    '0 10px 34px rgba(0,0,0,0.8)',
                  ].join(', '),
                }}
              >
                {chunk.text}
              </span>
            ) : (
              <span key={idx}>{chunk.text}</span>
            ),
          )}
        </div>

        <div
          style={{
            fontFamily: theme.fonts.mono,
            fontSize: 32,
            marginTop: 22,
            color: theme.colors.warning,
            opacity: headlineOpacity * 0.85,
            textShadow: '0 2px 12px rgba(0,0,0,0.85)',
          }}
        >
          " {hasNumber ? <span style={{color: theme.colors.muted}}>// number detected</span> : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
