import React from 'react';
import {Easing, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../styles/theme';

const toAssetSource = (src: string) => {
  if (src.startsWith('http') || src.startsWith('data:') || src.startsWith('file:')) {
    return src;
  }
  return staticFile(src);
};

export const Cover: React.FC<{title: string; source?: string; coverImage?: string}> = ({
  title,
  source,
  coverImage,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const time = frame / fps;

  const titleOpacity = interpolate(frame, [10, 28], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic)
  });
  const titleTranslate = interpolate(frame, [10, 28], [22, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic)
  });
  const sourceOpacity = interpolate(frame, [40, 58], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp'
  });

  // Cursor blink
  const blinkOn = Math.floor((time * 1.66) % 2) === 0;

  // Slow Ken-Burns zoom on the hero image keeps the first 3 seconds
  // feeling cinematic rather than a flat still — matches how Douyin
  // hook frames typically drift during the hook.
  const coverZoom = interpolate(frame, [0, 90], [1.06, 1.12], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.cubic),
  });

  if (coverImage) {
    return (
      <div
        style={{
          width: '100%',
          height: '100%',
          color: theme.colors.text,
          fontFamily: theme.fonts.ui,
          position: 'relative',
          background: theme.colors.background,
          overflow: 'hidden',
        }}
      >
        <Img
          src={toAssetSource(coverImage)}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            objectPosition: 'center',
            transform: `scale(${coverZoom})`,
            filter: 'saturate(1.08) contrast(1.05)',
          }}
        />

        {/* Bottom gradient scrim so white title text stays legible over
            whatever the hero image happens to be. Top scrim is lighter to
            keep the image readable but still give the brand badge bite. */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background:
              'linear-gradient(180deg, rgba(7,10,15,0.55) 0%, rgba(7,10,15,0) 22%, rgba(7,10,15,0) 45%, rgba(7,10,15,0.82) 78%, rgba(7,10,15,0.95) 100%)',
          }}
        />

        <div
          style={{
            position: 'absolute',
            left: 56,
            top: 132,
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            fontFamily: theme.fonts.mono,
            color: theme.colors.textSoft,
            fontSize: 22,
            letterSpacing: 0.6,
          }}
        >
          <span
            style={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              background: theme.colors.primary,
              boxShadow: `0 0 14px ${theme.colors.primary}`,
            }}
          />
          <span style={{color: theme.colors.primary, fontWeight: 700}}>ai-radar</span>
          <span style={{color: theme.colors.muted}}>·</span>
          <span style={{color: theme.colors.textSoft}}>海外 AI 信号</span>
        </div>

        <div
          style={{
            position: 'absolute',
            left: 56,
            right: 56,
            bottom: 240,
            opacity: titleOpacity,
            transform: `translateY(${titleTranslate}px)`,
            display: 'flex',
            alignItems: 'flex-start',
            gap: 24,
          }}
        >
          <div
            style={{
              width: 8,
              minHeight: 180,
              borderRadius: 4,
              background: `linear-gradient(180deg, ${theme.colors.primary}, ${theme.colors.secondary})`,
              boxShadow: `0 0 26px ${theme.colors.primarySoft}`,
            }}
          />
          <div
            style={{
              fontSize: 92,
              lineHeight: 1.05,
              fontWeight: 950,
              color: '#FFFFFF',
              maxWidth: 900,
              textShadow: '0 6px 32px rgba(0,0,0,0.85), 0 2px 6px rgba(0,0,0,0.7)',
            }}
          >
            {title}
            <span
              style={{
                color: theme.colors.primary,
                marginLeft: 6,
                opacity: blinkOn ? 1 : 0,
              }}
            >
              ▍
            </span>
          </div>
        </div>

        <div
          style={{
            position: 'absolute',
            left: 56,
            right: 56,
            bottom: 160,
            opacity: sourceOpacity,
            fontFamily: theme.fonts.mono,
            fontSize: 22,
            color: theme.colors.textSoft,
            letterSpacing: 0.4,
          }}
        >
          <span style={{color: theme.colors.warning}}>source</span>
          <span style={{color: theme.colors.muted}}> = </span>
          <span style={{color: theme.colors.primary}}>
            "{source || 'verified package'}"
          </span>
          <span style={{color: theme.colors.muted, marginLeft: 12}}>//</span>
          <span style={{color: theme.colors.muted, marginLeft: 6}}>v0.1 · daily build</span>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        color: theme.colors.text,
        fontFamily: theme.fonts.ui,
        position: 'relative'
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 56,
          top: 132,
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          fontFamily: theme.fonts.mono,
          color: theme.colors.textSoft,
          fontSize: 22,
          letterSpacing: 0.6
        }}
      >
        <span
          style={{
            width: 12,
            height: 12,
            borderRadius: '50%',
            background: theme.colors.primary,
            boxShadow: `0 0 14px ${theme.colors.primary}`
          }}
        />
        <span style={{color: theme.colors.primary, fontWeight: 700}}>ai-radar</span>
        <span style={{color: theme.colors.muted}}>—</span>
        <span style={{color: theme.colors.muted}}>v0.1 · daily build</span>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 56,
          right: 56,
          top: 360
        }}
      >
        <div
          style={{
            fontFamily: theme.fonts.mono,
            fontSize: 30,
            color: theme.colors.secondary,
            letterSpacing: 0.5,
            marginBottom: 22
          }}
        >
          In [00]: <span style={{color: theme.colors.muted}}>cover()</span>
        </div>

        <div
          style={{
            fontFamily: theme.fonts.mono,
            fontSize: 32,
            color: theme.colors.primary,
            marginBottom: 36
          }}
        >
          $ open <span style={{color: theme.colors.text}}>'{source || 'overseas-ai-asset'}'</span>
        </div>

        <div
          style={{
            opacity: titleOpacity,
            transform: `translateY(${titleTranslate}px)`,
            display: 'flex',
            alignItems: 'flex-start',
            gap: 28
          }}
        >
          <div
            style={{
              width: 8,
              minHeight: 240,
              borderRadius: 4,
              background: `linear-gradient(180deg, ${theme.colors.primary}, ${theme.colors.secondary})`,
              boxShadow: `0 0 26px ${theme.colors.primarySoft}`
            }}
          />
          <div
            style={{
              fontSize: 96,
              lineHeight: 1.05,
              fontWeight: 950,
              color: theme.colors.text,
              maxWidth: 880,
              textShadow: '0 6px 32px rgba(0,0,0,0.55)'
            }}
          >
            {title}
            <span style={{color: theme.colors.primary, marginLeft: 6, opacity: blinkOn ? 1 : 0}}>▍</span>
          </div>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 56,
          right: 56,
          bottom: 180,
          opacity: sourceOpacity,
          fontFamily: theme.fonts.mono,
          fontSize: 24,
          color: theme.colors.textSoft,
          letterSpacing: 0.4
        }}
      >
        <div style={{color: theme.colors.muted, marginBottom: 10}}>// out[00]</div>
        <div>
          <span style={{color: theme.colors.warning}}>source</span>
          <span style={{color: theme.colors.muted}}> = </span>
          <span style={{color: theme.colors.primary}}>"{source || 'verified package'}"</span>
        </div>
        <div style={{marginTop: 6}}>
          <span style={{color: theme.colors.warning}}>verified</span>
          <span style={{color: theme.colors.muted}}> = </span>
          <span style={{color: theme.colors.secondary}}>True</span>
        </div>
      </div>
    </div>
  );
};
