import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

const TRANSITION_FRAMES_DEFAULT = 8;

/**
 * Fade-in / fade-out wrapper with subtle breathing motion.
 *
 * IMPORTANT: this component is placed inside a <Sequence from={N}>, so
 * useCurrentFrame() returns SEQUENCE-LOCAL frames. The caller MUST pass
 * startFrame/endFrame in the same Sequence-local coordinate system.
 */
export const ShotTransition: React.FC<{
  startFrame: number;
  endFrame: number;
  children: React.ReactNode;
  inFrames?: number;
  outFrames?: number;
  /**
   * Optional shot index. When provided we alternate Ken-Burns direction so
   * adjacent shots don't all push the same way (1 zoom-in, 2 zoom-out, ...).
   */
  shotIndex?: number;
}> = ({
  startFrame,
  endFrame,
  children,
  inFrames = TRANSITION_FRAMES_DEFAULT,
  outFrames = TRANSITION_FRAMES_DEFAULT,
  shotIndex
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const localFrame = frame - startFrame;
  const totalDuration = Math.max(1, endFrame - startFrame);
  const fadeOutStart = Math.max(inFrames, totalDuration - outFrames);

  const opacityIn = interpolate(localFrame, [0, inFrames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic)
  });
  const opacityOut = interpolate(localFrame, [fadeOutStart, totalDuration], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.cubic)
  });
  const opacity = Math.min(opacityIn, opacityOut);

  // Ken-Burns: every shot is in motion the entire time it's on screen.
  // Previously we used a 4.5% zoom and ±6px drift, which was visually
  // indistinguishable from a static frame — adjacent shots that reused
  // the same screenshot (e.g. the repo README across shots 3 and 5)
  // looked identical. Bumped to 8% zoom + ±12px drift, and expanded from
  // a 2-variant to a 4-variant direction rotation so even two neighbouring
  // shots with the same visual_type get visibly different motion.
  const variant = ((shotIndex ?? 0) % 4 + 4) % 4;
  // Each variant: [scaleStart, scaleEnd, xStart, xEnd]
  const variants: Array<[number, number, number, number]> = [
    [1.0, 1.08, -12, 12],   // zoom-in, drift right
    [1.08, 1.0, 12, -12],   // zoom-out, drift left
    [1.0, 1.08, 12, -12],   // zoom-in, drift left (mirror of 0)
    [1.08, 1.0, -12, 12]    // zoom-out, drift right (mirror of 1)
  ];
  const [scaleStart, scaleEnd, xStart, xEnd] = variants[variant];
  const kenBurnsScale = interpolate(
    localFrame,
    [0, totalDuration],
    [scaleStart, scaleEnd],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.inOut(Easing.cubic)
    }
  );
  const kenBurnsX = interpolate(
    localFrame,
    [0, totalDuration],
    [xStart, xEnd],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.inOut(Easing.cubic)
    }
  );

  const translateY = interpolate(localFrame, [0, inFrames], [18, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic)
  });

  return (
    <AbsoluteFill
      style={{
        opacity,
        transform: `translateX(${kenBurnsX}px) translateY(${translateY}px) scale(${kenBurnsScale})`,
        transformOrigin: 'center center'
      }}
    >
      {children}
    </AbsoluteFill>
  );
};
