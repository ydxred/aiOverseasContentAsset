import React from 'react';
import {useCurrentFrame, useVideoConfig, spring, interpolate, Easing} from 'remotion';

/**
 * A simulated screen-recording cursor.
 *
 * The cursor enters from off-screen, springs to a target coordinate (specified
 * in % of its parent), then triggers a "click ripple" — the same kind of
 * affordance you see in screen-recording tools like Cleanshot or Loom.
 *
 * All inputs are local to the parent's coordinate system (the parent must be
 * ``position: relative``/``absolute``).  `targetXPct` / `targetYPct` are 0–100.
 *
 * Why we built this instead of using a real recorded video:
 *   - browser-use Agent screen recordings have erratic mouse paths.
 *   - We want deterministic, beat-matched motion that lands on the highlight.
 *   - It's ~1/20th the file size of a real video.
 */
export const RecordingCursor: React.FC<{
  targetXPct: number;
  targetYPct: number;
  fromXPct?: number;
  fromYPct?: number;
  /** Frame (relative to this composition's local time) when entry starts. */
  entryStartFrame?: number;
  entryDurationFrames?: number;
  /** Frame when the click ripple fires. If omitted, no click is shown. */
  clickAtFrame?: number;
  rippleDurationFrames?: number;
  /** Linger after the click so the cursor doesn't immediately fly away. */
  holdAfterClickFrames?: number;
  /** Optional second target — cursor moves there after the click. */
  secondTargetXPct?: number;
  secondTargetYPct?: number;
  size?: number;
  variant?: 'mac_dark' | 'mac_light';
}> = ({
  targetXPct,
  targetYPct,
  fromXPct = -8,
  fromYPct = 105,
  entryStartFrame = 6,
  entryDurationFrames = 26,
  clickAtFrame,
  rippleDurationFrames = 18,
  holdAfterClickFrames = 18,
  secondTargetXPct,
  secondTargetYPct,
  size = 38,
  variant = 'mac_light'
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const entryProgress = spring({
    frame: frame - entryStartFrame,
    fps,
    durationInFrames: entryDurationFrames,
    config: {damping: 26, stiffness: 110, mass: 1}
  });

  let xPct = interpolate(entryProgress, [0, 1], [fromXPct, targetXPct]);
  let yPct = interpolate(entryProgress, [0, 1], [fromYPct, targetYPct]);

  // Optional second leg — after the click, the cursor drifts to a follow-up
  // point. Useful for reading a CTA, highlighting the next button, etc.
  if (
    secondTargetXPct !== undefined &&
    secondTargetYPct !== undefined &&
    clickAtFrame !== undefined
  ) {
    const driftStart = clickAtFrame + holdAfterClickFrames;
    const driftDuration = 22;
    const driftProgress = spring({
      frame: frame - driftStart,
      fps,
      durationInFrames: driftDuration,
      config: {damping: 22, stiffness: 90, mass: 1}
    });
    xPct = interpolate(driftProgress, [0, 1], [xPct, secondTargetXPct]);
    yPct = interpolate(driftProgress, [0, 1], [yPct, secondTargetYPct]);
  }

  // Click ripple animation — only render if a click frame was supplied.
  let rippleScale = 0;
  let rippleOpacity = 0;
  let cursorPress = 1;
  if (clickAtFrame !== undefined) {
    const localF = frame - clickAtFrame;
    if (localF >= 0 && localF <= rippleDurationFrames) {
      rippleScale = interpolate(localF, [0, rippleDurationFrames], [0.2, 1.4], {
        easing: Easing.out(Easing.cubic),
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp'
      });
      rippleOpacity = interpolate(
        localF,
        [0, rippleDurationFrames * 0.25, rippleDurationFrames],
        [0, 0.85, 0],
        {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
      );
    }
    // Tactile press: cursor briefly shrinks 92% on the click frame.
    if (localF >= 0 && localF <= 5) {
      cursorPress = interpolate(localF, [0, 2, 5], [1, 0.92, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp'
      });
    }
  }

  const fillColor = variant === 'mac_dark' ? '#0B0E13' : '#FFFFFF';
  const strokeColor = variant === 'mac_dark' ? '#FFFFFF' : '#0B0E13';

  return (
    <div
      style={{
        position: 'absolute',
        left: `${xPct}%`,
        top: `${yPct}%`,
        width: size,
        height: size,
        pointerEvents: 'none',
        zIndex: 50,
        transform: `translate(-2px, -2px) scale(${cursorPress})`,
        transformOrigin: '4px 4px',
        filter: 'drop-shadow(0 4px 8px rgba(0,0,0,0.55))'
      }}
    >
      {/* Click ripple — sits behind the cursor tip */}
      {clickAtFrame !== undefined ? (
        <div
          style={{
            position: 'absolute',
            left: -size * 0.6,
            top: -size * 0.6,
            width: size * 1.6,
            height: size * 1.6,
            borderRadius: '50%',
            border: '3px solid #5EFF8F',
            boxShadow: '0 0 22px rgba(94,255,143,0.55)',
            transform: `scale(${rippleScale})`,
            opacity: rippleOpacity,
            transformOrigin: 'center center'
          }}
        />
      ) : null}

      {/* Classic macOS-style cursor */}
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        style={{position: 'absolute', left: 0, top: 0}}
      >
        <path
          d="M5.5 3 L5.5 19 L9.5 15.2 L12 21 L14.7 19.7 L12.2 14 L17.6 14 Z"
          fill={fillColor}
          stroke={strokeColor}
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
};
