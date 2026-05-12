import React from 'react';
import {AbsoluteFill} from 'remotion';
import {theme} from '../styles/theme';

// Persistent brand watermark anchored to the bottom-right safe zone.
//
// Why we add this:
// ----------------
// Mainstream Chinese AI/科技 short-video creators (MyElc / 计算机大白 /
// 阿浩 / 李华Bro) ALL keep an account watermark visible during the body
// of the video — typically a small platform icon + handle + "搜 XX 看
// 更多" line in the bottom corner. It serves three jobs:
//
//   1. Brand recall when the algorithm shows the same viewer multiple
//      videos in a row (this is the dominant short-video reach pattern
//      on 抖音 / 视频号).
//   2. Anti-piracy / cross-platform stamping (when our content gets
//      re-uploaded by搬运号, the watermark survives the codec re-encode
//      and acts as a tracking signal).
//   3. Signals that the video is a finished, branded explainer rather
//      than a captured clip. This was the single missing element when
//      we A/B'd our render against IMG_5835 (MyElc).
//
// Design constraints:
// -------------------
// * Live in the bottom-right corner of the 16:9 landscape canvas, NOT
//   the bottom-left where the headline / CTA blocks already sit.
// * Stay above the subtitle band but below the active shot content.
// * Use the same panel border / muted text colour the rest of the
//   templates use, so it reads as part of the system, not a sticker.
// * Do not show on the cover (the cover already presents the brand
//   ribbon big and centred).
//
// Configuration:
// --------------
// All copy is overrideable via the props (handle / platform label /
// search hint). Default values match the "海外 AI 信号" account the
// pipeline currently produces for; swap them when we wire multiple
// accounts.
export type BrandWatermarkProps = {
  handle?: string;
  platformLabel?: string;
  searchHint?: string;
  // Hide entirely when ``visible=false`` (cover sequence passes this).
  visible?: boolean;
};

export const BrandWatermark: React.FC<BrandWatermarkProps> = ({
  handle = '@海外 AI 信号',
  visible = true,
}) => {
  if (!visible) return null;
  return (
    <AbsoluteFill
      style={{
        pointerEvents: 'none',
      }}
    >
      {/* Single-line minimal watermark. Originally three lines (handle +
          platform + search hint) but that's a 3-line block stamped on
          every frame — reads as overlay clutter rather than brand mark.
          Reference creators (MyElc / 计算机大白) keep watermark to a
          single handle line; the search-hint copy belongs in the outro
          card, not as persistent chrome. ``platformLabel`` and
          ``searchHint`` props are still accepted so callers don't break. */}
      <div
        style={{
          position: 'absolute',
          right: 36,
          bottom: 36,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 14px',
          borderRadius: 999,
          background: 'rgba(7,10,15,0.5)',
          border: `1px solid ${theme.colors.panelBorder}`,
          backdropFilter: 'blur(4px)',
          WebkitBackdropFilter: 'blur(4px)',
          fontFamily: theme.fonts.ui,
          fontSize: 18,
          fontWeight: 600,
          color: theme.colors.textSoft,
          letterSpacing: 0.3,
          opacity: 0.75,
        }}
      >
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: theme.colors.primary,
            boxShadow: `0 0 8px ${theme.colors.primary}`,
          }}
        />
        {handle}
      </div>
    </AbsoluteFill>
  );
};
