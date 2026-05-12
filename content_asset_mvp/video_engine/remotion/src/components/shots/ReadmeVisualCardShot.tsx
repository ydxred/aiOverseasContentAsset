import React from 'react';
import {AbsoluteFill} from 'remotion';
import {theme} from '../../styles/theme';
import {RecordingCursor} from '../RecordingCursor';
import {SectionLabel} from '../SectionLabel';
import {resolveChrome} from './chromeForEvidence';
import type {ShotTemplateProps} from './types';

/**
 * Portrait "readme/illustration" overlay.
 *
 * The artwork itself is rendered globally by ``FullscreenEvidence``; this
 * template only adds a brand-coloured caption hint near the top so viewers
 * read the frame as "diagram / illustration" rather than just another
 * screenshot.
 */
export const ReadmeVisualCardShot: React.FC<ShotTemplateProps> = ({shot, evidence, repoName, shotIndex = 0}) => {
  const role = evidence?.role || '';
  const chrome = resolveChrome(role, repoName, {
    kind: 'jupyter',
    title: '',
  });
  const labelName = shot?.english_label || (chrome.isPhotographic ? 'video frame' : 'README');
  const labelStyle = shot?.label_style || 'comment';

  return (
    <AbsoluteFill style={{fontFamily: theme.fonts.ui}}>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />

      {chrome.isPhotographic ? null : (
        <RecordingCursor
          targetXPct={45}
          targetYPct={42}
          entryStartFrame={8}
          entryDurationFrames={26}
          secondTargetXPct={55}
          secondTargetYPct={58}
          clickAtFrame={42}
          holdAfterClickFrames={12}
          variant="mac_dark"
        />
      )}
    </AbsoluteFill>
  );
};
