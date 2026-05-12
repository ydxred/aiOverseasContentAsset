import React from 'react';
import {AbsoluteFill} from 'remotion';
import {theme} from '../../styles/theme';
import {RecordingCursor} from '../RecordingCursor';
import {SectionLabel} from '../SectionLabel';
import {resolveChrome} from './chromeForEvidence';
import type {ShotTemplateProps} from './types';

/**
 * Portrait "evidence zoom" overlay.
 *
 * Zoom-into-the-subject is now applied at the composition level via
 * ``FullscreenEvidence``'s ``subjectScale``. Here we only paint the focus
 * reticle + recording cursor for non-photographic evidence, plus the
 * section label.
 */
export const RepoEvidenceZoomShot: React.FC<ShotTemplateProps> = ({shot, evidence, repoName, shotIndex = 0}) => {
  const role = evidence?.role || '';
  const chrome = resolveChrome(role, repoName, {
    kind: 'terminal',
    title: '',
  });
  const labelName = shot?.english_label || (chrome.isPhotographic ? 'video frame' : 'evidence');
  const labelStyle = shot?.label_style || 'comment';

  return (
    <AbsoluteFill style={{fontFamily: theme.fonts.ui}}>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />

      {chrome.isPhotographic ? null : (
        <>
          {/* Focus reticle parked at canvas center to mimic an "ok, look here"
              beat. The zoom-in transform applied at the composition layer
              already pushes the visual punch; this rectangle is the cue. */}
          <div
            style={{
              position: 'absolute',
              left: '50%',
              top: '46%',
              width: 360,
              height: 360,
              transform: 'translate(-50%, -50%)',
              border: `2px solid ${theme.colors.secondary}`,
              borderRadius: 6,
              boxShadow: `0 0 0 2px rgba(11,13,18,0.55), 0 0 50px ${theme.colors.secondarySoft}`,
              pointerEvents: 'none',
            }}
          >
            <CornerTick pos="tl" />
            <CornerTick pos="tr" />
            <CornerTick pos="bl" />
            <CornerTick pos="br" />
          </div>

          <RecordingCursor
            targetXPct={50}
            targetYPct={46}
            entryStartFrame={6}
            entryDurationFrames={28}
            clickAtFrame={42}
          />
        </>
      )}
    </AbsoluteFill>
  );
};

const CornerTick: React.FC<{pos: 'tl' | 'tr' | 'bl' | 'br'}> = ({pos}) => {
  const base: React.CSSProperties = {
    position: 'absolute',
    width: 26,
    height: 26,
    borderColor: theme.colors.secondary,
    borderStyle: 'solid',
  };
  if (pos === 'tl') return <div style={{...base, left: -3, top: -3, borderWidth: '4px 0 0 4px'}} />;
  if (pos === 'tr') return <div style={{...base, right: -3, top: -3, borderWidth: '4px 4px 0 0'}} />;
  if (pos === 'bl') return <div style={{...base, left: -3, bottom: -3, borderWidth: '0 0 4px 4px'}} />;
  return <div style={{...base, right: -3, bottom: -3, borderWidth: '0 4px 4px 0'}} />;
};
