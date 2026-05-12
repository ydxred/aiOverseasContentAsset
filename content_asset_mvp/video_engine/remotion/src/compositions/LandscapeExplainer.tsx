import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {BrandWatermark} from '../components/BrandWatermark';
import {CoverLandscape} from '../components/CoverLandscape';
import {EdgeGradient} from '../components/EdgeGradient';
import {LandscapeShotDispatcher} from '../components/shots/LandscapeShots';
import type {DirectorShot, EvidenceItem} from '../components/shots/types';
import {SubtitleCue, SubtitleLayer} from '../components/SubtitleLayer';
import {TechBackdrop} from '../components/TechBackdrop';
import {ShotTransition} from '../components/ShotTransition';
import {theme} from '../styles/theme';

export type LandscapeExplainerProps = {
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

export const LandscapeExplainer: React.FC<LandscapeExplainerProps> = ({
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

  // Mirror the DouyinExplainer heuristic: prefer a YouTube thumbnail as
  // the hero image when available. The landscape 16:9 cover reserves the
  // left 58% for this image, which matches the native aspect ratio of a
  // YouTube thumbnail and avoids the cropping we see on portrait.
  const heroItem =
    visualItems.find((item) => item.role === 'youtube_thumbnail') ||
    visualItems.find((item) => item.role?.startsWith('youtube_')) ||
    undefined;
  const coverImage = heroItem?.src;

  const activeShotIndex = shots.findIndex(
    (shot) => directorTime >= Number(shot.start || 0) && directorTime <= Number(shot.end || 0)
  );
  const activeShot = activeShotIndex >= 0 ? shots[activeShotIndex] : undefined;

  // Map the active shot's scene_id to a TechBackdrop tone. We accept
  // the four canonical scene_ids that video_director emits, plus
  // "neutral" as a fallback. The resulting per-scene colour shift is
  // the cheapest way to break the "60 shots, same layout" feeling
  // while we wait for tier-2 info-graphic templates to land.
  const sceneId = String(activeShot?.scene_id || '').toLowerCase();
  const KNOWN_SCENES = new Set(['hook', 'context', 'evidence', 'takeaway']);
  const backdropTone = (KNOWN_SCENES.has(sceneId) ? sceneId : 'neutral') as
    | 'hook'
    | 'context'
    | 'evidence'
    | 'takeaway'
    | 'neutral';

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

  // FullscreenEvidence (creator portrait / repo screenshot used as a
  // ~70% screen-fill backdrop) is intentionally NOT mounted here.
  //
  // Why we removed it: A/B against IMG_5834 (计算机大白) / IMG_5835
  // (MyElc) / IMG_5836 confirms that the dominant visual style of
  // mainstream Chinese AI/科技 short-video creators is "100% self-
  // designed graphics" — they use ZERO frames of the source video as
  // backdrop. Their videos read as authored explainers, not as
  // commentary-on-someone-else's-video.
  //
  // Our previous output had Peter Yang's face filling the frame for
  // ~70% of the runtime, which positions the channel as a "海外搬运/
  // 二创" account regardless of how good the script is. Cutting the
  // photographic backdrop is the single biggest visual identity move
  // available.
  //
  // The 3 historically-photographic templates (repo_full_bleed,
  // repo_evidence_zoom, readme_visual_card) are now rerouted in the
  // dispatcher to typography-only equivalents so the captions still
  // render with intentional layout instead of "caption on transparent".
  //
  // To re-enable photographic backdrops for a specific source type
  // (e.g. genuine repo screenshots for non-creator-portrait sources),
  // re-introduce a guarded FullscreenEvidence here keyed off the
  // evidence ``role`` rather than the global default.
  void activeEvidence;  // explicitly acknowledge the unused binding for the linter

  return (
    <AbsoluteFill style={{backgroundColor: theme.colors.background}}>
      <TechBackdrop tone={backdropTone} />
      <Sequence from={0} durationInFrames={COVER_FRAMES}>
        <CoverLandscape title={title} source={repoName} coverImage={coverImage} />
      </Sequence>
      <Sequence from={COVER_FRAMES}>
        <EdgeGradient topHeightPct={8} bottomHeightPct={20} />
        {/* Brand watermark — bottom-right account stamp shown for the
            entire body of the video. Cover handles its own branding. */}
        <BrandWatermark visible />

        {/* BrandRibbonLandscape removed from per-shot render: the cover
            already shows the "● ai-radar · 海外 AI 信号" mark for the first
            ~1.5s, repeating it on every one of 60+ shots is just visual
            noise that competes with the subject's face / evidence asset.
            Mainstream short-video creators (Peter Yang / MyElc / Matt
            Wolfe) only brand the cover and the outro, never every frame. */}
        {activeShot ? (
          <ShotTransition
            startFrame={activeStartFrame}
            endFrame={activeEndFrame}
            shotIndex={activeShotIndex}
          >
            <LandscapeShotDispatcher
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

// Minimal brand mark for landscape — same philosophy as portrait, just
// the glowing dot + handle.
//
// Currently NOT mounted in the per-shot Sequence (see comment in the
// composition above): every-frame branding was removed in favour of
// brand mark on the cover only. The component is kept here so it can
// be re-mounted from the outro / sponsor slot later without rewriting
// the layout from scratch.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const BrandRibbonLandscape: React.FC<{title: string}> = ({title: _title}) => (
  <div
    style={{
      position: 'absolute',
      left: theme.landscape.shot.paddingX,
      top: theme.landscape.ribbonTop,
      height: theme.landscape.ribbonHeight,
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
