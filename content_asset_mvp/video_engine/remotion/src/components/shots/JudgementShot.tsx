import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../../styles/theme';
import {SectionLabel} from '../SectionLabel';
import type {ShotTemplateProps} from './types';

// Prompt line shown above the CTA pills. Tries to pull an action-phrase
// from shot.screen_text itself; falls back to a generic invitation.
//
// This is deliberately kept short because the pills are the real CTA —
// the line above is just a verbal bridge.
const CTA_PROMPTS = [
  '说说你是怎么看的',
  '你会用它干什么',
  '留言告诉我',
];

const pickPrompt = (seed: string): string => {
  const hash = Array.from(seed).reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  return CTA_PROMPTS[hash % CTA_PROMPTS.length];
};

// Judgement + CTA combined card. Keeps the "assert(claim, 'why')" Python
// framing that identifies our brand, adds the MyElc-style 关注/评论/收藏
// pills and "下期见" stinger for platform algorithm signal.
//
// We chose this over a separate cta_card shot because it's one slot
// instead of two (keeps the 50–180s video clock from ballooning), and
// because every signal we ship is worth a takeaway — combining takeaway
// and CTA in one frame mirrors how MyElc does it (final 6s: invite +
// question + pills + 下期见).
export const JudgementShot: React.FC<ShotTemplateProps> = ({shot, shotIndex = 0}) => {
  const text = shot?.screen_text || '我们的判断';
  const labelName = shot?.english_label || 'Take & CTA';
  const labelStyle = shot?.label_style || 'comment';

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  // Staged spring entrances: claim first (hero), pills slightly later so
  // the eye lands on the takeaway before noticing the call-to-action.
  const claimSpring = spring({frame, fps, config: {damping: 22, stiffness: 110, mass: 0.9}});
  const pillsSpring = spring({
    frame: Math.max(0, frame - 18),
    fps,
    config: {damping: 20, stiffness: 130, mass: 0.7},
  });

  const claimTranslate = interpolate(claimSpring, [0, 1], [40, 0]);
  const claimOpacity = interpolate(claimSpring, [0, 1], [0, 1]);
  const pillsTranslate = interpolate(pillsSpring, [0, 1], [24, 0]);
  const pillsOpacity = interpolate(pillsSpring, [0, 1], [0, 1]);

  const prompt = pickPrompt(text);

  return (
    <AbsoluteFill style={{fontFamily: theme.fonts.ui, color: theme.colors.text}}>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />

      <div
        style={{
          position: 'absolute',
          left: 56,
          right: 56,
          top: 280,
          bottom: 380,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        <div style={{opacity: claimOpacity, transform: `translateY(${claimTranslate}px)`}}>
          <div
            style={{
              fontFamily: theme.fonts.mono,
              fontSize: 30,
              color: theme.colors.warning,
              marginBottom: 28,
              letterSpacing: 0.6,
              textShadow: '0 2px 12px rgba(0,0,0,0.85)',
            }}
          >
            assert <span style={{color: theme.colors.muted}}>(</span>
          </div>

          <div
            style={{
              fontSize: 104,
              lineHeight: 1.06,
              fontWeight: 950,
              color: theme.colors.text,
              textShadow: [
                '-3px -3px 0 #000',
                '3px -3px 0 #000',
                '-3px 3px 0 #000',
                '3px 3px 0 #000',
                '0 -3px 0 #000',
                '0 3px 0 #000',
                '-3px 0 0 #000',
                '3px 0 0 #000',
                '0 8px 30px rgba(0,0,0,0.85)',
              ].join(', '),
              maxWidth: '94%',
            }}
          >
            <span
              style={{
                background: `linear-gradient(180deg, transparent 60%, ${theme.colors.warningSoft} 60%)`,
                padding: '0 6px',
              }}
            >
              {text}
            </span>
          </div>

          <div
            style={{
              fontFamily: theme.fonts.mono,
              fontSize: 30,
              color: theme.colors.warning,
              marginTop: 28,
              letterSpacing: 0.6,
            }}
          >
            <span style={{color: theme.colors.muted}}>)</span>,{' '}
            <span style={{color: theme.colors.secondary}}>"why"</span>
          </div>
        </div>

        {/* CTA block — anchored to the bottom so even if the claim text
            wraps onto 3 lines the pills stay in a predictable spot. */}
        <div
          style={{
            opacity: pillsOpacity,
            transform: `translateY(${pillsTranslate}px)`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 22,
            paddingBottom: 8,
          }}
        >
          <div
            style={{
              fontFamily: theme.fonts.ui,
              fontSize: 34,
              color: theme.colors.textSoft,
              letterSpacing: 0.3,
            }}
          >
            {prompt}
          </div>
          <div style={{display: 'flex', gap: 28}}>
            <CtaPill icon="+" label="关注" color={theme.colors.primary} glow={theme.colors.primarySoft} />
            <CtaPill icon="💬" label="评论" color={theme.colors.secondary} glow={theme.colors.secondarySoft} />
            <CtaPill icon="★" label="收藏" color={theme.colors.warning} glow={theme.colors.warningSoft} />
          </div>
          <div
            style={{
              fontFamily: theme.fonts.mono,
              fontSize: 26,
              color: theme.colors.muted,
              letterSpacing: 0.5,
              marginTop: 6,
            }}
          >
            // 下期见
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const CtaPill: React.FC<{icon: string; label: string; color: string; glow: string}> = ({
  icon,
  label,
  color,
  glow,
}) => {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '16px 32px',
        borderRadius: 999,
        background: 'rgba(11,14,19,0.75)',
        border: `2px solid ${color}`,
        boxShadow: `0 0 26px ${glow}, inset 0 0 14px rgba(0,0,0,0.4)`,
        color,
        fontFamily: theme.fonts.ui,
        fontSize: 32,
        fontWeight: 700,
        letterSpacing: 0.4,
      }}
    >
      <span style={{fontSize: 30, lineHeight: 1}}>{icon}</span>
      <span>{label}</span>
    </div>
  );
};
