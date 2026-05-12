import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../styles/theme';

export type SubtitleCue = {
  start: number;
  end: number;
  text: string;
  highlight_words?: string[];
  style?: string;
  safe_area?: {x: number; y: number; width: number; height: number};
};

export const SubtitleLayer: React.FC<{
  subtitles: SubtitleCue[];
  /**
   * If set, suppress subtitle rendering before this absolute frame.
   * Used so the Cover sequence doesn't have the narration's first line
   * fighting for attention with the cover's big claim title.
   */
  hideBeforeFrame?: number;
}> = ({subtitles, hideBeforeFrame = 0}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  if (frame < hideBeforeFrame) {
    return null;
  }
  const time = frame / fps;
  const cue = subtitles.find((item) => time >= item.start && time <= item.end);
  if (!cue) {
    return null;
  }
  // Pick the right default safe area based on composition orientation.
  const isLandscape = width >= height;
  const defaultArea = isLandscape ? theme.landscape.safeArea : theme.safeArea;
  // Cues can override with their own ``safe_area``, but only if it actually
  // fits inside the current composition. Otherwise fall back to the default.
  // The subtitle plan is generated for portrait (y=1220 etc.) and would clip
  // off-screen if reused as-is in a landscape render.
  const cueArea = cue.safe_area;
  const cueFits =
    cueArea != null &&
    cueArea.x + cueArea.width <= width &&
    cueArea.y + cueArea.height <= height;
  const safeArea = cueFits && cueArea ? cueArea : defaultArea;
  // For portrait keep the historical floor of y >= 1288 to dodge phone UI.
  // Landscape uses the safeArea.y directly (already inside frame).
  const subtitleTop = isLandscape ? safeArea.y : Math.max(safeArea.y, 1288);
  const opacity = interpolate(frame, [cue.start * fps, cue.start * fps + 6], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp'
  });
  // Slightly larger now that we no longer hide behind a panel background.
  const baseSize = isLandscape ? 44 : 52;
  const bigSize = isLandscape ? 56 : 64;
  const fontSize = cue.style === 'big_claim' ? bigSize : baseSize;

  // Multi-layer text shadow simulates a thick black stroke + soft drop
  // shadow. This is what 影视飓风 / Fireship / ThePrimeagen do — no panel,
  // just heavy outline so the subtitle reads on any background.
  const subtitleShadow = [
    // 8-direction 3px black "stroke"
    '-3px -3px 0 #000',
    '3px -3px 0 #000',
    '-3px 3px 0 #000',
    '3px 3px 0 #000',
    '0 -3px 0 #000',
    '0 3px 0 #000',
    '-3px 0 0 #000',
    '3px 0 0 #000',
    // soft drop shadow for separation from background
    '0 6px 22px rgba(0,0,0,0.95)',
    '0 0 32px rgba(0,0,0,0.65)'
  ].join(', ');

  return (
    <div
      style={{
        position: 'absolute',
        left: safeArea.x,
        top: subtitleTop,
        width: safeArea.width,
        minHeight: safeArea.height,
        opacity,
        color: theme.colors.text,
        fontFamily: theme.fonts.ui,
        fontSize,
        fontWeight: 900,
        lineHeight: 1.18,
        textAlign: 'center',
        letterSpacing: 0.4,
        textShadow: subtitleShadow,
        boxSizing: 'border-box'
      }}
    >
      {renderHighlighted(cue.text, cue.highlight_words || [])}
    </div>
  );
};

// Subtitle keyword highlight color. Previously we used theme.colors.primary
// (#5EFF8F / acid green) — the green is fine for terminal text but underwhelming
// against a real subtitle that also has a black stroke. The three Chinese
// short-video reference accounts (@计算机大白 / MyElc / 课程式博主) all use
// warm gold for keyword highlights because gold pops harder against any
// background — dark, light, and the photo/screenshot mix in between. Switching
// to gold immediately makes the keyword feel "punctuated", not just colored.
const HIGHLIGHT_COLOR = '#FFD43B';
const HIGHLIGHT_FONT_WEIGHT = 950 as const;

const renderHighlighted = (text: string, highlights: string[]) => {
  if (!highlights.length) return text;
  const escaped = highlights.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).filter(Boolean);
  if (!escaped.length) return text;
  const re = new RegExp(`(${escaped.join('|')})`, 'g');
  const parts = text.split(re);
  return parts.map((p, i) => {
    if (highlights.includes(p)) {
      return (
        <span
          key={i}
          style={{
            color: HIGHLIGHT_COLOR,
            fontWeight: HIGHLIGHT_FONT_WEIGHT,
            // 1.12x size bump on the highlighted token — the keyword should
            // visually punch out of the line, not just change color. Cap is
            // intentionally subtle so it doesn't break line height.
            fontSize: '1.12em'
          }}
        >
          {p}
        </span>
      );
    }
    return <span key={i}>{p}</span>;
  });
};
