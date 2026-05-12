import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {Cover} from '../components/Cover';
import {EdgeGradient} from '../components/EdgeGradient';
import {FullscreenEvidence} from '../components/FullscreenEvidence';
import {ShotDispatcher} from '../components/shots/ShotDispatcher';
import {resolveChrome} from '../components/shots/chromeForEvidence';
import type {DirectorShot, EvidenceItem} from '../components/shots/types';
import {SubtitleCue, SubtitleLayer} from '../components/SubtitleLayer';
import {TechBackdrop} from '../components/TechBackdrop';
import {ShotTransition} from '../components/ShotTransition';
import {theme} from '../styles/theme';

export type DouyinExplainerProps = {
  title?: string;
  durationSeconds?: number;
  audioPath?: string;
  subtitles?: SubtitleCue[];
  evidenceImage?: string;
  evidenceItems?: EvidenceItem[];
  directorPlan?: DirectorPlan;
  repoName?: string;
};

type DirectorPlan = {
  shots?: DirectorShot[];
  scenes?: Array<{scene_id?: string; label?: string; start?: number; end?: number; screen_text?: string}>;
};

const COVER_FRAMES = 90;

export const DouyinExplainer: React.FC<DouyinExplainerProps> = ({
  title = 'AI product signal worth watching',
  audioPath,
  subtitles = [],
  evidenceImage,
  evidenceItems = [],
  directorPlan = {},
  repoName
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const directorTime = Math.max(0, (frame - COVER_FRAMES) / fps);

  const fallbackItems: EvidenceItem[] = evidenceImage
    ? [{src: evidenceImage, label: 'Evidence and product context'}]
    : [];
  const visualItems = evidenceItems.length > 0 ? evidenceItems : fallbackItems;
  const shots = Array.isArray(directorPlan.shots) ? directorPlan.shots : [];

  // Prefer a YouTube thumbnail as the cover hero because it's usually the
  // most hook-optimised asset we have. Fall back to any evidence if no
  // thumbnail is tagged; leave undefined when nothing is available so the
  // Cover falls back to its terminal-only layout.
  const heroItem =
    visualItems.find((item) => item.role === 'youtube_thumbnail') ||
    visualItems.find((item) => item.role?.startsWith('youtube_')) ||
    undefined;
  const coverImage = heroItem?.src;

  const activeShotIndex = shots.findIndex(
    (shot) => directorTime >= Number(shot.start || 0) && directorTime <= Number(shot.end || 0)
  );
  const activeShot = activeShotIndex >= 0 ? shots[activeShotIndex] : undefined;

  // ShotTransition lives inside <Sequence from={COVER_FRAMES}>, so its
  // useCurrentFrame() returns Sequence-local frames. Pass start/end in
  // Sequence-local coordinates (do NOT add COVER_FRAMES).
  const activeStartFrame =
    activeShot != null ? Math.round(Number(activeShot.start || 0) * fps) : 0;
  const activeEndFrame =
    activeShot != null
      ? Math.round(Number(activeShot.end || 0) * fps)
      : Math.max(0, durationInFrames - COVER_FRAMES);

  const evidenceIndex =
    visualItems.length > 0
      ? (activeShotIndex >= 0
          ? activeShotIndex
          : Math.floor(Math.max(0, frame - COVER_FRAMES) / (fps * 5.5))) % visualItems.length
      : 0;
  const activeEvidence = visualItems[evidenceIndex];

  // Per-shot evidence framing. ``repo_evidence_zoom`` punches in 1.35x on the
  // top-third of the subject so the foreground reads as a "zoom in" beat
  // even though there's no chrome around it anymore. Photographic frames
  // (YouTube thumbnails, talking heads) anchor higher up the canvas
  // (35%) since faces / titles tend to live there.
  const evidenceChrome = activeEvidence
    ? resolveChrome(activeEvidence.role, repoName, {kind: 'browser', title: ''})
    : undefined;
  const isZoomShot = activeShot?.visual_type === 'repo_evidence_zoom';
  const isPhotographic = evidenceChrome?.isPhotographic === true;
  // 16:9 source on a 9:16 canvas: cover already crops the sides ~64%, but
  // many sources still have top/bottom dead space (screen-share chrome,
  // talking-head letterbox). We over-zoom mildly to absorb that dead band
  // without trashing the subject framing. ``FullscreenEvidence`` paints a
  // blurred copy of the same image as a backstop so any remaining
  // letterbox reads as ambient atmosphere instead of black bars.
  //   - photographic (thumbnails / faces): keep face intact, only +12%
  //   - keyframes (screen-shares with chrome): aggressive +35% to crop chrome
  //   - zoom shots: deliberate punch-in
  const role = activeEvidence?.role || '';
  const isScreenShareChrome =
    role === 'youtube_keyframe' || role === 'youtube_clip';
  const subjectScale = isZoomShot
    ? 1.65
    : isScreenShareChrome
      ? 1.55
      : isPhotographic
        ? 1.32
        : 1.18;
  const subjectOrigin = isPhotographic ? '50% 38%' : '50% 50%';
  const objectPosition = isPhotographic ? 'center 30%' : 'center 50%';

  return (
    <AbsoluteFill style={{backgroundColor: theme.colors.background}}>
      <TechBackdrop />
      <Sequence from={0} durationInFrames={COVER_FRAMES}>
        <Cover title={title} source={repoName} coverImage={coverImage} />
      </Sequence>
      <Sequence from={COVER_FRAMES}>
        {/* Fullscreen evidence + edge gradient sits beneath every shot.
            Shot templates render only foreground text/CTA/cursor on top. */}
        <FullscreenEvidence
          src={activeEvidence?.src}
          objectPosition={objectPosition}
          subjectScale={subjectScale}
          subjectOrigin={subjectOrigin}
          dim={0.30}
        />
        <EdgeGradient topHeightPct={0} bottomHeightPct={0} />
        <BrandRibbon title={title} />
        {activeShot ? (
          <ShotTransition
            startFrame={activeStartFrame}
            endFrame={activeEndFrame}
            shotIndex={activeShotIndex}
          >
            <ShotDispatcher
              shot={activeShot}
              evidence={activeEvidence}
              title={title}
              index={evidenceIndex}
              total={visualItems.length}
              shotIndex={activeShotIndex}
              repoName={repoName}
            />
          </ShotTransition>
        ) : null}
      </Sequence>
      <SubtitleLayer subtitles={subtitles} hideBeforeFrame={COVER_FRAMES} />
      {audioPath ? <Audio src={toAssetSource(audioPath)} /> : null}
    </AbsoluteFill>
  );
};

// Minimal brand mark — just a glowing dot + handle. The title is already
// established in the cover; repeating it on every shot is noise.
const BrandRibbon: React.FC<{title: string}> = ({title: _title}) => (
  <div
    style={{
      position: 'absolute',
      left: 56,
      top: 132,
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      fontFamily: theme.fonts.mono,
      color: theme.colors.textSoft,
      fontSize: 18,
      letterSpacing: 0.6,
      opacity: 0.55
    }}
  >
    <span
      style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: theme.colors.primary,
        boxShadow: `0 0 10px ${theme.colors.primary}`
      }}
    />
    <span style={{color: theme.colors.primary, fontWeight: 700}}>ai-radar</span>
  </div>
);

const toAssetSource = (src: string) => {
  if (src.startsWith('http') || src.startsWith('data:') || src.startsWith('file:')) {
    return src;
  }
  return staticFile(src);
};
