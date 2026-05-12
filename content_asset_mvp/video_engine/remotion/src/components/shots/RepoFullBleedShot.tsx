import React from 'react';
import {AbsoluteFill} from 'remotion';
import {theme} from '../../styles/theme';
import {RecordingCursor} from '../RecordingCursor';
import {SectionLabel} from '../SectionLabel';
import {resolveChrome} from './chromeForEvidence';
import type {ShotTemplateProps} from './types';

/**
 * Portrait "establishing shot" overlay.
 *
 * The evidence image is now rendered globally by ``<FullscreenEvidence />``
 * in DouyinExplainer, so this template only paints the foreground decorations
 * — section label, optional recording-cursor for non-photographic frames —
 * and lets the underlying image breathe.
 */
export const RepoFullBleedShot: React.FC<ShotTemplateProps> = ({shot, evidence, repoName, shotIndex = 0}) => {
  const role = evidence?.role || '';
  const chrome = resolveChrome(role, repoName, {
    kind: 'browser',
    title: '',
  });
  const labelName =
    shot?.english_label || (chrome.isPhotographic ? 'play clip' : 'open repo');
  const labelStyle = shot?.label_style || 'shell';

  return (
    <AbsoluteFill style={{fontFamily: theme.fonts.ui}}>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />

      {/* The recording cursor only "points" at things that look like UI.
          For talking-head / video-frame evidence the target would land on a
          face, so we suppress it. Its anchor coords are computed against the
          full canvas, not a clipped chrome window. */}
      {chrome.isPhotographic ? null : (
        <RecordingCursor
          targetXPct={42}
          targetYPct={48}
          entryStartFrame={6}
          entryDurationFrames={28}
          clickAtFrame={48}
          secondTargetXPct={56}
          secondTargetYPct={62}
          holdAfterClickFrames={14}
          variant="mac_dark"
        />
      )}
    </AbsoluteFill>
  );
};
