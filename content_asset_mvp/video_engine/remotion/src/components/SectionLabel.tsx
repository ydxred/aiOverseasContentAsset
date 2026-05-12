import React from 'react';
import {theme} from '../styles/theme';

type LabelStyle = 'cell' | 'comment' | 'section' | 'shell' | 'traceback';

const formatLabel = (style: LabelStyle, index: number, name?: string) => {
  const idx = String(index).padStart(2, '0');
  switch (style) {
    case 'comment':
      return `# %% ${name || ''}`.trim();
    case 'section':
      return `§ ${index}. ${name || ''}`.trim();
    case 'shell':
      return `$ ${name || 'analyze'}`;
    case 'traceback':
      return `! ${name || 'Traceback'}`;
    case 'cell':
    default:
      return `In [${idx}]: ${name || ''}`.trim();
  }
};

const labelColor = (style: LabelStyle) => {
  if (style === 'traceback') return theme.colors.warning;
  if (style === 'comment') return theme.colors.secondary;
  if (style === 'shell') return theme.colors.primary;
  if (style === 'section') return theme.colors.secondary;
  return theme.colors.primary;
};

// SectionLabel was originally meant to give every shot a Jupyter-style
// header like ``In [01]: Spotlight`` / ``$ Video Frame`` / ``// REPO
// OVERVIEW`` for a "knowledge / IDE" aesthetic. In practice that's a top-
// left badge stamped on top of the subject's face for ~3 minutes, and
// stacks with the brand ribbon and caption-hint, making each frame look
// like an unfinished debug UI instead of a short video.
//
// We keep the component (and ``formatLabel`` / ``labelColor`` are still
// referenced by other label-style choices) so callers don't have to be
// rewritten, but the on-screen render is muted by default. Set
// ``REMOTION_SHOW_SECTION_LABEL=1`` (read at bundle time) to bring the
// debug overlay back when iterating on layout.
const SHOW_SECTION_LABEL =
  // ``process.env`` is replaced at bundle time by Remotion's webpack.
  typeof process !== 'undefined' &&
  process.env &&
  process.env.REMOTION_SHOW_SECTION_LABEL === '1';

void formatLabel;
void labelColor;

export const SectionLabel: React.FC<{
  index: number;
  name?: string;
  style?: LabelStyle;
}> = ({index, name, style = 'cell'}) => {
  if (!SHOW_SECTION_LABEL) {
    return null;
  }
  const text = formatLabel(style, index, name);
  return (
    <div
      style={{
        position: 'absolute',
        left: 56,
        top: 56,
        padding: '10px 18px',
        fontFamily: theme.fonts.mono,
        fontSize: 26,
        fontWeight: 600,
        color: labelColor(style),
        letterSpacing: 0.5,
        background: 'rgba(7,10,15,0.62)',
        border: `1px solid ${theme.colors.panelBorder}`,
        borderRadius: 8,
        boxShadow: '0 4px 18px rgba(0,0,0,0.42)',
        fontFeatureSettings: '"liga" on, "calt" on',
        whiteSpace: 'nowrap',
        maxWidth: 'calc(100% - 112px)',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }}
    >
      {text}
    </div>
  );
};
