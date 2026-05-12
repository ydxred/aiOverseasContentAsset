import React from 'react';
import {AbsoluteFill, staticFile} from 'remotion';
import {theme} from '../styles/theme';

/**
 * Fullscreen evidence backdrop — implemented with ``background-image`` +
 * ``background-size: cover`` instead of ``<Img>`` because Remotion's
 * ``<Img>`` does not honour ``objectFit: cover`` reliably when the source
 * aspect ratio differs from the canvas (e.g. 16:9 thumbnail on 9:16
 * portrait), which leaves the picture letter-boxed instead of bleed-filling.
 *
 * Layers:
 *  - background-image cover layer: paints the full canvas, side-cropped via
 *    ``backgroundPosition`` (defaults to 35% from the top so the face/title
 *    on a YouTube thumbnail stays visible after the inevitable side-crop).
 *  - flat dim overlay (≈30%): keeps subtitles + headline type readable on
 *    bright thumbnails. Picture still feels like a picture.
 *
 * If ``src`` is empty, only a soft radial gradient renders so motion-graphics
 * scenes still get visual texture instead of a flat black canvas.
 */
export const FullscreenEvidence: React.FC<{
  src?: string;
  /** CSS background-position for the cover layer. Default ``center 35%``. */
  objectPosition?: string;
  /** Dim factor for the global overlay (0..1). Default 0.30. */
  dim?: number;
  /** Optional foreground subject zoom (1..2). 1 = no zoom. */
  subjectScale?: number;
  /** Transform-origin for ``subjectScale``. Default ``50% 35%``. */
  subjectOrigin?: string;
}> = ({
  src,
  objectPosition = 'center 35%',
  dim = 0.30,
  subjectScale = 1.0,
  subjectOrigin = '50% 35%',
}) => {
  if (!src) {
    return (
      <AbsoluteFill
        style={{
          background: `radial-gradient(120% 80% at 50% 35%, ${theme.colors.panel} 0%, ${theme.colors.background} 60%, ${theme.colors.backgroundDeep} 100%)`,
        }}
      />
    );
  }
  const resolved = toAssetSource(src);
  const dimAlpha = Math.max(0, Math.min(1, dim));
  return (
    <AbsoluteFill style={{backgroundColor: theme.colors.background}}>
      {/* Layer 1 — soft blurred backdrop. Painted from the same source so
          any letterbox/chrome bands inherent to the asset don't read as
          a hard black bar; we widen + brighten the cover scale so the
          centre of the canvas always reads as warm imagery, not black. */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `url(${JSON.stringify(resolved)})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center center',
          backgroundRepeat: 'no-repeat',
          filter: 'blur(64px) brightness(0.85) saturate(1.25)',
          transform: 'scale(1.45)',
        }}
      />
      {/* Layer 2 — the foreground subject. ``subjectScale`` defaults high
          (1.55 for 16:9 source on 9:16 canvas) which crops the inevitable
          top/bottom dead-space (record-screen chrome, talking-head
          letterbox) so the subject reads edge-to-edge. The cover origin
          (``objectPosition``) anchors the crop on the face/headline. */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `url(${JSON.stringify(resolved)})`,
          backgroundSize: 'cover',
          backgroundPosition: objectPosition,
          backgroundRepeat: 'no-repeat',
          transform: `scale(${subjectScale})`,
          transformOrigin: subjectOrigin,
          filter: 'contrast(1.06) saturate(1.08)',
        }}
      />
      {dimAlpha > 0 ? (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: `rgba(0,0,0,${dimAlpha})`,
            pointerEvents: 'none',
          }}
        />
      ) : null}
    </AbsoluteFill>
  );
};

const toAssetSource = (src: string) => {
  if (src.startsWith('http') || src.startsWith('data:') || src.startsWith('file:')) {
    return src;
  }
  return staticFile(src);
};
