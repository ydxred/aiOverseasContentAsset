import React from 'react';
import {Easing, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../styles/theme';

const PADDING_X = theme.landscape.shot.paddingX;

const toAssetSource = (src: string) => {
  if (src.startsWith('http') || src.startsWith('data:') || src.startsWith('file:')) {
    return src;
  }
  return staticFile(src);
};

export const CoverLandscape: React.FC<{title: string; source?: string; coverImage?: string}> = ({
  title,
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
  // Thumbnail Ken-Burns drift for the hero layout.
  const coverZoom = interpolate(frame, [0, 90], [1.04, 1.1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.cubic),
  });

  const blinkOn = Math.floor((time * 1.66) % 2) === 0;

  // Hero layout: 16:9 YouTube thumbnails slot cleanly into a 16:9 frame
  // without cropping, so give the hero image the full left 58% and keep
  // the right 42% for the title + source metadata. This matches the
  // MyElc reference where information sits beside the image rather than
  // being overlaid on top (which would waste the thumbnail's composition).
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
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: '58%',
            overflow: 'hidden',
          }}
        >
          <Img
            src={toAssetSource(coverImage)}
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'cover',
              objectPosition: 'center',
              transform: `scale(${coverZoom})`,
              filter: 'saturate(1.06) contrast(1.04)',
            }}
          />
          {/* Right-edge vignette so the title column's background transitions
              cleanly instead of hard-cutting at 58%. */}
          <div
            style={{
              position: 'absolute',
              inset: 0,
              background:
                'linear-gradient(90deg, rgba(7,10,15,0) 60%, rgba(7,10,15,0.7) 92%, rgba(7,10,15,0.95) 100%)',
            }}
          />
        </div>

        <div
          style={{
            position: 'absolute',
            left: '60%',
            right: PADDING_X,
            top: 200,
            opacity: titleOpacity,
            transform: `translateY(${titleTranslate}px)`,
          }}
        >
          <div
            style={{
              width: 8,
              height: 60,
              borderRadius: 4,
              background: `linear-gradient(180deg, ${theme.colors.primary}, ${theme.colors.secondary})`,
              boxShadow: `0 0 26px ${theme.colors.primarySoft}`,
              marginBottom: 22,
            }}
          />
          <div
            style={{
              fontSize: 72,
              lineHeight: 1.08,
              fontWeight: 950,
              color: '#FFFFFF',
              textShadow: '0 6px 32px rgba(0,0,0,0.85)',
            }}
          >
            {title}
            <span style={{color: theme.colors.primary, marginLeft: 6, opacity: blinkOn ? 1 : 0}}>
              ▍
            </span>
          </div>
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
      {/* Main: vertical centered title only — chrome (brand ribbon, In[00],
          open prompt, bottom output strip) was removed because it read as
          internal debug output instead of finished narrative video. */}
      <div
        style={{
          position: 'absolute',
          left: PADDING_X,
          right: PADDING_X,
          top: 180,
          bottom: 220
        }}
      >
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
              width: 10,
              minHeight: 240,
              borderRadius: 5,
              background: `linear-gradient(180deg, ${theme.colors.primary}, ${theme.colors.secondary})`,
              boxShadow: `0 0 30px ${theme.colors.primarySoft}`
            }}
          />
          <div
            style={{
              fontSize: 110,
              lineHeight: 1.05,
              fontWeight: 950,
              color: theme.colors.text,
              maxWidth: 1500,
              textShadow: '0 6px 32px rgba(0,0,0,0.55)'
            }}
          >
            {title}
            <span style={{color: theme.colors.primary, marginLeft: 6, opacity: blinkOn ? 1 : 0}}>▍</span>
          </div>
        </div>
      </div>

    </div>
  );
};
