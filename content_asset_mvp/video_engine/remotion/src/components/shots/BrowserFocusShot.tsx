import React from 'react';
import {AbsoluteFill} from 'remotion';
import {theme} from '../../styles/theme';
import {RecordingCursor} from '../RecordingCursor';
import {SectionLabel} from '../SectionLabel';
import {resolveChrome} from './chromeForEvidence';
import type {ShotTemplateProps} from './types';

/**
 * Portrait "browser snapshot" overlay.
 *
 * The screenshot itself is rendered globally by ``FullscreenEvidence``; this
 * shot only paints the section label, an [N/M] counter when there are
 * multiple snapshots in the shot list, and an optional recording cursor.
 */
export const BrowserFocusShot: React.FC<ShotTemplateProps> = ({shot, evidence, index, total, repoName, shotIndex = 0}) => {
  const role = evidence?.role || '';
  const chrome = resolveChrome(role, repoName, {
    kind: 'browser',
    title: '',
  });
  const labelName =
    shot?.english_label ||
    (chrome.isPhotographic ? 'video frame' : `browse ${role || 'evidence'}`.trim());
  const labelStyle = shot?.label_style || 'shell';

  return (
    <AbsoluteFill style={{fontFamily: theme.fonts.ui}}>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />

      {total > 1 ? (
        <div
          style={{
            position: 'absolute',
            right: 56,
            top: 200,
            padding: '10px 18px',
            borderRadius: 8,
            background: 'rgba(7,10,15,0.78)',
            border: `1px solid ${theme.colors.panelBorder}`,
            color: theme.colors.primary,
            fontFamily: theme.fonts.mono,
            fontSize: 26,
            fontWeight: 700,
            backdropFilter: 'blur(6px)',
          }}
        >
          [{index + 1}/{total}]
        </div>
      ) : null}

      {chrome.isPhotographic ? null : (
        <RecordingCursor
          targetXPct={50}
          targetYPct={46}
          entryStartFrame={4}
          entryDurationFrames={26}
          clickAtFrame={36}
          variant="mac_dark"
        />
      )}
    </AbsoluteFill>
  );
};
