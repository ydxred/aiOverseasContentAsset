import React from 'react';
import {Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../../styles/theme';
import {SectionLabel} from '../SectionLabel';
import {resolveChrome} from './chromeForEvidence';
import type {ShotTemplateProps} from './types';

// Section pills (e.g. "钩子·HOOK") were originally meant to anchor the
// viewer to the narrative beat — but in practice they read like internal
// debug overlays on a finished narrative video, and reference creators
// (@计算机大白 / MyElc) never use them. Beat changes should be felt via
// rhythm + camera change, not labelled with a pill. Gated off by default;
// set ``REMOTION_SHOW_SECTION_PILL=1`` to bring them back during layout
// iteration.
const SHOW_SECTION_PILL =
  typeof process !== 'undefined' &&
  process.env &&
  process.env.REMOTION_SHOW_SECTION_PILL === '1';

// Match numbers with optional currency / unit. Used by VariableLandscape to
// highlight digits in warning colour — e.g. "¥23,967 / 年" → just the
// "¥23,967 / 年" block glows amber, the rest stays CRT-green.
const LANDSCAPE_NUMBER_PATTERN =
  /([¥$€￥]?\d[\d,.]*[kKmMwW万亿百千％%]?[分秒年月日年岁次个项条位美元]?(?:\s*[\/／]\s*\d[\d,.]*[年月日次分秒])?|\d+%)/;

type LandscapeChunk = {text: string; isNumber: boolean};

const splitByNumbersLandscape = (raw: string): LandscapeChunk[] => {
  const trimmed = raw.trim();
  if (!trimmed) return [{text: '', isNumber: false}];
  const match = trimmed.match(LANDSCAPE_NUMBER_PATTERN);
  if (!match || match.index == null) {
    return [{text: trimmed, isNumber: false}];
  }
  const chunks: LandscapeChunk[] = [];
  if (match.index > 0) chunks.push({text: trimmed.slice(0, match.index), isNumber: false});
  chunks.push({text: match[0], isNumber: true});
  const tail = trimmed.slice(match.index + match[0].length);
  if (tail) chunks.push({text: tail, isNumber: false});
  return chunks;
};

const LANDSCAPE_CTA_PROMPTS = [
  '说说你是怎么看的',
  '你会用它干什么',
  '留言告诉我',
];

// Per-shot motion vocabulary. The Python director assigns one of these
// strings to each shot (and ``_expand_specs`` rotates through the list
// per cycle), but historically typography templates ignored the field
// — every shot got the same spring-rise + 4% Ken Burns regardless. The
// viewer therefore couldn't tell shot 4 apart from shot 7 even though
// the visual_type was nominally different.
//
// motionTransform takes the motion name + frame + fps and returns the
// CSS transform / opacity values to apply to the shot's content
// container. Each motion produces a hand-tuned trajectory:
//
//   slow_push    : scale 1.00 → 1.10 over the shot, opacity fade-in
//   snap_zoom    : scale 0.88 → 1.00 in 0.4s, then settle
//   quick_push   : scale 1.04 → 1.18 over 1.5s (faster Ken Burns)
//   slow_pull    : scale 1.10 → 1.00 over the shot (zoom out)
//   static_held  : no transform — locked frame
//   pan_left     : translateX +60 → 0 over 1.2s (slide in from right)
//   pan_right    : translateX -60 → 0 over 1.2s (slide in from left)
//
// All variants share the opacity fade-in for the first 8 frames so
// shot transitions never hard-cut. Highlight position is handled by
// ``motionAnchor`` — see below.
type MotionVariant = {transform: string; opacity: number};

const motionTransform = (motion: string | undefined, frame: number, fps: number): MotionVariant => {
  const t = frame / fps;
  // Shared opacity fade-in over the first 0.27s.
  const opacity = Math.min(1, frame / 8);
  switch ((motion || 'slow_push').toLowerCase()) {
    case 'snap_zoom': {
      // Quick-zoom-in then settle. Strong attention-grabber for impact
      // beats / number reveals.
      const k = Math.min(1, t / 0.4);
      const scale = 0.88 + 0.12 * (k * (2 - k)); // ease-out quad
      return {transform: `scale(${scale.toFixed(4)})`, opacity};
    }
    case 'quick_push': {
      // Faster Ken Burns — noticeable forward push without being snappy.
      const scale = 1.04 + Math.min(1, t / 1.5) * 0.14;
      return {transform: `scale(${scale.toFixed(4)})`, opacity};
    }
    case 'slow_pull': {
      // Pull back — opens up the frame, good for "stepping back" beats.
      const k = Math.min(1, t / 4.0);
      const scale = 1.10 - 0.10 * (k * (2 - k));
      return {transform: `scale(${scale.toFixed(4)})`, opacity};
    }
    case 'static_held': {
      return {transform: 'none', opacity};
    }
    case 'pan_left':
    case 'left_focal': {
      // Slide in from right + slight scale. Used by typography templates
      // when the shot's authored ``highlight`` is left-anchored.
      const k = Math.min(1, t / 1.2);
      const tx = 60 - 60 * (k * (2 - k));
      const scale = 1.02 + Math.min(1, t / 4) * 0.05;
      return {transform: `translateX(${tx.toFixed(1)}px) scale(${scale.toFixed(3)})`, opacity};
    }
    case 'pan_right':
    case 'right_focal': {
      const k = Math.min(1, t / 1.2);
      const tx = -60 + 60 * (k * (2 - k));
      const scale = 1.02 + Math.min(1, t / 4) * 0.05;
      return {transform: `translateX(${tx.toFixed(1)}px) scale(${scale.toFixed(3)})`, opacity};
    }
    case 'top_third': {
      // Vertical slide in from above. Used when authored highlight
      // anchors to the top region.
      const k = Math.min(1, t / 1.0);
      const ty = -40 + 40 * (k * (2 - k));
      return {transform: `translateY(${ty.toFixed(1)}px) scale(1.02)`, opacity};
    }
    case 'bottom_third': {
      const k = Math.min(1, t / 1.0);
      const ty = 40 - 40 * (k * (2 - k));
      return {transform: `translateY(${ty.toFixed(1)}px) scale(1.02)`, opacity};
    }
    case 'slow_push':
    default: {
      // Default Ken Burns — gentle 10% push over the shot duration.
      const scale = 1.00 + Math.min(1, t / 4.5) * 0.10;
      return {transform: `scale(${scale.toFixed(4)})`, opacity};
    }
  }
};

const pickLandscapePrompt = (seed: string): string => {
  const hash = Array.from(seed).reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  return LANDSCAPE_CTA_PROMPTS[hash % LANDSCAPE_CTA_PROMPTS.length];
};

// Pill component shared by the landscape CTA footer. Kept local so a
// landscape-specific size tweak doesn't ripple into the portrait version.
const LandscapeCtaPill: React.FC<{
  icon: string;
  label: string;
  color: string;
  glow: string;
}> = ({icon, label, color, glow}) => (
  <div
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      padding: '18px 36px',
      borderRadius: 999,
      background: 'rgba(11,14,19,0.75)',
      border: `2px solid ${color}`,
      boxShadow: `0 0 30px ${glow}, inset 0 0 16px rgba(0,0,0,0.4)`,
      color,
      fontFamily: theme.fonts.ui,
      fontSize: 34,
      fontWeight: 700,
      letterSpacing: 0.4,
    }}
  >
    <span style={{fontSize: 32, lineHeight: 1}}>{icon}</span>
    <span>{label}</span>
  </div>
);

/**
 * 16:9 (1920x1080) shot templates for B 站 / YouTube / 横版抖音.
 *
 * Layout strategy:
 *   - Text-heavy shots (Definition / Variable / Assertion) center vertically and
 *     fill the full content area (1728x768 inside the safe area).
 *   - Visual shots (Repo / Evidence / Browser / README) use a 42 / 58 split:
 *     left column = caption + purpose, right column = chrome window with the
 *     screenshot. This gives screenshots the room they need without competing
 *     with the text.
 *
 * Section labels and color palette match the portrait variant so audiences can
 * tell both versions are the same brand.
 */

const SHOT_X = theme.landscape.shot.paddingX;
const SHOT_TOP = theme.landscape.shot.top;
const SHOT_HEIGHT = theme.landscape.shot.height;
const SHOT_WIDTH = theme.landscape.width - SHOT_X * 2;

// Heavy black stroke for landscape headlines that now sit on top of a
// fullscreen photo / thumbnail backdrop instead of a clean dark panel.
const LANDSCAPE_HEADLINE_SHADOW = [
  '-3px -3px 0 #000',
  '3px -3px 0 #000',
  '-3px 3px 0 #000',
  '3px 3px 0 #000',
  '0 -3px 0 #000',
  '0 3px 0 #000',
  '-3px 0 0 #000',
  '3px 0 0 #000',
  '0 8px 30px rgba(0,0,0,0.85)',
].join(', ');

const ShotShell: React.FC<{children: React.ReactNode}> = ({children}) => (
  <div
    style={{
      position: 'absolute',
      left: SHOT_X,
      top: SHOT_TOP,
      width: SHOT_WIDTH,
      height: SHOT_HEIGHT,
      fontFamily: theme.fonts.ui,
      color: theme.colors.text
    }}
  >
    {children}
  </div>
);

// ---------------- Definition Card (impact_title_card) ----------------
// Landscape variant: full-bleed centered headline. The screen is intentionally
// quiet — no chrome, no panel — to let the headline carry weight against the
// image-heavy split shots. Negative space IS the design.

const DefinitionLandscape: React.FC<ShotTemplateProps> = ({shot, title, shotIndex = 0}) => {
  const text = shot?.screen_text || title;
  const labelName = shot?.english_label || 'Definition';
  const labelStyle = shot?.label_style || 'comment';
  // Scene-aware uppercase tag — replaces the previous ``# def name() -> str``
  // pseudo-Python decoration. Mainstream Chinese AI/科技 short-video
  // creators (MyElc / 计算机大白) use plain uppercase section pills, not
  // code-style decorations, because (a) it reads as authoritative
  // signage instead of inside-joke and (b) it doesn't compete with the
  // headline for the viewer's first 0.5s of attention.
  const sceneId = String(shot?.scene_id || '').toLowerCase();
  const TAG_BY_SCENE: Record<string, {zh: string; en: string}> = {
    hook: {zh: '钩子', en: 'HOOK'},
    context: {zh: '背景', en: 'CONTEXT'},
    mechanism: {zh: '机制', en: 'HOW'},
    evidence: {zh: '证据', en: 'EVIDENCE'},
    extend: {zh: '延展', en: 'MORE'},
    takeaway: {zh: '判断', en: 'TAKEAWAY'},
    boundary: {zh: '边界', en: 'EDGE'},
  };
  const tag = TAG_BY_SCENE[sceneId] || {zh: '定义', en: 'DEFINITION'};

  return (
    <ShotShell>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 130,
          bottom: 30,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center'
        }}
      >
        {SHOW_SECTION_PILL ? (
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 14,
              padding: '10px 22px',
              borderRadius: 999,
              border: `1px solid ${theme.colors.panelBorder}`,
              background: 'rgba(10,13,18,0.78)',
              fontFamily: theme.fonts.mono,
              fontSize: 22,
              letterSpacing: 1.4,
              color: theme.colors.textSoft,
              marginBottom: 32,
            }}
          >
            <span style={{color: theme.colors.primary, fontWeight: 800}}>{tag.zh}</span>
            <span style={{color: theme.colors.muted}}>·</span>
            <span style={{color: theme.colors.secondary, fontWeight: 700}}>{tag.en}</span>
          </div>
        ) : null}
        <div
          style={{
            fontSize: 130,
            lineHeight: 1.04,
            fontWeight: 900,
            color: theme.colors.text,
            textShadow: LANDSCAPE_HEADLINE_SHADOW,
            maxWidth: '90%'
          }}
        >
          {text}
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Variable Spotlight (keyword_punch_card) ----------------
// Landscape variant: centered Python assignment. The variable name lives on
// its own line above, the value (the actual punch line) is dead-center in
// CRT green. Closing paren echoes back below so the rhythm reads like code.

const VariableLandscape: React.FC<ShotTemplateProps> = ({shot, title, shotIndex = 0}) => {
  const text = shot?.screen_text || shot?.highlight || title;
  const labelName = shot?.english_label || 'Spotlight';
  const labelStyle = shot?.label_style || 'cell';

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // Per-shot motion vocabulary (slow_push / snap_zoom / quick_push / ...)
  // drives the keyword-card transform so two consecutive
  // keyword_punch_card shots in the same scene visually differ even
  // though their template is the same.
  const motionVar = motionTransform(shot?.motion, frame, fps);
  const pulse = interpolate(frame, [18, 36, 60], [1.0, 1.04, 1.0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const chunks = splitByNumbersLandscape(text);

  return (
    <ShotShell>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 130,
          bottom: 30,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center'
        }}
      >
        {/* Compact uppercase tag replaces the previous ``VARIABLE = (`` /
            ``)`` Python brackets. The spotlight variant is meant to land
            ONE punchy data point (e.g. "200 美元" / "8 万 star"); wrapping
            it in code syntax made it read as "fake terminal output" —
            inside-joke for devs, alienating for the broader 抖音/B站
            audience that mainstream creators target. */}
        {SHOW_SECTION_PILL ? (
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 14,
              padding: '10px 22px',
              borderRadius: 999,
              border: `1px solid ${theme.colors.panelBorder}`,
              background: 'rgba(10,13,18,0.78)',
              fontFamily: theme.fonts.mono,
              fontSize: 22,
              letterSpacing: 1.4,
              color: theme.colors.textSoft,
              marginBottom: 36,
            }}
          >
            <span style={{color: theme.colors.primary, fontWeight: 800}}>重点</span>
            <span style={{color: theme.colors.muted}}>·</span>
            <span style={{color: theme.colors.secondary, fontWeight: 700}}>SPOTLIGHT</span>
          </div>
        ) : null}
        <div
          style={{
            opacity: motionVar.opacity,
            transform: `${motionVar.transform} scale(${pulse})`,
            fontSize: 128,
            lineHeight: 1.04,
            fontWeight: 900,
            color: theme.colors.primary,
            textShadow: [
              '-2px -2px 0 #000',
              '2px -2px 0 #000',
              '-2px 2px 0 #000',
              '2px 2px 0 #000',
              '0 -2px 0 #000',
              '0 2px 0 #000',
              '-2px 0 0 #000',
              '2px 0 0 #000',
              `0 0 40px ${theme.colors.glow}`,
              '0 10px 30px rgba(0,0,0,0.72)'
            ].join(', '),
            wordBreak: 'break-word',
            maxWidth: '90%'
          }}
        >
          {chunks.map((chunk, idx) =>
            chunk.isNumber ? (
              <span
                key={idx}
                style={{
                  color: theme.colors.warning,
                  letterSpacing: 0,
                  textShadow: [
                    '-2px -2px 0 #000',
                    '2px -2px 0 #000',
                    '-2px 2px 0 #000',
                    '2px 2px 0 #000',
                    `0 0 38px ${theme.colors.warning}`,
                    `0 0 72px ${theme.colors.warning}`,
                    '0 10px 30px rgba(0,0,0,0.8)',
                  ].join(', '),
                }}
              >
                {chunk.text}
              </span>
            ) : (
              <span key={idx}>{chunk.text}</span>
            ),
          )}
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Assertion Card (judgement_card) ----------------
// Landscape variant: centered Python REPL session. Orange ``assert (...)``
// brackets the punch line, with an optional comment line beneath as the
// "reason". Lots of breathing room — this is the editorial moment.

const AssertionLandscape: React.FC<ShotTemplateProps> = ({shot, title, shotIndex = 0}) => {
  const text = shot?.screen_text || title;
  const labelName = shot?.english_label || 'Take & CTA';
  const labelStyle = shot?.label_style || 'shell';

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // Two-stage spring entrance so the takeaway reads first, then the pills
  // slide up a beat later. Matches the MyElc CTA rhythm (see IMG_5835 /
  // last 6s: 下期见 → pills appear from bottom).
  const claimSpring = spring({frame, fps, config: {damping: 22, stiffness: 110, mass: 0.9}});
  const pillsSpring = spring({
    frame: Math.max(0, frame - 18),
    fps,
    config: {damping: 20, stiffness: 130, mass: 0.7},
  });
  const claimTranslate = interpolate(claimSpring, [0, 1], [36, 0]);
  const claimOpacity = interpolate(claimSpring, [0, 1], [0, 1]);
  const pillsTranslate = interpolate(pillsSpring, [0, 1], [28, 0]);
  const pillsOpacity = interpolate(pillsSpring, [0, 1], [0, 1]);
  const prompt = pickLandscapePrompt(text);

  return (
    <ShotShell>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 110,
          bottom: 30,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        {/* Takeaway block — uppercase pill replaces the previous
            ``>>> assert (...), "why"`` Python REPL framing. The pill is
            the same component as DefinitionLandscape / VariableLandscape
            so the three "pure typography" templates share one section
            grammar and the viewer's eye tracks the pill as a consistent
            "heading slot" across cuts. */}
        <div
          style={{
            opacity: claimOpacity,
            transform: `translateY(${claimTranslate}px)`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 26,
            marginTop: 40,
          }}
        >
          {SHOW_SECTION_PILL ? (
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 14,
                padding: '10px 22px',
                borderRadius: 999,
                border: `1px solid ${theme.colors.panelBorder}`,
                background: 'rgba(10,13,18,0.78)',
                fontFamily: theme.fonts.mono,
                fontSize: 22,
                letterSpacing: 1.4,
                color: theme.colors.textSoft,
              }}
            >
              <span style={{color: theme.colors.warning, fontWeight: 800}}>判断</span>
              <span style={{color: theme.colors.muted}}>·</span>
              <span style={{color: theme.colors.secondary, fontWeight: 700}}>TAKEAWAY</span>
            </div>
          ) : null}
          <div
            style={{
              fontSize: 110,
              lineHeight: 1.08,
              fontWeight: 900,
              color: theme.colors.warning,
              textShadow: LANDSCAPE_HEADLINE_SHADOW,
              maxWidth: '88%',
              textAlign: 'center',
            }}
          >
            {text}
          </div>
        </div>

        {/* CTA pills block anchored near the bottom ribbon. Kept the
            "下期见" stinger because that's a recognisable mainstream
            short-video closer (MyElc / 计算机大白 both use it), but
            removed the ``// `` comment prefix that gave it a Python
            decoration vibe. */}
        <div
          style={{
            opacity: pillsOpacity,
            transform: `translateY(${pillsTranslate}px)`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 20,
            paddingBottom: 16,
          }}
        >
          <div
            style={{
              fontFamily: theme.fonts.ui,
              fontSize: 36,
              color: theme.colors.textSoft,
              letterSpacing: 0.4,
            }}
          >
            {prompt}
          </div>
          <div style={{display: 'flex', gap: 32}}>
            <LandscapeCtaPill
              icon="+"
              label="关注"
              color={theme.colors.primary}
              glow={theme.colors.primarySoft}
            />
            <LandscapeCtaPill
              icon="💬"
              label="评论"
              color={theme.colors.secondary}
              glow={theme.colors.secondarySoft}
            />
            <LandscapeCtaPill
              icon="★"
              label="收藏"
              color={theme.colors.warning}
              glow={theme.colors.warningSoft}
            />
          </div>
          <div
            style={{
              fontFamily: theme.fonts.ui,
              fontSize: 28,
              color: theme.colors.muted,
              letterSpacing: 1.4,
              marginTop: 4,
            }}
          >
            下期见
          </div>
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Caption-on-evidence overlay ----------------
//
// Previously this rendered a 36/64 split where the right column held a
// Mac-Chrome'd screenshot. The screenshot itself is now drawn full-screen
// underneath via ``FullscreenEvidence``, so this overlay degenerates to a
// single caption block sitting on top of the image with a heavy stroke for
// readability. Dispatcher still passes a ``variant`` so caption hints can
// vary (repo overview / evidence zoom / browser snapshot / readme cell).

type SplitVariant =
  | 'repo_full_bleed'
  | 'repo_evidence_zoom'
  | 'browser_focus'
  | 'readme_visual_card';

const SPLIT_PRESETS: Record<
  SplitVariant,
  {
    defaultLabel: string;
    captionHint: string; // shown above the headline as `// HINT`
  }
> = {
  repo_full_bleed: {
    defaultLabel: 'Repo View',
    captionHint: 'repo overview',
  },
  repo_evidence_zoom: {
    defaultLabel: 'Evidence Zoom',
    captionHint: 'evidence zoom',
  },
  browser_focus: {
    defaultLabel: 'Browser View',
    captionHint: 'browser snapshot',
  },
  readme_visual_card: {
    defaultLabel: 'README Cell',
    captionHint: 'readme cell',
  },
};

const CaptionOnEvidence: React.FC<ShotTemplateProps & {variant: SplitVariant}> = ({
  shot,
  evidence,
  title,
  shotIndex = 0,
  variant,
  repoName,
}) => {
  const preset = SPLIT_PRESETS[variant];
  const role = String(evidence?.role || '');
  const chrome = resolveChrome(role, repoName, {
    kind: role.startsWith('browser_') ? 'browser' : 'terminal',
    title: '',
  });
  const labelName =
    shot?.english_label || (chrome.isPhotographic ? 'Video Frame' : preset.defaultLabel);
  const labelStyle = shot?.label_style || 'shell';
  const screen = shot?.screen_text || evidence?.label || title;

  return (
    <ShotShell>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />
      {/* Caption block: bold headline anchored bottom-left, sitting in the
          dark gradient zone EdgeGradient paints over the lower third
          of the frame (high contrast, low risk of covering the
          subject's face). The earlier ``// {preset.captionHint}`` line
          (e.g. ``// REPO OVERVIEW``) was removed: for non-GitHub
          subjects (YouTube interviews, blog screenshots) it was outright
          wrong, and even on GitHub repos it just acted as a fake code
          comment competing with the actual headline. */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: SHOT_WIDTH * 0.4,
          bottom: 30,
          display: 'flex',
          flexDirection: 'column',
          gap: 18,
        }}
      >
        <div
          style={{
            fontSize: 64,
            lineHeight: 1.16,
            fontWeight: 900,
            color: theme.colors.text,
            textShadow: LANDSCAPE_HEADLINE_SHADOW,
            maxWidth: '100%',
          }}
        >
          {screen}
        </div>
      </div>
    </ShotShell>
  );
};

const RepoLandscape: React.FC<ShotTemplateProps> = (props) => (
  <CaptionOnEvidence {...props} variant="repo_full_bleed" />
);

const EvidenceLandscape: React.FC<ShotTemplateProps> = (props) => (
  <CaptionOnEvidence {...props} variant="repo_evidence_zoom" />
);

const BrowserLandscape: React.FC<ShotTemplateProps> = (props) => (
  <CaptionOnEvidence {...props} variant="browser_focus" />
);

const ReadmeLandscape: React.FC<ShotTemplateProps> = (props) => (
  <CaptionOnEvidence {...props} variant="readme_visual_card" />
);

// ---------------- Step List (step_list_card) ----------------
// Used for ``mechanism`` scenes ("它怎么做到的"). Three numbered cells stacked
// vertically with a heavy left rail — feels like an explainer step list,
// distinct from CaptionOnEvidence (which is photo-on-bottom-caption). The
// step text comes from ``shot.subtitle_keywords`` (3 keywords → 3 steps);
// when fewer keywords are available we slice the screen_text on '/' or '、'
// so the template degrades gracefully on imperfect upstream data.

const _splitToSteps = (raw: string): string[] => {
  const trimmed = (raw || '').trim();
  if (!trimmed) return [];
  // Authored screen_text in our director uses ' / ' as a 3-keyword separator
  // (see _keyword_phrase). We also accept '、' and ',' for robustness.
  const parts = trimmed.split(/\s*[/／、，,|]\s*/).map((p) => p.trim()).filter(Boolean);
  return parts.slice(0, 3);
};

const StepListLandscape: React.FC<ShotTemplateProps> = ({shot, title, shotIndex = 0}) => {
  const labelName = shot?.english_label || 'Mechanism';
  const labelStyle = shot?.label_style || 'comment';
  const overlay = shot?.screen_text || title;
  const fromKeywords = shot?.subtitle_keywords && shot.subtitle_keywords.length > 0
    ? Array.from(shot.subtitle_keywords).slice(0, 3)
    : [];
  const steps = (fromKeywords.length >= 2 ? fromKeywords : _splitToSteps(overlay));
  // Pad to exactly 3 cells for layout stability (a single-step list looks
  // like a typo); fallback labels are intentionally generic so they don't
  // pollute the narrative.
  const padded = steps.length >= 3 ? steps : steps.concat(['关键动作', '产生效果', '形成结果']).slice(0, 3);

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enterT = spring({frame, fps, config: {damping: 22, stiffness: 110, mass: 0.9}});

  return (
    <ShotShell>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 110,
          bottom: 30,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div style={{display: 'flex', flexDirection: 'column', gap: 28, width: '78%'}}>
          {padded.map((stepText, i) => {
            const offset = interpolate(enterT, [0, 1], [80 + i * 40, 0]);
            const opacity = interpolate(enterT, [Math.min(0.05 * i, 0.6), Math.min(0.4 + 0.05 * i, 0.95)], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });
            return (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 24,
                  transform: `translateX(${offset}px)`,
                  opacity,
                }}
              >
                <div
                  style={{
                    width: 92,
                    height: 92,
                    borderRadius: 22,
                    background: `linear-gradient(135deg, ${theme.colors.primary}, ${theme.colors.secondary})`,
                    color: '#0b1018',
                    fontFamily: theme.fonts.mono,
                    fontSize: 56,
                    fontWeight: 950,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    boxShadow: `0 12px 32px ${theme.colors.primarySoft}`,
                    flexShrink: 0,
                  }}
                >
                  {i + 1}
                </div>
                <div
                  style={{
                    fontSize: 78,
                    lineHeight: 1.1,
                    fontWeight: 900,
                    color: theme.colors.text,
                    textShadow: LANDSCAPE_HEADLINE_SHADOW,
                  }}
                >
                  {stepText}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Quote Highlight (quote_highlight_card) ----------------
// Used for ``extend`` scenes ("它还能干什么"). A pull-quote layout: oversized
// open-quote glyph at top-left, the keyword phrase rendered in the headline,
// closing-quote glyph bottom-right. Distinct from StepList (which is
// numbered cells) and from CaptionOnEvidence (which is photo + bottom
// caption).

const QuoteHighlightLandscape: React.FC<ShotTemplateProps> = ({shot, title, shotIndex = 0}) => {
  const labelName = shot?.english_label || 'Extend';
  const labelStyle = shot?.label_style || 'shell';
  const text = shot?.screen_text || title;

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const motionVar = motionTransform(shot?.motion, frame, fps);

  return (
    <ShotShell>
      <SectionLabel index={shotIndex + 1} name={labelName} style={labelStyle} />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            position: 'relative',
            width: '78%',
            padding: '40px 60px',
            transform: motionVar.transform,
            opacity: motionVar.opacity,
          }}
        >
          <div
            aria-hidden
            style={{
              position: 'absolute',
              left: -10,
              top: -90,
              fontFamily: 'Georgia, serif',
              fontSize: 240,
              lineHeight: 0.9,
              color: theme.colors.primary,
              opacity: 0.55,
              fontWeight: 900,
            }}
          >
            “
          </div>
          <div
            style={{
              fontSize: 110,
              lineHeight: 1.08,
              fontWeight: 950,
              color: theme.colors.text,
              textShadow: LANDSCAPE_HEADLINE_SHADOW,
              textAlign: 'center',
            }}
          >
            {text}
          </div>
          <div
            aria-hidden
            style={{
              position: 'absolute',
              right: -10,
              bottom: -120,
              fontFamily: 'Georgia, serif',
              fontSize: 240,
              lineHeight: 0.9,
              color: theme.colors.secondary,
              opacity: 0.55,
              fontWeight: 900,
            }}
          >
            ”
          </div>
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Story beat slate (story_beat_card) ----------------
// Editorial chapter marker — typography-only reset between evidence shots.
// Fixes ``context`` (“故事是怎么发生的”) falling through to generic
// caption-on-evidence for every beat.

const SCENE_BEAT_TAGS: Record<string, {zh: string; en: string}> = {
  hook: {zh: '钩子', en: 'HOOK'},
  context: {zh: '故事', en: 'STORY'},
  mechanism: {zh: '机制', en: 'HOW'},
  extend: {zh: '延展', en: 'MORE'},
  takeaway: {zh: '收束', en: 'CLOSE'},
  boundary: {zh: '边界', en: 'EDGE'},
};

const _clipStoryLine = (raw: string, maxChars: number): string => {
  const text = raw.trim().replace(/\s+/g, ' ');
  if (text.length <= maxChars) {
    return text;
  }
  return `${text.slice(0, Math.max(0, maxChars - 1)).replace(/[，,、。；;]$/, '')}…`;
};

const StoryBeatLandscape: React.FC<ShotTemplateProps> = ({shot, title}) => {
  const sceneId = String(shot?.scene_id || 'context');
  const tag = SCENE_BEAT_TAGS[sceneId] || {zh: '节拍', en: 'BEAT'};
  const headline = _clipStoryLine(String(shot?.screen_text || title || ''), 76);

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // Use shot.motion to drive the per-shot transform vocabulary so two
  // consecutive StoryBeat shots in the same scene LOOK different even
  // though the typography template is identical.
  const motionVar = motionTransform(shot?.motion, frame, fps);

  return (
    <ShotShell>
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 96,
          bottom: 40,
          width: 14,
          borderRadius: 6,
          background: `linear-gradient(180deg, ${theme.colors.primary}, ${theme.colors.secondary})`,
          boxShadow: `0 0 28px ${theme.colors.primarySoft}`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 56,
          right: 48,
          top: 118,
          bottom: 52,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 36,
          transform: motionVar.transform,
          opacity: motionVar.opacity,
        }}
      >
        {SHOW_SECTION_PILL ? (
          <div
            style={{
              alignSelf: 'flex-start',
              padding: '10px 22px',
              borderRadius: 999,
              border: `1px solid ${theme.colors.panelBorder}`,
              background: 'rgba(10,13,18,0.78)',
              fontFamily: theme.fonts.mono,
              fontSize: 22,
              letterSpacing: 1.4,
              color: theme.colors.textSoft,
            }}
          >
            <span style={{color: theme.colors.primary, fontWeight: 800}}>{tag.zh}</span>
            <span style={{color: theme.colors.muted, margin: '0 14px'}}>·</span>
            <span style={{color: theme.colors.secondary, fontWeight: 700}}>{tag.en}</span>
          </div>
        ) : null}
        <div
          style={{
            fontSize: headline.length > 48 ? 58 : 72,
            lineHeight: 1.22,
            fontWeight: 950,
            color: theme.colors.text,
            textShadow: LANDSCAPE_HEADLINE_SHADOW,
            letterSpacing: 0.2,
          }}
        >
          {headline}
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Signal pulse strips (signal_pulse_card) ----------------
// Motion-only kinetic beat — breaks the “talking-head + slash keywords” rut.

const _fiveBarRatios = (seed: string): number[] => {
  let hash = 2166136261 >>> 0;
  for (let i = 0; i < seed.length; i++) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16777619) >>> 0;
  }
  return [0, 1, 2, 3, 4].map((slot) => {
    const slice = (hash >> (slot * 5)) & 127;
    return 0.32 + slice / 200;
  });
};

const SignalPulseLandscape: React.FC<ShotTemplateProps> = ({shot, title}) => {
  const label = String(shot?.screen_text || title || '信号节拍').trim();
  const ratios = _fiveBarRatios(label);

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const motionVar = motionTransform(shot?.motion, frame, fps);

  return (
    <ShotShell>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 48,
          transform: motionVar.transform,
          opacity: motionVar.opacity,
        }}
      >
        <div style={{display: 'flex', alignItems: 'flex-end', gap: 34, height: 360}}>
          {ratios.map((ratio, idx) => {
            const stagger = Math.max(0, frame - idx * 3);
            const local = spring({
              frame: stagger,
              fps,
              config: {damping: 16 + idx * 2, stiffness: 120 + idx * 8, mass: 0.7},
            });
            const h = interpolate(local, [0, 1], [24, ratio * 320]);
            return (
              <div
                key={idx}
                style={{
                  width: 62,
                  height: h,
                  borderRadius: 18,
                  background: `linear-gradient(180deg, ${theme.colors.primary}, ${theme.colors.secondary})`,
                  boxShadow: `0 0 22px ${idx % 2 === 0 ? theme.colors.primarySoft : theme.colors.secondarySoft}`,
                }}
              />
            );
          })}
        </div>
        <div
          style={{
            fontFamily: theme.fonts.ui,
            fontSize: 44,
            fontWeight: 800,
            color: theme.colors.text,
            letterSpacing: 0.8,
            textShadow: LANDSCAPE_HEADLINE_SHADOW,
            textAlign: 'center',
            maxWidth: '86%',
          }}
        >
          {label}
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Evidence Showcase ----------------
//
// Real source footage / screenshot rendered as a windowed CARD
// (NOT fullscreen backdrop). This is the "fusion" mode — we co-mount
// real evidence with typography so the video reads as authored
// commentary on real material, not as a slideshow of stock cards.
//
// Layout: 58/38 split. Left card = the actual asset wrapped in a
// browser/terminal chrome with Ken-Burns. Right column = pill tag +
// big headline. We deliberately:
//
//   - DO NOT cover faces with text (the subject's portrait region is
//     never overdrawn — caption sits in the right column, not above
//     the image).
//   - DO NOT scale the asset to fill 100% of the frame (the previous
//     ``FullscreenEvidence`` style made every shot read as "Peter
//     Yang's face plus subtitles" — exactly the "搬运/二创" look the
//     user flagged).
//   - DO frame the asset with a chrome that matches its origin
//     (``www.youtube.com/watch`` for YT keyframes, terminal for
//     repo / CLI screenshots) so the viewer can tell at a glance
//     where the evidence comes from.
//
// One shot per scene gets routed here (see dispatcher); the rest stay
// typography / flow-chart, giving us roughly 1/3 evidence + 1/3 text +
// 1/3 info-graphic across a 30-shot video — that's the visual cadence
// MyElc / 计算机大白 use, just transposed onto our content.
const _evidenceSource = (raw?: string): string | undefined => {
  if (!raw) return undefined;
  if (/^(https?:|file:|data:|blob:)/i.test(raw)) return raw;
  // Asset paths from the Python pipeline arrive as absolute paths on
  // the host (``/root/.../keyframe_03.jpg``); Remotion's bundler can
  // serve them through ``staticFile`` only when they were copied into
  // ``public/``. Otherwise we leave them as-is so the renderer's
  // ``--public-dir=...`` flag picks them up. Keep the conversion
  // single-pass — ``staticFile`` itself is harmless for unknown paths.
  try {
    return staticFile(raw);
  } catch {
    return raw;
  }
};

const ChromeBar: React.FC<{kind: 'browser' | 'terminal' | 'jupyter'; title: string}> = ({
  kind,
  title,
}) => {
  const dotColours = ['#ff5f56', '#ffbd2e', '#27c93f'];
  const isTerminal = kind === 'terminal';
  return (
    <div
      style={{
        height: 44,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '0 18px',
        background: isTerminal ? '#0d1117' : '#1f2329',
        borderBottom: `1px solid ${theme.colors.panelBorder}`,
      }}
    >
      <div style={{display: 'flex', gap: 8}}>
        {dotColours.map((c) => (
          <div
            key={c}
            style={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              background: c,
              opacity: 0.92,
            }}
          />
        ))}
      </div>
      <div
        style={{
          marginLeft: 14,
          fontFamily: theme.fonts.mono,
          fontSize: 16,
          color: theme.colors.muted,
          letterSpacing: 0.4,
          overflow: 'hidden',
          whiteSpace: 'nowrap',
          textOverflow: 'ellipsis',
        }}
      >
        {title || (isTerminal ? '~' : 'about:blank')}
      </div>
    </div>
  );
};

const EvidenceShowcaseLandscape: React.FC<ShotTemplateProps> = ({
  shot,
  evidence,
  title,
  shotIndex = 0,
  repoName,
}) => {
  const sceneId = String(shot?.scene_id || '').toLowerCase();
  const TAG_BY_SCENE: Record<string, {zh: string; en: string}> = {
    hook: {zh: '现场', en: 'SCENE'},
    context: {zh: '背景', en: 'CONTEXT'},
    mechanism: {zh: '过程', en: 'PROCESS'},
    evidence: {zh: '证据', en: 'EVIDENCE'},
    extend: {zh: '延展', en: 'MORE'},
    takeaway: {zh: '收束', en: 'CLOSE'},
  };
  const tag = TAG_BY_SCENE[sceneId] || {zh: '画面', en: 'CLIP'};

  const role = String(evidence?.role || '');
  const chrome = resolveChrome(role, repoName, {
    kind: role.startsWith('browser_') ? 'browser' : 'terminal',
    title: '',
  });
  const src = _evidenceSource(evidence?.src);
  const screen = (shot?.screen_text || evidence?.label || title || '').trim();

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const intro = spring({frame, fps, config: {damping: 22, stiffness: 110, mass: 0.9}});
  const cardLift = interpolate(intro, [0, 1], [50, 0]);
  const cardOpacity = interpolate(intro, [0, 1], [0, 1]);
  const textLift = interpolate(spring({frame: Math.max(0, frame - 6), fps, config: {damping: 22, stiffness: 130, mass: 0.7}}), [0, 1], [40, 0]);
  const textOpacity = interpolate(intro, [0.2, 1], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  // Subtle Ken Burns push so a static image still reads as "moving footage".
  const kenBurns = 1.0 + interpolate(frame, [0, 90], [0, 0.04], {extrapolateRight: 'clamp'});

  return (
    <ShotShell>
      <SectionLabel index={shotIndex + 1} name={chrome.title} style="shell" />
      {/* Left card: chromed asset, ~58% width. Anchored slightly off
          the left edge to keep breathing room from the safe-area stroke
          and to leave a vertical accent column for the right block. */}
      <div
        style={{
          position: 'absolute',
          left: 56,
          top: 110,
          bottom: 100,
          width: '54%',
          borderRadius: 18,
          overflow: 'hidden',
          background: '#0a0d12',
          border: `1px solid ${theme.colors.panelBorder}`,
          boxShadow: '0 24px 60px rgba(0,0,0,0.55), 0 0 28px rgba(34,211,238,0.18)',
          transform: `translateY(${cardLift}px)`,
          opacity: cardOpacity,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <ChromeBar kind={chrome.kind} title={chrome.title} />
        {/* Inner photo area BG: white for browser/jupyter chrome (README
            content / GitHub UI is designed for white pages), black for
            terminal chrome only. Earlier we used black everywhere, which
            hid black-fill wordmark SVGs (browser-use logo) entirely. */}
        <div style={{flex: 1, position: 'relative', overflow: 'hidden', background: chrome.kind === 'terminal' ? '#0d1117' : '#ffffff'}}>
          {src ? (
            <Img
              src={src}
              style={{
                width: '100%',
                height: '100%',
                objectFit: chrome.isPhotographic ? 'cover' : 'contain',
                objectPosition: chrome.isPhotographic ? '50% 35%' : 'center',
                transform: `scale(${kenBurns})`,
                transformOrigin: '50% 45%',
              }}
            />
          ) : (
            <div
              style={{
                width: '100%',
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontFamily: theme.fonts.mono,
                fontSize: 28,
                color: theme.colors.muted,
              }}
            >
              {screen || '素材占位'}
            </div>
          )}
          {/* Bottom-bleed gradient so an evidence label can float over
              the lower edge without fighting the photo content. */}
          <div
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 0,
              height: 96,
              background: 'linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.78) 100%)',
              pointerEvents: 'none',
            }}
          />
          {SHOW_SECTION_PILL && evidence?.label ? (
            <div
              style={{
                position: 'absolute',
                left: 18,
                bottom: 14,
                padding: '6px 12px',
                borderRadius: 8,
                background: 'rgba(7,10,15,0.7)',
                border: `1px solid ${theme.colors.panelBorder}`,
                fontFamily: theme.fonts.mono,
                fontSize: 16,
                color: theme.colors.textSoft,
                letterSpacing: 0.4,
              }}
            >
              {evidence.label}
            </div>
          ) : null}
        </div>
      </div>
      {/* Right column: typography stack — uppercase pill + big headline.
          Same pill grammar as DefinitionLandscape / FlowChartLandscape so
          the entire video shares one section vocabulary regardless of
          template type. */}
      <div
        style={{
          position: 'absolute',
          right: 56,
          top: 130,
          bottom: 120,
          width: '36%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 26,
          transform: `translateY(${textLift}px)`,
          opacity: textOpacity,
        }}
      >
        {SHOW_SECTION_PILL ? (
          <div
            style={{
              display: 'inline-flex',
              alignSelf: 'flex-start',
              alignItems: 'center',
              gap: 12,
              padding: '8px 18px',
              borderRadius: 999,
              border: `1px solid ${theme.colors.panelBorder}`,
              background: 'rgba(10,13,18,0.78)',
              fontFamily: theme.fonts.mono,
              fontSize: 20,
              letterSpacing: 1.4,
              color: theme.colors.textSoft,
            }}
          >
            <span style={{color: theme.colors.primary, fontWeight: 800}}>{tag.zh}</span>
            <span style={{color: theme.colors.muted}}>·</span>
            <span style={{color: theme.colors.secondary, fontWeight: 700}}>{tag.en}</span>
          </div>
        ) : null}
        <div
          style={{
            fontSize: screen.length > 16 ? 60 : 78,
            lineHeight: 1.16,
            fontWeight: 950,
            color: theme.colors.text,
            textShadow: LANDSCAPE_HEADLINE_SHADOW,
            letterSpacing: 0.2,
          }}
        >
          {screen}
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Flow Chart (viz_flow_chart) ----------------
// Data-driven info-graphic. Renders a connected sequence of nodes
// (3-5 boxes) joined by chevron arrows. Used when ``shot.visualization``
// has ``kind: 'flow_chart'`` — typically attached to mechanism scenes
// where the LLM/heuristic extracted concrete action steps from
// the voiceover. Replaces the typography fallback (StepListLandscape)
// for that one shot of the scene.
//
// Why a horizontal chain (not the numbered cells of StepListLandscape):
// flow_chart represents transitions ("拍照 → 识别 → 修复"), not parallel
// items. The arrow glyph between nodes carries the "then" semantic the
// numbered list would force the viewer to infer. This makes the visual
// instantly distinct from StepListLandscape even when both fire on the
// same scene type, which is the diversity goal of 档位 2.
const FlowChartLandscape: React.FC<ShotTemplateProps> = ({shot, title}) => {
  const viz = shot?.visualization;
  const nodes = (viz?.data || [])
    .map((d) => (d.label || '').trim())
    .filter(Boolean)
    .slice(0, 5);
  const headline = (viz?.title || shot?.screen_text || title || '').trim();

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // Stagger each node so the chain reads left-to-right; arrow glyphs
  // fade in slightly behind the trailing node they point into.
  const nodeSpring = (idx: number) =>
    spring({
      frame: Math.max(0, frame - idx * 5),
      fps,
      config: {damping: 20, stiffness: 130, mass: 0.7},
    });

  if (nodes.length < 2) {
    // Defensive: if extractor produced too few nodes, hand off to
    // SignalPulse instead of rendering an empty chart.
    return <SignalPulseLandscape shot={shot} title={title} index={0} total={1} />;
  }

  return (
    <ShotShell>
      {/* Title pill — reuses the same uppercase pill grammar as the
          typography templates so the section grammar stays consistent
          across info-graphic and typography shots. */}
      {SHOW_SECTION_PILL ? (
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: 96,
            display: 'flex',
            justifyContent: 'center',
          }}
        >
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 14,
              padding: '10px 22px',
              borderRadius: 999,
              border: `1px solid ${theme.colors.panelBorder}`,
              background: 'rgba(10,13,18,0.78)',
              fontFamily: theme.fonts.mono,
              fontSize: 22,
              letterSpacing: 1.4,
              color: theme.colors.textSoft,
            }}
          >
            <span style={{color: theme.colors.primary, fontWeight: 800}}>流程</span>
            <span style={{color: theme.colors.muted}}>·</span>
            <span style={{color: theme.colors.secondary, fontWeight: 700}}>FLOW</span>
          </div>
        </div>
      ) : null}
      {/* Headline above the chain (truncated/wrapped naturally). */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 168,
          textAlign: 'center',
          padding: '0 80px',
          fontSize: 56,
          lineHeight: 1.2,
          fontWeight: 900,
          color: theme.colors.text,
          textShadow: LANDSCAPE_HEADLINE_SHADOW,
        }}
      >
        {headline}
      </div>
      {/* Chain of nodes. Wraps to a 2-row grid when 4-5 nodes don't fit
          a single row at the body width (1728px usable). For 3 nodes
          we stay single row at full size. */}
      <div
        style={{
          position: 'absolute',
          left: 64,
          right: 64,
          top: 360,
          bottom: 80,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: nodes.length >= 4 ? 22 : 36,
          flexWrap: 'wrap',
        }}
      >
        {nodes.map((label, idx) => {
          const t = nodeSpring(idx);
          const lift = interpolate(t, [0, 1], [40, 0]);
          const opacity = interpolate(t, [0, 1], [0, 1]);
          // Node colour cycles through primary / secondary / warning so
          // adjacent nodes don't blur into one another.
          const palette = [
            {fill: theme.colors.primary, glow: theme.colors.primarySoft},
            {fill: theme.colors.secondary, glow: theme.colors.secondarySoft},
            {fill: theme.colors.warning, glow: theme.colors.warningSoft},
          ];
          const colour = palette[idx % palette.length];
          const nodeWidth = nodes.length >= 4 ? 280 : 320;
          return (
            <React.Fragment key={idx}>
              <div
                style={{
                  width: nodeWidth,
                  minHeight: 130,
                  padding: '22px 18px',
                  borderRadius: 22,
                  border: `2px solid ${colour.fill}`,
                  background: 'rgba(11,14,19,0.88)',
                  boxShadow: `0 0 32px ${colour.glow}, inset 0 0 14px rgba(0,0,0,0.45)`,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 10,
                  transform: `translateY(${lift}px)`,
                  opacity,
                }}
              >
                <div
                  style={{
                    fontFamily: theme.fonts.mono,
                    fontSize: 22,
                    color: colour.fill,
                    fontWeight: 800,
                    letterSpacing: 1.2,
                  }}
                >
                  STEP {idx + 1}
                </div>
                <div
                  style={{
                    fontSize: 30,
                    lineHeight: 1.2,
                    fontWeight: 800,
                    color: theme.colors.text,
                    textAlign: 'center',
                    textShadow: LANDSCAPE_HEADLINE_SHADOW,
                  }}
                >
                  {label}
                </div>
              </div>
              {idx < nodes.length - 1 && (
                <div
                  style={{
                    fontSize: 64,
                    color: theme.colors.muted,
                    opacity: interpolate(nodeSpring(idx + 1), [0, 1], [0, 1]),
                    fontWeight: 200,
                  }}
                >
                  ›
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </ShotShell>
  );
};

// ---------------- Bar Chart (viz_bar_chart) ----------------
// Renders 2-5 horizontal bars, each with a label, animated bar fill, and
// big value+unit label at the right edge of the bar. Used when scene
// voiceover names multiple quantitative items
// (e.g. "8万 star / 周下载 50万").
//
// Why horizontal bars (not vertical):
// - Chinese labels are wider than English; horizontal layout gives them
//   room without forcing tiny font sizes.
// - Reads top-to-bottom in scan order, matching the viewer's expected
//   "what's the biggest number here?" question.
// - Vertical bars existed already in SignalPulseLandscape (decorative,
//   non-data); horizontal bars stay visually distinct from that pattern.
const BarChartLandscape: React.FC<ShotTemplateProps> = ({shot, title}) => {
  const viz = shot?.visualization;
  const items = (viz?.data || [])
    .map((d) => ({
      label: (d.label || '').trim(),
      value: typeof d.value === 'number' ? d.value : 0,
      unit: d.unit || '',
    }))
    .filter((item) => item.label && item.value > 0)
    .slice(0, 5);
  const headline = (viz?.title || shot?.screen_text || title || '').trim();

  if (items.length < 2) {
    return <SignalPulseLandscape shot={shot} title={title} index={0} total={1} />;
  }

  const maxValue = Math.max(...items.map((it) => it.value));
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  return (
    <ShotShell>
      {SHOW_SECTION_PILL ? (
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: 96,
            display: 'flex',
            justifyContent: 'center',
          }}
        >
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 14,
              padding: '10px 22px',
              borderRadius: 999,
              border: `1px solid ${theme.colors.panelBorder}`,
              background: 'rgba(10,13,18,0.78)',
              fontFamily: theme.fonts.mono,
              fontSize: 22,
              letterSpacing: 1.4,
              color: theme.colors.textSoft,
            }}
          >
            <span style={{color: theme.colors.primary, fontWeight: 800}}>数据</span>
            <span style={{color: theme.colors.muted}}>·</span>
            <span style={{color: theme.colors.secondary, fontWeight: 700}}>DATA</span>
          </div>
        </div>
      ) : null}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 168,
          textAlign: 'center',
          padding: '0 80px',
          fontSize: 52,
          lineHeight: 1.2,
          fontWeight: 900,
          color: theme.colors.text,
          textShadow: LANDSCAPE_HEADLINE_SHADOW,
        }}
      >
        {headline}
      </div>
      <div
        style={{
          position: 'absolute',
          left: 96,
          right: 96,
          top: 320,
          bottom: 90,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 30,
        }}
      >
        {items.map((item, idx) => {
          const t = spring({
            frame: Math.max(0, frame - idx * 4),
            fps,
            config: {damping: 22, stiffness: 100, mass: 0.9},
          });
          const targetWidthPct = (item.value / maxValue) * 100;
          const widthPct = interpolate(t, [0, 1], [0, targetWidthPct]);
          const opacity = interpolate(t, [0, 1], [0, 1]);
          const palette = [
            theme.colors.primary,
            theme.colors.secondary,
            theme.colors.warning,
          ];
          const colour = palette[idx % palette.length];
          return (
            <div
              key={idx}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 24,
                opacity,
              }}
            >
              <div
                style={{
                  width: 240,
                  flexShrink: 0,
                  fontSize: 30,
                  fontWeight: 800,
                  color: theme.colors.text,
                  textAlign: 'right',
                  letterSpacing: 0.4,
                }}
              >
                {item.label}
              </div>
              <div
                style={{
                  flex: 1,
                  height: 56,
                  background: 'rgba(11,14,19,0.6)',
                  border: `1px solid ${theme.colors.panelBorder}`,
                  borderRadius: 12,
                  position: 'relative',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: `${widthPct}%`,
                    background: `linear-gradient(90deg, ${colour}, rgba(255,255,255,0.0))`,
                    boxShadow: `0 0 22px ${colour}`,
                    borderRadius: 12,
                  }}
                />
              </div>
              <div
                style={{
                  width: 200,
                  flexShrink: 0,
                  fontFamily: theme.fonts.mono,
                  fontSize: 38,
                  fontWeight: 900,
                  color: colour,
                  textShadow: LANDSCAPE_HEADLINE_SHADOW,
                }}
              >
                {item.value}
                <span
                  style={{
                    fontSize: 22,
                    marginLeft: 6,
                    color: theme.colors.textSoft,
                    fontWeight: 600,
                  }}
                >
                  {item.unit}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </ShotShell>
  );
};

// ---------------- Dispatcher ----------------
//
// The 3 historically-photographic visual_types (``repo_full_bleed``,
// ``repo_evidence_zoom``, ``readme_visual_card``) used to render a
// creator portrait / repo screenshot as a ~70% backdrop with caption
// overlay. We removed that backdrop globally (see LandscapeExplainer
// for the rationale), so those visual_types now map to typography-only
// equivalents that match the role each was originally trying to play:
//
//   repo_full_bleed     → story_beat_card  (long-form context narration)
//   repo_evidence_zoom  → keyword_punch_card  (single emphasised data point)
//   readme_visual_card  → step_list_card  (structured feature breakdown)
//
// The legacy ``RepoLandscape`` / ``EvidenceLandscape`` / ``ReadmeLandscape``
// templates are kept in the file for now (still valid for non-creator
// sources where the photographic backdrop genuinely adds info), but
// they are no longer the default for these visual_types.
// ---------------- Creator Portrait Templates ----------------
// 4 visual_types added when source is a solo creator / indie founder
// (Pieter Levels, Greg Isenberg, Rob Walling). They share the same
// dark-tech palette as the rest of LandscapeShots so a creator video
// reads as the same brand, not a different show.

// PortraitCardLandscape: hero portrait shot. Big circular avatar on the
// left, name + tagline + 1-line description on the right. Used in hook
// scenes ("这位独立开发者一个人做了 4 个产品，年入 $XM") so the viewer
// sees who we're talking about in the first 3 seconds.
const PortraitCardLandscape: React.FC<ShotTemplateProps> = ({shot, evidence, title, shotIndex = 0}) => {
  const sceneId = String(shot?.scene_id || '').toLowerCase();
  const TAG_BY_SCENE: Record<string, {zh: string; en: string}> = {
    hook: {zh: '人物', en: 'PORTRAIT'},
    context: {zh: '背景', en: 'CONTEXT'},
    mechanism: {zh: '路径', en: 'PATH'},
    extend: {zh: '延展', en: 'MORE'},
    takeaway: {zh: '判断', en: 'TAKEAWAY'},
  };
  const tag = TAG_BY_SCENE[sceneId] || {zh: '人物', en: 'PORTRAIT'};

  const avatarSrc = _evidenceSource(evidence?.src);
  // 一行小字 tag —— shot.screen_text 里第二行,或 evidence.label,fallback 默认
  const screen = (shot?.screen_text || '').trim();
  const screenLines = screen.split(/\s*\/\s*|\s*·\s*|\n/).map((s) => s.trim()).filter(Boolean);
  const headlineName = screenLines[0] || title || '主角';
  const tagline = screenLines.slice(1).join(' · ') || evidence?.label || '';

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const intro = spring({frame, fps, config: {damping: 20, stiffness: 110}});
  const avatarLift = interpolate(intro, [0, 1], [60, 0]);
  const textLift = interpolate(spring({frame: Math.max(0, frame - 6), fps, config: {damping: 22, stiffness: 130}}), [0, 1], [40, 0]);
  const opacity = interpolate(intro, [0, 1], [0, 1]);

  return (
    <ShotShell>
      <SectionLabel index={shotIndex + 1} name={tag.en} style="shell" />
      {/* Section pill 同 EvidenceShowcaseLandscape 风格 */}
      {SHOW_SECTION_PILL ? (
        <div style={{position: 'absolute', left: 56, top: 110, display: 'flex', alignItems: 'center', gap: 12, padding: '8px 18px', borderRadius: 999, border: `1px solid ${theme.colors.panelBorder}`, background: 'rgba(10,13,18,0.78)', fontFamily: theme.fonts.mono, fontSize: 20, letterSpacing: 1.4, color: theme.colors.textSoft, opacity}}>
          <span style={{color: theme.colors.primary, fontWeight: 800}}>{tag.zh}</span>
          <span style={{color: theme.colors.muted}}>·</span>
          <span style={{color: theme.colors.secondary, fontWeight: 700}}>{tag.en}</span>
        </div>
      ) : null}

      {/* 左侧:圆形头像 */}
      <div style={{position: 'absolute', left: 120, top: 200, bottom: 140, width: 540, display: 'flex', alignItems: 'center', justifyContent: 'center', transform: `translateY(${avatarLift}px)`, opacity}}>
        <div style={{position: 'relative', width: 460, height: 460, borderRadius: '50%', overflow: 'hidden', border: `3px solid ${theme.colors.primary}`, boxShadow: `0 0 60px rgba(94,255,143,0.35), inset 0 0 30px rgba(0,0,0,0.4)`, background: '#0a0d12'}}>
          {avatarSrc ? (
            <Img src={avatarSrc} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
          ) : (
            <div style={{width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: theme.fonts.mono, fontSize: 180, fontWeight: 900, color: theme.colors.primary, background: 'linear-gradient(135deg, rgba(94,255,143,0.15), rgba(179,136,255,0.15))'}}>
              {(headlineName || '?').slice(0, 1).toUpperCase()}
            </div>
          )}
        </div>
      </div>

      {/* 右侧:名字 + tagline */}
      <div style={{position: 'absolute', left: 720, right: 80, top: 220, bottom: 140, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 32, transform: `translateY(${textLift}px)`, opacity}}>
        <div style={{fontSize: 96, lineHeight: 1.05, fontWeight: 950, color: theme.colors.text, textShadow: LANDSCAPE_HEADLINE_SHADOW, letterSpacing: -0.5}}>
          {headlineName}
        </div>
        {tagline ? (
          <div style={{fontSize: 36, lineHeight: 1.3, fontWeight: 600, color: theme.colors.textSoft, letterSpacing: 0.3}}>
            {tagline}
          </div>
        ) : null}
      </div>
    </ShotShell>
  );
};

// TimelineLandscape: horizontal year-anchored milestones. Reads
// ``shot.visualization.data`` (timeline kind) — each datum {date, label}
// becomes one milestone. Falls back to ``subtitle_keywords`` rendered
// without dates when no viz payload is attached.
const TimelineLandscape: React.FC<ShotTemplateProps> = ({shot, title, shotIndex = 0}) => {
  const viz = shot?.visualization;
  const milestones: {date: string; label: string}[] = [];
  if (viz?.kind === 'timeline' && Array.isArray(viz.data)) {
    for (const d of viz.data) {
      const date = String(d.date || d.label || '').trim();
      const label = String(d.label || '').trim();
      if (date) milestones.push({date, label: label !== date ? label : ''});
    }
  }
  if (milestones.length === 0) {
    const kws = (shot?.subtitle_keywords || []).slice(0, 5);
    for (const k of kws) milestones.push({date: '', label: String(k)});
  }
  const items = milestones.slice(0, 5);
  const headline = (viz?.title || shot?.screen_text || title || '').trim();

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  return (
    <ShotShell>
      <SectionLabel index={shotIndex + 1} name="Timeline" style="shell" />
      {SHOW_SECTION_PILL ? (
        <div style={{position: 'absolute', left: 0, right: 0, top: 96, display: 'flex', justifyContent: 'center'}}>
          <div style={{display: 'inline-flex', alignItems: 'center', gap: 14, padding: '10px 22px', borderRadius: 999, border: `1px solid ${theme.colors.panelBorder}`, background: 'rgba(10,13,18,0.78)', fontFamily: theme.fonts.mono, fontSize: 22, letterSpacing: 1.4, color: theme.colors.textSoft}}>
            <span style={{color: theme.colors.primary, fontWeight: 800}}>轨迹</span>
            <span style={{color: theme.colors.muted}}>·</span>
            <span style={{color: theme.colors.secondary, fontWeight: 700}}>TIMELINE</span>
          </div>
        </div>
      ) : null}
      {headline ? (
        <div style={{position: 'absolute', left: 0, right: 0, top: 178, textAlign: 'center', padding: '0 80px', fontSize: 56, lineHeight: 1.15, fontWeight: 900, color: theme.colors.text, textShadow: LANDSCAPE_HEADLINE_SHADOW}}>
          {headline}
        </div>
      ) : null}
      {/* 时间轴线 */}
      <div style={{position: 'absolute', left: 120, right: 120, top: 540, height: 4, background: `linear-gradient(90deg, ${theme.colors.primary} 0%, ${theme.colors.secondary} 100%)`, borderRadius: 2, boxShadow: `0 0 20px rgba(94,255,143,0.4)`}} />
      {/* 节点 */}
      <div style={{position: 'absolute', left: 120, right: 120, top: 480, height: 280, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start'}}>
        {items.map((m, idx) => {
          const t = spring({frame: Math.max(0, frame - idx * 5), fps, config: {damping: 22, stiffness: 120}});
          const lift = interpolate(t, [0, 1], [40, 0]);
          const opacity = interpolate(t, [0, 1], [0, 1]);
          return (
            <div key={idx} style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18, transform: `translateY(${lift}px)`, opacity, width: `${100 / items.length}%`, maxWidth: 280}}>
              <div style={{position: 'relative', top: 56, width: 28, height: 28, borderRadius: '50%', background: theme.colors.primary, boxShadow: `0 0 20px ${theme.colors.primary}, inset 0 0 8px rgba(0,0,0,0.3)`, border: `3px solid ${theme.colors.background}`}} />
              {m.date ? (
                <div style={{marginTop: 70, fontFamily: theme.fonts.mono, fontSize: 30, fontWeight: 800, color: theme.colors.warning, letterSpacing: 1}}>{m.date}</div>
              ) : null}
              {m.label ? (
                <div style={{textAlign: 'center', fontSize: 24, lineHeight: 1.3, fontWeight: 700, color: theme.colors.text, padding: '0 8px'}}>{m.label}</div>
              ) : null}
            </div>
          );
        })}
      </div>
    </ShotShell>
  );
};

// TweetQuoteCardLandscape: render a single X/Twitter post as a centered
// card. Used as evidence in extend/takeaway scenes ("他在 X 上说过一句").
// Reads ``shot.screen_text`` for the tweet body and ``evidence.label``
// for the @handle when present; viz data fields can carry likes/reposts.
const TweetQuoteCardLandscape: React.FC<ShotTemplateProps> = ({shot, evidence, title, shotIndex = 0}) => {
  const viz = shot?.visualization;
  const handle = (evidence?.label || (viz?.data?.[0]?.label) || '@levelsio').replace(/^@?/, '@');
  const body = (shot?.screen_text || title || '').trim();
  const likes = Number(viz?.data?.[0]?.value || 0);
  const likesFmt = likes > 1000 ? `${(likes / 1000).toFixed(1)}K` : likes ? String(likes) : '';

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const intro = spring({frame, fps, config: {damping: 22, stiffness: 110}});
  const lift = interpolate(intro, [0, 1], [40, 0]);
  const opacity = interpolate(intro, [0, 1], [0, 1]);

  return (
    <ShotShell>
      <SectionLabel index={shotIndex + 1} name="Tweet" style="shell" />
      {SHOW_SECTION_PILL ? (
        <div style={{position: 'absolute', left: 0, right: 0, top: 96, display: 'flex', justifyContent: 'center'}}>
          <div style={{display: 'inline-flex', alignItems: 'center', gap: 12, padding: '8px 18px', borderRadius: 999, border: `1px solid ${theme.colors.panelBorder}`, background: 'rgba(10,13,18,0.78)', fontFamily: theme.fonts.mono, fontSize: 20, letterSpacing: 1.4, color: theme.colors.textSoft}}>
            <span style={{color: theme.colors.primary, fontWeight: 800}}>原话</span>
            <span style={{color: theme.colors.muted}}>·</span>
            <span style={{color: theme.colors.secondary, fontWeight: 700}}>QUOTE</span>
          </div>
        </div>
      ) : null}
      <div style={{position: 'absolute', left: 220, right: 220, top: 220, bottom: 140, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: 56, borderRadius: 28, background: 'rgba(15,23,42,0.9)', border: `1px solid ${theme.colors.panelBorder}`, boxShadow: '0 24px 60px rgba(0,0,0,0.5), 0 0 30px rgba(56,189,248,0.18)', transform: `translateY(${lift}px)`, opacity}}>
        {/* 头部:蓝鸟 + handle */}
        <div style={{display: 'flex', alignItems: 'center', gap: 16, marginBottom: 32}}>
          <svg width="44" height="44" viewBox="0 0 24 24" fill="#1da1f2"><path d="M22 5.8c-.7.3-1.5.5-2.4.7.9-.5 1.5-1.3 1.8-2.3-.8.5-1.7.8-2.7 1-.8-.8-1.9-1.3-3.1-1.3-2.4 0-4.3 1.9-4.3 4.3 0 .3 0 .7.1 1-3.6-.2-6.7-1.9-8.8-4.5-.4.6-.6 1.4-.6 2.2 0 1.5.8 2.8 1.9 3.6-.7 0-1.4-.2-2-.5 0 2.1 1.5 3.8 3.5 4.2-.4.1-.8.2-1.2.2-.3 0-.6 0-.8-.1.6 1.7 2.2 3 4 3-1.5 1.1-3.3 1.8-5.2 1.8-.3 0-.7 0-1-.1 1.9 1.2 4.1 1.9 6.4 1.9 7.7 0 11.9-6.4 11.9-11.9v-.5c.8-.6 1.5-1.3 2.1-2.2z"/></svg>
          <div style={{fontSize: 32, fontWeight: 800, color: '#1da1f2', letterSpacing: 0.3}}>{handle}</div>
        </div>
        {/* 推文正文 */}
        <div style={{fontSize: 44, lineHeight: 1.4, fontWeight: 600, color: theme.colors.text, letterSpacing: 0.2}}>{body}</div>
        {/* 底部 likes */}
        {likesFmt ? (
          <div style={{marginTop: 32, display: 'flex', gap: 36, fontSize: 22, fontFamily: theme.fonts.mono, color: theme.colors.muted}}>
            <span style={{display: 'inline-flex', alignItems: 'center', gap: 8}}>
              <span style={{color: '#f87171'}}>♥</span>
              <span>{likesFmt}</span>
            </span>
          </div>
        ) : null}
      </div>
    </ShotShell>
  );
};

// ProjectPortfolioGridLandscape: 3-column grid showing a creator's
// project portfolio (e.g. Pieter Levels: Nomad List / Photo AI / Remote OK).
// Reads ``shot.visualization.data`` (3 items with {label, icon?, side?})
// or falls back to ``subtitle_keywords``. Each project gets its own card
// with a logo placeholder + name + 1-line tagline.
const ProjectPortfolioGridLandscape: React.FC<ShotTemplateProps> = ({shot, title, shotIndex = 0}) => {
  const viz = shot?.visualization;
  const projects: {name: string; tagline: string}[] = [];
  if (viz && Array.isArray(viz.data)) {
    for (const d of viz.data) {
      const name = String(d.label || '').trim();
      const tagline = String(d.side || d.unit || '').trim();
      if (name) projects.push({name, tagline});
    }
  }
  if (projects.length === 0) {
    for (const k of (shot?.subtitle_keywords || []).slice(0, 3)) {
      projects.push({name: String(k), tagline: ''});
    }
  }
  const items = projects.slice(0, 3);
  const headline = (viz?.title || shot?.screen_text || title || '').trim();

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  return (
    <ShotShell>
      <SectionLabel index={shotIndex + 1} name="Portfolio" style="shell" />
      {SHOW_SECTION_PILL ? (
        <div style={{position: 'absolute', left: 0, right: 0, top: 96, display: 'flex', justifyContent: 'center'}}>
          <div style={{display: 'inline-flex', alignItems: 'center', gap: 12, padding: '8px 18px', borderRadius: 999, border: `1px solid ${theme.colors.panelBorder}`, background: 'rgba(10,13,18,0.78)', fontFamily: theme.fonts.mono, fontSize: 20, letterSpacing: 1.4, color: theme.colors.textSoft}}>
            <span style={{color: theme.colors.primary, fontWeight: 800}}>作品集</span>
            <span style={{color: theme.colors.muted}}>·</span>
            <span style={{color: theme.colors.secondary, fontWeight: 700}}>PORTFOLIO</span>
          </div>
        </div>
      ) : null}
      {headline ? (
        <div style={{position: 'absolute', left: 0, right: 0, top: 168, textAlign: 'center', padding: '0 80px', fontSize: 52, lineHeight: 1.15, fontWeight: 900, color: theme.colors.text, textShadow: LANDSCAPE_HEADLINE_SHADOW}}>
          {headline}
        </div>
      ) : null}
      <div style={{position: 'absolute', left: 80, right: 80, top: 320, bottom: 100, display: 'grid', gridTemplateColumns: `repeat(${items.length}, 1fr)`, gap: 36}}>
        {items.map((p, idx) => {
          const t = spring({frame: Math.max(0, frame - idx * 6), fps, config: {damping: 22, stiffness: 110}});
          const lift = interpolate(t, [0, 1], [50, 0]);
          const opacity = interpolate(t, [0, 1], [0, 1]);
          const palette = [theme.colors.primary, theme.colors.secondary, theme.colors.warning];
          const color = palette[idx % palette.length];
          return (
            <div key={idx} style={{padding: 36, borderRadius: 24, background: 'rgba(15,23,42,0.85)', border: `2px solid ${color}`, boxShadow: `0 0 32px ${color}33, inset 0 0 16px rgba(0,0,0,0.4)`, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', transform: `translateY(${lift}px)`, opacity}}>
              <div style={{width: 72, height: 72, borderRadius: 16, background: `linear-gradient(135deg, ${color}33, ${color}11)`, border: `1px solid ${color}66`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: theme.fonts.mono, fontSize: 36, fontWeight: 900, color}}>
                {p.name.slice(0, 1).toUpperCase()}
              </div>
              <div style={{display: 'flex', flexDirection: 'column', gap: 14}}>
                <div style={{fontSize: 40, lineHeight: 1.1, fontWeight: 900, color: theme.colors.text, letterSpacing: -0.3}}>{p.name}</div>
                {p.tagline ? (
                  <div style={{fontSize: 22, lineHeight: 1.35, color: theme.colors.textSoft}}>{p.tagline}</div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </ShotShell>
  );
};

// ---------------- Mock Code Editor (viz_code_editor) ----------------
// VSCode-style mock that renders the README's first fenced code block as
// the visual. Replaces "yet another README screenshot" on mechanism
// scenes. Lines fade in 2-by-2 so the editor reads as "code being
// typed" — a touch reference creators (MyElc / 计算机大白) lean on
// when explaining how a tool actually works.
//
// Why a mock not a real editor capture: the source README is markdown,
// not a runnable workspace. Capturing a real VSCode shell would need a
// per-language runtime + theming. A mock that respects the same colour
// vocabulary (keyword, string, comment, number) reads identically at
// 1080p and removes that whole infrastructure dependency.

// Naive single-pass tokenizer. Order matters — comments first (so a
// ``#`` inside a string isn't split), then strings (so a keyword inside
// a string isn't recoloured), then numbers/keywords. Keeps the regex
// list tight; covers the four languages our extractor accepts.
type CodeToken = {text: string; kind: 'comment' | 'string' | 'keyword' | 'number' | 'plain'};

const PYTHON_KEYWORDS = new Set([
  'import', 'from', 'as', 'def', 'class', 'return', 'if', 'elif', 'else',
  'for', 'while', 'in', 'not', 'and', 'or', 'is', 'None', 'True', 'False',
  'await', 'async', 'with', 'try', 'except', 'finally', 'raise', 'pass',
  'lambda', 'yield', 'global', 'nonlocal', 'break', 'continue',
]);
const JS_KEYWORDS = new Set([
  'import', 'from', 'as', 'export', 'default', 'const', 'let', 'var',
  'function', 'class', 'extends', 'return', 'if', 'else', 'for', 'while',
  'do', 'in', 'of', 'new', 'typeof', 'instanceof', 'await', 'async',
  'try', 'catch', 'finally', 'throw', 'switch', 'case', 'break',
  'continue', 'null', 'undefined', 'true', 'false', 'this', 'super',
]);
const SH_KEYWORDS = new Set([
  'if', 'then', 'else', 'fi', 'for', 'do', 'done', 'while', 'case',
  'esac', 'in', 'function', 'return', 'export', 'cd', 'echo', 'pip',
  'npm', 'pnpm', 'yarn', 'curl', 'wget', 'git', 'docker', 'python',
  'node', 'bun', 'uv',
]);

const _keywordSetFor = (lang: string): Set<string> => {
  const l = lang.toLowerCase();
  if (l === 'python' || l === 'py') return PYTHON_KEYWORDS;
  if (l === 'sh' || l === 'bash' || l === 'shell' || l === 'zsh') return SH_KEYWORDS;
  return JS_KEYWORDS;
};

const _tokenizeCodeLine = (line: string, language: string): CodeToken[] => {
  const tokens: CodeToken[] = [];
  const keywords = _keywordSetFor(language);
  const isShell = ['sh', 'bash', 'shell', 'zsh'].includes(language.toLowerCase());
  const commentChar = ['python', 'py', 'sh', 'bash', 'shell', 'zsh'].includes(language.toLowerCase())
    ? '#'
    : '//';
  // Comment cut: anything from commentChar to end of line.
  const commentIdx = line.indexOf(commentChar);
  let body = line;
  let trailingComment = '';
  if (commentIdx >= 0) {
    body = line.slice(0, commentIdx);
    trailingComment = line.slice(commentIdx);
  }
  // Walk body: split on string regions then tokenise non-string regions.
  const STRING_RE = /(['"`])((?:\\.|(?!\1).)*)\1/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = STRING_RE.exec(body)) !== null) {
    if (match.index > cursor) {
      _tokenisePlain(body.slice(cursor, match.index), keywords, isShell, tokens);
    }
    tokens.push({text: match[0], kind: 'string'});
    cursor = match.index + match[0].length;
  }
  if (cursor < body.length) {
    _tokenisePlain(body.slice(cursor), keywords, isShell, tokens);
  }
  if (trailingComment) {
    tokens.push({text: trailingComment, kind: 'comment'});
  }
  return tokens.length ? tokens : [{text: line, kind: 'plain'}];
};

const NUMBER_RE = /\b\d+(?:\.\d+)?\b/g;

const _tokenisePlain = (
  segment: string,
  keywords: Set<string>,
  isShell: boolean,
  out: CodeToken[],
) => {
  // Tokenise on word boundaries, classify each word against keywords/numbers.
  // Whitespace and punctuation stay as plain tokens between words.
  const WORD_RE = /[A-Za-z_][\w-]*|[0-9]+(?:\.[0-9]+)?|\s+|[^\s\w]+/g;
  let m: RegExpExecArray | null;
  while ((m = WORD_RE.exec(segment)) !== null) {
    const w = m[0];
    if (/^\s+$/.test(w)) {
      out.push({text: w, kind: 'plain'});
    } else if (NUMBER_RE.test(w) && /^[0-9.]+$/.test(w)) {
      out.push({text: w, kind: 'number'});
    } else if (keywords.has(w)) {
      out.push({text: w, kind: 'keyword'});
    } else if (isShell && /^[A-Z][A-Z0-9_]+$/.test(w)) {
      // shell ENV_VAR style → number tone for visual contrast
      out.push({text: w, kind: 'number'});
    } else {
      out.push({text: w, kind: 'plain'});
    }
    // Reset NUMBER_RE lastIndex (RegExp.test is stateful with /g).
    NUMBER_RE.lastIndex = 0;
  }
};

const CODE_TOKEN_COLOUR: Record<CodeToken['kind'], string> = {
  comment: '#6a7280',
  string: '#a3e635',
  keyword: '#c084fc',
  number: '#f59e0b',
  plain: '#e5e7eb',
};

const MockCodeEditorLandscape: React.FC<ShotTemplateProps> = ({shot, title}) => {
  const viz = shot?.visualization;
  const filename = (viz?.title || 'quickstart.py').trim();
  const language = String(viz?.caption || 'python').trim();
  const lines: string[] = Array.isArray(viz?.data)
    ? (viz!.data as Array<{text: string}>).map((d) => String(d.text || ''))
    : [];

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // Card lift on enter — keeps the editor consistent with other chrome cards.
  const intro = spring({frame, fps, config: {damping: 22, stiffness: 110, mass: 0.9}});
  const cardLift = interpolate(intro, [0, 1], [60, 0]);
  const cardOpacity = interpolate(intro, [0, 1], [0, 1]);

  // Per-line typing reveal: 2 lines per ~0.5s. Caps at total lines so a
  // long block finishes typing before the shot ends.
  const linesShown = Math.min(
    lines.length,
    Math.max(0, Math.floor((frame / fps) / 0.18)),
  );
  // Cursor blink at the active typing edge.
  const cursorOn = Math.floor(frame / 18) % 2 === 0;

  const headlineText = (shot?.screen_text || title || '').trim();

  return (
    <ShotShell>
      {/* Editor card (left ~58%) */}
      <div
        style={{
          position: 'absolute',
          left: 56,
          top: 110,
          bottom: 100,
          width: '54%',
          borderRadius: 14,
          overflow: 'hidden',
          background: '#0d1117',
          border: `1px solid ${theme.colors.panelBorder}`,
          boxShadow: '0 24px 60px rgba(0,0,0,0.6), 0 0 28px rgba(94,255,143,0.18)',
          transform: `translateY(${cardLift}px)`,
          opacity: cardOpacity,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Title bar with traffic-light dots + filename */}
        <div
          style={{
            height: 38,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '0 14px',
            background: '#1f2329',
            borderBottom: `1px solid ${theme.colors.panelBorder}`,
          }}
        >
          <div style={{display: 'flex', gap: 7}}>
            <span style={{width: 12, height: 12, borderRadius: '50%', background: '#ff5f56'}} />
            <span style={{width: 12, height: 12, borderRadius: '50%', background: '#ffbd2e'}} />
            <span style={{width: 12, height: 12, borderRadius: '50%', background: '#27c93f'}} />
          </div>
          <div
            style={{
              fontFamily: theme.fonts.mono,
              fontSize: 13,
              color: '#9ca3af',
              letterSpacing: 0.4,
              marginLeft: 14,
            }}
          >
            {filename}
          </div>
        </div>
        {/* Tab strip */}
        <div
          style={{
            height: 32,
            display: 'flex',
            alignItems: 'center',
            background: '#13171d',
            borderBottom: `1px solid ${theme.colors.panelBorder}`,
            paddingLeft: 4,
          }}
        >
          <div
            style={{
              padding: '0 16px',
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              fontFamily: theme.fonts.mono,
              fontSize: 12,
              color: '#e5e7eb',
              background: '#0d1117',
              borderTop: `2px solid ${theme.colors.primary}`,
              borderLeft: `1px solid ${theme.colors.panelBorder}`,
              borderRight: `1px solid ${theme.colors.panelBorder}`,
            }}
          >
            {filename}
          </div>
        </div>
        {/* Code body — line numbers gutter + tokens */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            background: '#0d1117',
            fontFamily: theme.fonts.mono,
            fontSize: 18,
            lineHeight: 1.6,
            overflow: 'hidden',
          }}
        >
          {/* Gutter */}
          <div
            style={{
              width: 56,
              padding: '14px 0',
              textAlign: 'right',
              color: '#3f444d',
              borderRight: `1px solid ${theme.colors.panelBorder}`,
              userSelect: 'none',
            }}
          >
            {lines.map((_, i) => (
              <div key={`gutter-${i}`} style={{padding: '0 12px', opacity: i < linesShown ? 1 : 0.25}}>
                {i + 1}
              </div>
            ))}
          </div>
          {/* Code lines */}
          <div style={{flex: 1, padding: '14px 18px', whiteSpace: 'pre'}}>
            {lines.map((line, i) => {
              const visible = i < linesShown;
              const tokens = _tokenizeCodeLine(line, language);
              const isActive = i === linesShown;
              return (
                <div
                  key={`code-${i}`}
                  style={{
                    opacity: visible ? 1 : 0,
                    transition: 'opacity 0.12s linear',
                  }}
                >
                  {tokens.map((tk, ti) => (
                    <span key={ti} style={{color: CODE_TOKEN_COLOUR[tk.kind]}}>{tk.text}</span>
                  ))}
                  {isActive && cursorOn ? (
                    <span style={{color: theme.colors.primary, marginLeft: 2}}>▍</span>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
        {/* Status bar */}
        <div
          style={{
            height: 26,
            background: theme.colors.primary,
            color: '#0d1117',
            fontFamily: theme.fonts.mono,
            fontSize: 12,
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            padding: '0 14px',
            letterSpacing: 0.4,
          }}
        >
          {language.toUpperCase()} · {lines.length} lines · UTF-8
        </div>
      </div>
      {/* Right column — headline mirrors evidence-shot layout */}
      <div
        style={{
          position: 'absolute',
          right: 56,
          top: 130,
          bottom: 120,
          width: '36%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 26,
          opacity: cardOpacity,
        }}
      >
        <div
          style={{
            fontSize: headlineText.length > 18 ? 56 : 72,
            lineHeight: 1.16,
            fontWeight: 950,
            color: theme.colors.text,
            textShadow: LANDSCAPE_HEADLINE_SHADOW,
            letterSpacing: 0.2,
          }}
        >
          {headlineText}
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Mock Terminal (viz_terminal) ----------------
// Terminal session mock for context shots that need to show "how do
// you USE this thing" — install + run + first-output. Reads bash/sh
// fenced blocks from README via the Python extractor, annotates each
// line as ``command`` or ``output`` so the renderer can split the
// prompt prefix from the body and colour them differently.
//
// Visual idea: black panel (true terminal black, not the dark-tech
// surface), one mac-style title bar, monospace body. Lines reveal
// progressively, every 4 frames. Active prompt line ends with a
// blinking block cursor.
const MockTerminalLandscape: React.FC<ShotTemplateProps> = ({shot, title}) => {
  const viz = shot?.visualization;
  const data = (Array.isArray(viz?.data) ? viz!.data : []) as Array<{text: string; kind?: string}>;
  const lang = String(viz?.caption || 'bash').trim();

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const intro = spring({frame, fps, config: {damping: 22, stiffness: 110, mass: 0.9}});
  const cardLift = interpolate(intro, [0, 1], [60, 0]);
  const cardOpacity = interpolate(intro, [0, 1], [0, 1]);
  const linesShown = Math.min(data.length, Math.max(0, Math.floor((frame / fps) / 0.22)));
  const cursorOn = Math.floor(frame / 18) % 2 === 0;

  const headlineText = (shot?.screen_text || title || '').trim();

  return (
    <ShotShell>
      <div
        style={{
          position: 'absolute',
          left: 56,
          top: 110,
          bottom: 100,
          width: '54%',
          borderRadius: 14,
          overflow: 'hidden',
          background: '#000000',
          border: `1px solid ${theme.colors.panelBorder}`,
          boxShadow: '0 24px 60px rgba(0,0,0,0.6), 0 0 28px rgba(94,255,143,0.15)',
          transform: `translateY(${cardLift}px)`,
          opacity: cardOpacity,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Title bar */}
        <div
          style={{
            height: 38,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '0 14px',
            background: '#1f2329',
            borderBottom: `1px solid ${theme.colors.panelBorder}`,
          }}
        >
          <div style={{display: 'flex', gap: 7}}>
            <span style={{width: 12, height: 12, borderRadius: '50%', background: '#ff5f56'}} />
            <span style={{width: 12, height: 12, borderRadius: '50%', background: '#ffbd2e'}} />
            <span style={{width: 12, height: 12, borderRadius: '50%', background: '#27c93f'}} />
          </div>
          <div
            style={{
              fontFamily: theme.fonts.mono,
              fontSize: 13,
              color: '#9ca3af',
              letterSpacing: 0.4,
              marginLeft: 14,
            }}
          >
            {lang}
          </div>
        </div>
        {/* Body */}
        <div
          style={{
            flex: 1,
            padding: '20px 22px',
            background: '#000000',
            fontFamily: theme.fonts.mono,
            fontSize: 18,
            lineHeight: 1.7,
            whiteSpace: 'pre',
            overflow: 'hidden',
          }}
        >
          {data.map((line, i) => {
            const visible = i < linesShown;
            const isCommand = line.kind === 'command' || /^\s*[\$#>]/.test(line.text);
            const isActive = i === linesShown - 1;
            // Strip leading `$ ` so we render it as a separately-coloured prompt
            // glyph rather than baked into the command body.
            const stripped = line.text.replace(/^\s*[\$#>]\s?/, '');
            return (
              <div
                key={`line-${i}`}
                style={{
                  opacity: visible ? 1 : 0,
                  transition: 'opacity 0.1s linear',
                }}
              >
                {isCommand ? (
                  <>
                    <span style={{color: theme.colors.primary, fontWeight: 700}}>$ </span>
                    <span style={{color: '#e5e7eb'}}>{stripped}</span>
                  </>
                ) : (
                  <span style={{color: '#9ca3af'}}>{line.text}</span>
                )}
                {isActive && cursorOn ? (
                  <span style={{color: theme.colors.primary, marginLeft: 2}}>▍</span>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
      {/* Right column headline */}
      <div
        style={{
          position: 'absolute',
          right: 56,
          top: 130,
          bottom: 120,
          width: '36%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 26,
          opacity: cardOpacity,
        }}
      >
        <div
          style={{
            fontSize: headlineText.length > 18 ? 56 : 72,
            lineHeight: 1.16,
            fontWeight: 950,
            color: theme.colors.text,
            textShadow: LANDSCAPE_HEADLINE_SHADOW,
            letterSpacing: 0.2,
          }}
        >
          {headlineText}
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Mock Comparison Table (viz_comparison_table) ----------------
// 2-column comparison table for mechanism scenes that contrast the
// project being explained with a "traditional / before" alternative.
// Reads the heuristic ``comparison_table`` payload built by Python from
// "传统的 X 工具（比如 A、B）需要 Y" + "<repo> 的思路是 Z" patterns.
//
// Visual: full-width table on the LEFT, 56% width, with a header row
// and 3 dimension rows. Old side is muted/strikethrough-feel; new side
// is highlighted with primary colour. Right column carries the spoken
// line so the table is "for support" rather than "for read".
const MockComparisonTableLandscape: React.FC<ShotTemplateProps> = ({shot, title}) => {
  const viz = shot?.visualization;
  const rows = (Array.isArray(viz?.data) ? viz!.data : []) as Array<{
    label: string;
    left: string;
    right: string;
  }>;
  // caption holds "<old> vs <new>" — split it for column headers.
  const caption = String(viz?.caption || '').trim();
  const sides = caption.split(/\s+vs\s+/i);
  const leftHeader = (sides[0] || '传统方法').trim();
  const rightHeader = (sides[1] || '新方法').trim();

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const intro = spring({frame, fps, config: {damping: 22, stiffness: 110, mass: 0.9}});
  const cardLift = interpolate(intro, [0, 1], [60, 0]);
  const cardOpacity = interpolate(intro, [0, 1], [0, 1]);
  // Per-row reveal: 0.3s apart, after a 0.3s pre-roll for the headers.
  const rowProgress = (rowIdx: number): number => {
    const t = Math.max(0, frame / fps - 0.3 - rowIdx * 0.3);
    return Math.min(1, t / 0.5);
  };

  const headlineText = (shot?.screen_text || title || '').trim();

  return (
    <ShotShell>
      <div
        style={{
          position: 'absolute',
          left: 56,
          top: 110,
          bottom: 100,
          width: '54%',
          borderRadius: 14,
          overflow: 'hidden',
          background: '#0a0d12',
          border: `1px solid ${theme.colors.panelBorder}`,
          boxShadow: '0 24px 60px rgba(0,0,0,0.5)',
          transform: `translateY(${cardLift}px)`,
          opacity: cardOpacity,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Header row */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '120px 1fr 1fr',
            background: '#13171d',
            borderBottom: `2px solid ${theme.colors.primary}`,
            padding: '14px 18px',
            fontFamily: theme.fonts.mono,
            fontSize: 18,
            fontWeight: 700,
            letterSpacing: 0.4,
            color: theme.colors.textSoft,
            gap: 18,
          }}
        >
          <span>维度</span>
          <span style={{color: '#9ca3af'}}>{leftHeader}</span>
          <span style={{color: theme.colors.primary}}>{rightHeader}</span>
        </div>
        {/* Rows */}
        <div style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-evenly', padding: '14px 0'}}>
          {rows.map((row, i) => {
            const reveal = rowProgress(i);
            const yOffset = (1 - reveal) * 24;
            return (
              <div
                key={`row-${i}`}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '120px 1fr 1fr',
                  padding: '12px 18px',
                  fontFamily: theme.fonts.ui,
                  fontSize: 22,
                  lineHeight: 1.3,
                  color: theme.colors.text,
                  gap: 18,
                  alignItems: 'center',
                  opacity: reveal,
                  transform: `translateY(${yOffset}px)`,
                  borderBottom: i === rows.length - 1 ? 'none' : `1px solid rgba(255,255,255,0.06)`,
                }}
              >
                <span
                  style={{
                    color: theme.colors.textSoft,
                    fontWeight: 700,
                    fontFamily: theme.fonts.mono,
                    fontSize: 18,
                    letterSpacing: 0.3,
                  }}
                >
                  {row.label}
                </span>
                <span style={{color: '#9ca3af', display: 'flex', alignItems: 'center', gap: 10}}>
                  <span style={{color: '#ef4444', fontWeight: 800}}>✗</span>
                  {row.left}
                </span>
                <span style={{color: theme.colors.text, display: 'flex', alignItems: 'center', gap: 10}}>
                  <span style={{color: theme.colors.primary, fontWeight: 800}}>✓</span>
                  {row.right}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      {/* Right column headline */}
      <div
        style={{
          position: 'absolute',
          right: 56,
          top: 130,
          bottom: 120,
          width: '36%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 26,
          opacity: cardOpacity,
        }}
      >
        <div
          style={{
            fontSize: headlineText.length > 18 ? 56 : 72,
            lineHeight: 1.16,
            fontWeight: 950,
            color: theme.colors.text,
            textShadow: LANDSCAPE_HEADLINE_SHADOW,
            letterSpacing: 0.2,
          }}
        >
          {headlineText}
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Mock Browser Agent (viz_browser_agent) ----------------
// Demonstrates "AI 操控浏览器" — Chrome-style window with a scripted
// mouse cursor that walks through navigate → click → type/screenshot.
// Each step holds for ~1.4s with a click-ring flash on the click step.
// Designed for ``extend`` scenes of AI-tool / browser-automation
// content (browser-use, openai/codex, anthropic computer-use).
type AgentStep = {action: string; label: string; target: string};

const _AGENT_STEP_HOTSPOTS: Record<string, {x: number; y: number}> = {
  navigate: {x: 320, y: 80},   // URL bar
  click: {x: 540, y: 320},     // mid-page button
  type: {x: 520, y: 220},      // search input
  screenshot: {x: 720, y: 64}, // toolbar icon
};

const MockBrowserAgentLandscape: React.FC<ShotTemplateProps> = ({shot, title}) => {
  const viz = shot?.visualization;
  const url = String(viz?.title || 'https://example.com').trim();
  const steps = (Array.isArray(viz?.data) ? (viz!.data as AgentStep[]) : []);

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const intro = spring({frame, fps, config: {damping: 22, stiffness: 110, mass: 0.9}});
  const cardLift = interpolate(intro, [0, 1], [60, 0]);
  const cardOpacity = interpolate(intro, [0, 1], [0, 1]);

  // Step pacing: 1.4s per step. Cursor smoothly transits between hotspots.
  const stepDuration = 1.4 * fps;
  const t = Math.max(0, frame - 12);  // slight pre-roll
  const stepIdx = Math.min(steps.length - 1, Math.floor(t / stepDuration));
  const stepFrac = Math.min(1, (t % stepDuration) / stepDuration);
  const currentStep = steps[stepIdx];
  const prevStep = stepIdx > 0 ? steps[stepIdx - 1] : currentStep;
  const fromHot = prevStep ? _AGENT_STEP_HOTSPOTS[prevStep.action] || {x: 80, y: 60} : {x: 80, y: 60};
  const toHot = currentStep ? _AGENT_STEP_HOTSPOTS[currentStep.action] || {x: 540, y: 320} : {x: 540, y: 320};
  // Easing: cubic ease-in-out for the cursor transit so it doesn't look robotic.
  const ease = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
  const cursorX = fromHot.x + (toHot.x - fromHot.x) * ease(stepFrac);
  const cursorY = fromHot.y + (toHot.y - fromHot.y) * ease(stepFrac);
  // Click ring expands then fades on click step end.
  const clickProgress = currentStep?.action === 'click' && stepFrac > 0.6 ? (stepFrac - 0.6) / 0.4 : 0;

  const headlineText = (shot?.screen_text || title || '').trim();

  return (
    <ShotShell>
      <div
        style={{
          position: 'absolute',
          left: 56,
          top: 110,
          bottom: 100,
          width: '54%',
          borderRadius: 14,
          overflow: 'hidden',
          background: '#ffffff',
          border: `1px solid ${theme.colors.panelBorder}`,
          boxShadow: '0 24px 60px rgba(0,0,0,0.55), 0 0 28px rgba(94,255,143,0.18)',
          transform: `translateY(${cardLift}px)`,
          opacity: cardOpacity,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Browser title bar */}
        <div
          style={{
            height: 36,
            background: '#e8eaed',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '0 12px',
            borderBottom: '1px solid #d0d3d8',
          }}
        >
          <div style={{display: 'flex', gap: 7}}>
            <span style={{width: 12, height: 12, borderRadius: '50%', background: '#ff5f56'}} />
            <span style={{width: 12, height: 12, borderRadius: '50%', background: '#ffbd2e'}} />
            <span style={{width: 12, height: 12, borderRadius: '50%', background: '#27c93f'}} />
          </div>
        </div>
        {/* URL bar */}
        <div
          style={{
            height: 44,
            background: '#f1f3f4',
            display: 'flex',
            alignItems: 'center',
            padding: '0 14px',
            gap: 10,
            borderBottom: '1px solid #d0d3d8',
          }}
        >
          <div
            style={{
              flex: 1,
              height: 28,
              borderRadius: 14,
              background: '#ffffff',
              border: '1px solid #d0d3d8',
              display: 'flex',
              alignItems: 'center',
              padding: '0 14px',
              fontFamily: theme.fonts.mono,
              fontSize: 13,
              color: '#1f2937',
            }}
          >
            <span style={{color: '#6b7280', marginRight: 8}}>🔒</span>
            {url}
          </div>
        </div>
        {/* Page body — abstract mock */}
        <div style={{flex: 1, position: 'relative', background: '#ffffff'}}>
          {/* Sidebar */}
          <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: 64, background: '#fafbfc', borderRight: '1px solid #eef0f2'}} />
          {/* Header strip */}
          <div style={{position: 'absolute', left: 80, right: 24, top: 24, height: 18, background: '#374151', borderRadius: 4, opacity: 0.85}} />
          <div style={{position: 'absolute', left: 80, top: 56, width: 240, height: 12, background: '#9ca3af', borderRadius: 3}} />
          {/* Search input — type-step hotspot */}
          <div style={{position: 'absolute', left: 80, right: 24, top: 96, height: 56, background: '#f3f4f6', borderRadius: 8, border: '1px solid #d1d5db', display: 'flex', alignItems: 'center', padding: '0 16px', fontFamily: theme.fonts.ui, fontSize: 18, color: '#1f2937'}}>
            {currentStep?.action === 'type' && stepFrac > 0.4
              ? `${currentStep.target.slice(0, Math.floor((stepFrac - 0.4) * currentStep.target.length / 0.5))}${(Math.floor(frame / 12) % 2 === 0) ? '|' : ''}`
              : <span style={{color: '#9ca3af'}}>搜索...</span>
            }
          </div>
          {/* Cards row */}
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: 80 + i * 200,
                top: 196,
                width: 180,
                height: 140,
                background: '#ffffff',
                border: '1px solid #e5e7eb',
                borderRadius: 8,
                boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
              }}
            >
              <div style={{height: 60, background: '#e5e7eb', borderTopLeftRadius: 8, borderTopRightRadius: 8}} />
              <div style={{margin: '12px 14px 4px', height: 8, background: '#374151', borderRadius: 2}} />
              <div style={{margin: '0 14px', height: 6, background: '#9ca3af', borderRadius: 2, width: '60%'}} />
            </div>
          ))}
          {/* Submit button — click target */}
          <div style={{position: 'absolute', left: 460, top: 290, width: 160, height: 44, background: theme.colors.primary, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: theme.fonts.ui, fontSize: 15, fontWeight: 700, color: '#0d1117'}}>
            提交
          </div>
          {/* Click ring */}
          {clickProgress > 0 ? (
            <div
              style={{
                position: 'absolute',
                left: toHot.x - 30,
                top: toHot.y - 30,
                width: 60 + clickProgress * 60,
                height: 60 + clickProgress * 60,
                borderRadius: '50%',
                border: `3px solid ${theme.colors.primary}`,
                transform: `translate(${-clickProgress * 30}px, ${-clickProgress * 30}px)`,
                opacity: 1 - clickProgress,
              }}
            />
          ) : null}
          {/* Cursor + tooltip */}
          <div
            style={{
              position: 'absolute',
              left: cursorX,
              top: cursorY,
              pointerEvents: 'none',
              transform: 'translate(-2px, -2px)',
            }}
          >
            <svg width="22" height="28" viewBox="0 0 22 28">
              <path d="M2 2 L2 22 L8 17 L12 26 L16 24 L11 16 L18 14 Z" fill="#0d1117" stroke="#ffffff" strokeWidth="1.5" strokeLinejoin="round" />
            </svg>
            {currentStep ? (
              <div
                style={{
                  position: 'absolute',
                  left: 28,
                  top: 0,
                  padding: '6px 12px',
                  borderRadius: 8,
                  background: '#0d1117',
                  border: `1px solid ${theme.colors.primary}`,
                  color: theme.colors.primary,
                  fontFamily: theme.fonts.ui,
                  fontSize: 14,
                  fontWeight: 700,
                  whiteSpace: 'nowrap',
                }}
              >
                {currentStep.label}
              </div>
            ) : null}
          </div>
        </div>
        {/* Step indicator strip at bottom */}
        <div style={{height: 36, background: '#0d1117', display: 'flex', alignItems: 'center', padding: '0 16px', gap: 10, borderTop: `1px solid ${theme.colors.panelBorder}`}}>
          {steps.map((s, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontFamily: theme.fonts.mono,
                fontSize: 12,
                fontWeight: 700,
                color: i === stepIdx ? theme.colors.primary : '#6b7280',
                letterSpacing: 0.4,
              }}
            >
              <span style={{
                width: 8, height: 8, borderRadius: '50%',
                background: i === stepIdx ? theme.colors.primary : '#374151',
                boxShadow: i === stepIdx ? `0 0 10px ${theme.colors.primary}` : 'none',
              }} />
              {String(i + 1).padStart(2, '0')} · {s.label}
            </div>
          ))}
        </div>
      </div>
      {/* Right column headline */}
      <div
        style={{
          position: 'absolute',
          right: 56,
          top: 130,
          bottom: 120,
          width: '36%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 26,
          opacity: cardOpacity,
        }}
      >
        <div
          style={{
            fontSize: headlineText.length > 18 ? 56 : 72,
            lineHeight: 1.16,
            fontWeight: 950,
            color: theme.colors.text,
            textShadow: LANDSCAPE_HEADLINE_SHADOW,
            letterSpacing: 0.2,
          }}
        >
          {headlineText}
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Mock Star History (viz_star_history) ----------------
// Sparkline / area chart of GitHub star growth, synthesised from the
// repo's current star count + creation date. Renders as a smooth path
// with a glowing end-point ball and the final count as the headline.
type StarPoint = {label: string; value: number};

const MockStarHistoryLandscape: React.FC<ShotTemplateProps> = ({shot, title}) => {
  const viz = shot?.visualization;
  const points = (Array.isArray(viz?.data) ? (viz!.data as StarPoint[]) : []);
  const finalLabel = String(viz?.caption || '').trim();
  const repoLabel = String(viz?.title || 'stars').trim();

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const intro = spring({frame, fps, config: {damping: 22, stiffness: 110, mass: 0.9}});
  const cardLift = interpolate(intro, [0, 1], [60, 0]);
  const cardOpacity = interpolate(intro, [0, 1], [0, 1]);
  // Reveal: line draws over 1.2s.
  const drawProgress = Math.min(1, (frame - 18) / (fps * 1.2));

  const headlineText = (shot?.screen_text || title || '').trim();

  // SVG geometry — chart area inside the card.
  const chartW = 720;
  const chartH = 360;
  const padX = 60;
  const padY = 50;
  const innerW = chartW - 2 * padX;
  const innerH = chartH - 2 * padY;
  const maxValue = points.length ? Math.max(...points.map((p) => p.value)) : 1;
  const stepX = points.length > 1 ? innerW / (points.length - 1) : innerW;

  const fullPath = points
    .map((p, i) => {
      const x = padX + i * stepX;
      const y = padY + innerH - (p.value / maxValue) * innerH;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  const areaPath = `${fullPath} L${(padX + (points.length - 1) * stepX).toFixed(1)},${(padY + innerH).toFixed(1)} L${padX.toFixed(1)},${(padY + innerH).toFixed(1)} Z`;

  // Last point coordinates for the end-ball.
  const last = points[points.length - 1];
  const lastX = last ? padX + (points.length - 1) * stepX : padX;
  const lastY = last ? padY + innerH - (last.value / maxValue) * innerH : padY;

  return (
    <ShotShell>
      <div
        style={{
          position: 'absolute',
          left: 56,
          top: 110,
          bottom: 100,
          width: '54%',
          borderRadius: 14,
          overflow: 'hidden',
          background: '#0d1117',
          border: `1px solid ${theme.colors.panelBorder}`,
          boxShadow: '0 24px 60px rgba(0,0,0,0.55), 0 0 28px rgba(94,255,143,0.16)',
          transform: `translateY(${cardLift}px)`,
          opacity: cardOpacity,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Header with repo name + final count */}
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 22px',
            borderBottom: `1px solid ${theme.colors.panelBorder}`,
            background: '#13171d',
          }}
        >
          <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
            <span style={{color: theme.colors.primary, fontSize: 18}}>★</span>
            <span style={{fontFamily: theme.fonts.mono, fontSize: 16, color: theme.colors.textSoft, letterSpacing: 0.4}}>{repoLabel}</span>
          </div>
          <span style={{fontFamily: theme.fonts.mono, fontSize: 22, color: theme.colors.primary, fontWeight: 800, letterSpacing: 0.4}}>{finalLabel}</span>
        </div>
        {/* Chart area */}
        <div style={{flex: 1, position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
          <svg width={chartW} height={chartH} viewBox={`0 0 ${chartW} ${chartH}`}>
            <defs>
              <linearGradient id="starGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={theme.colors.primary} stopOpacity="0.35" />
                <stop offset="100%" stopColor={theme.colors.primary} stopOpacity="0" />
              </linearGradient>
            </defs>
            {/* Grid lines */}
            {[0.25, 0.5, 0.75].map((p) => (
              <line
                key={p}
                x1={padX}
                x2={padX + innerW}
                y1={padY + innerH * p}
                y2={padY + innerH * p}
                stroke={theme.colors.panelBorder}
                strokeDasharray="4 6"
                strokeWidth="1"
                opacity="0.5"
              />
            ))}
            {/* Area under curve */}
            <path d={areaPath} fill="url(#starGradient)" opacity={drawProgress} />
            {/* Line */}
            <path
              d={fullPath}
              fill="none"
              stroke={theme.colors.primary}
              strokeWidth="3.5"
              strokeLinejoin="round"
              strokeLinecap="round"
              strokeDasharray={4000}
              strokeDashoffset={(1 - drawProgress) * 4000}
              style={{filter: `drop-shadow(0 0 12px ${theme.colors.primary})`}}
            />
            {/* End point ball + pulse */}
            {drawProgress > 0.95 && last ? (
              <>
                <circle cx={lastX} cy={lastY} r="14" fill={theme.colors.primary} opacity="0.25" />
                <circle cx={lastX} cy={lastY} r="7" fill={theme.colors.primary} />
              </>
            ) : null}
            {/* X-axis labels */}
            {points.map((p, i) => (
              <text
                key={`xl-${i}`}
                x={padX + i * stepX}
                y={padY + innerH + 24}
                textAnchor="middle"
                fontFamily={theme.fonts.mono}
                fontSize="13"
                fill="#6b7280"
              >
                {p.label}
              </text>
            ))}
          </svg>
        </div>
      </div>
      {/* Right column headline */}
      <div
        style={{
          position: 'absolute',
          right: 56,
          top: 130,
          bottom: 120,
          width: '36%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 26,
          opacity: cardOpacity,
        }}
      >
        <div
          style={{
            fontSize: headlineText.length > 18 ? 56 : 72,
            lineHeight: 1.16,
            fontWeight: 950,
            color: theme.colors.text,
            textShadow: LANDSCAPE_HEADLINE_SHADOW,
            letterSpacing: 0.2,
          }}
        >
          {headlineText}
        </div>
      </div>
    </ShotShell>
  );
};

// ---------------- Mock MRR Dashboard (viz_mrr_dashboard) ----------------
// Stripe-style revenue summary panel for creator_portrait scenes that
// reference revenue. Top KPI tile (MRR), secondary tile (customers),
// bottom sparkline. Numbers extracted from voiceover when present.
type DashRow = {
  key?: string;
  value?: string;
  trend?: string;
  growth?: string;
  points?: number[];
};

const MockMRRDashboardLandscape: React.FC<ShotTemplateProps> = ({shot, title}) => {
  const viz = shot?.visualization;
  const data = (Array.isArray(viz?.data) ? (viz!.data as DashRow[]) : []);
  const mrrRow = data.find((d) => d.key === 'mrr');
  const custRow = data.find((d) => d.key === 'customers');
  const sparkRow = data.find((d) => d.key === 'sparkline');

  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const intro = spring({frame, fps, config: {damping: 22, stiffness: 110, mass: 0.9}});
  const cardLift = interpolate(intro, [0, 1], [60, 0]);
  const cardOpacity = interpolate(intro, [0, 1], [0, 1]);
  const drawProgress = Math.min(1, (frame - 12) / (fps * 1.0));

  const headlineText = (shot?.screen_text || title || '').trim();

  // Sparkline geometry.
  const sparkW = 520;
  const sparkH = 110;
  const sparkPad = 12;
  const points = sparkRow?.points || [];
  const sparkPath = points
    .map((v, i) => {
      const x = sparkPad + (i / Math.max(1, points.length - 1)) * (sparkW - 2 * sparkPad);
      const y = sparkH - sparkPad - v * (sparkH - 2 * sparkPad);
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <ShotShell>
      <div
        style={{
          position: 'absolute',
          left: 56,
          top: 110,
          bottom: 100,
          width: '54%',
          borderRadius: 18,
          overflow: 'hidden',
          background: '#ffffff',
          border: `1px solid ${theme.colors.panelBorder}`,
          boxShadow: '0 24px 60px rgba(0,0,0,0.55), 0 0 28px rgba(99,102,241,0.18)',
          transform: `translateY(${cardLift}px)`,
          opacity: cardOpacity,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Stripe-style header */}
        <div
          style={{
            height: 50,
            background: '#635bff',
            display: 'flex',
            alignItems: 'center',
            padding: '0 22px',
            color: '#ffffff',
            fontFamily: theme.fonts.ui,
            fontSize: 16,
            fontWeight: 700,
            letterSpacing: 0.4,
          }}
        >
          stripe · Dashboard
        </div>
        {/* KPI tiles row */}
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, padding: 22}}>
          {/* MRR tile */}
          <div style={{padding: 22, borderRadius: 12, border: '1px solid #e5e7eb', background: '#f9fafb'}}>
            <div style={{fontFamily: theme.fonts.ui, fontSize: 13, color: '#6b7280', letterSpacing: 0.3, marginBottom: 8}}>MRR · 月度经常性收入</div>
            <div style={{fontFamily: theme.fonts.ui, fontSize: 56, fontWeight: 800, color: '#111827', letterSpacing: -1, marginBottom: 6}}>
              {mrrRow?.value || '$X0K'}
            </div>
            <div style={{display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, color: '#10b981', fontWeight: 700}}>
              <span>↑</span>
              {mrrRow?.growth || '+12%'}
              <span style={{color: '#9ca3af', fontWeight: 400, marginLeft: 4}}>vs 上月</span>
            </div>
          </div>
          {/* Customers tile */}
          <div style={{padding: 22, borderRadius: 12, border: '1px solid #e5e7eb', background: '#f9fafb'}}>
            <div style={{fontFamily: theme.fonts.ui, fontSize: 13, color: '#6b7280', letterSpacing: 0.3, marginBottom: 8}}>付费用户</div>
            <div style={{fontFamily: theme.fonts.ui, fontSize: 56, fontWeight: 800, color: '#111827', letterSpacing: -1, marginBottom: 6}}>
              {custRow?.value || '0'}
            </div>
            <div style={{display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, color: '#10b981', fontWeight: 700}}>
              <span>↑</span>
              {custRow?.growth || '+8%'}
              <span style={{color: '#9ca3af', fontWeight: 400, marginLeft: 4}}>vs 上月</span>
            </div>
          </div>
        </div>
        {/* Sparkline section */}
        <div style={{flex: 1, padding: '0 22px 22px', display: 'flex', flexDirection: 'column', gap: 10}}>
          <div style={{fontFamily: theme.fonts.ui, fontSize: 13, color: '#6b7280', letterSpacing: 0.3}}>过去 30 天 · MRR 走势</div>
          <div style={{flex: 1, position: 'relative', borderRadius: 10, background: '#fafbfc', border: '1px solid #eef0f2', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            <svg width={sparkW} height={sparkH} viewBox={`0 0 ${sparkW} ${sparkH}`}>
              <defs>
                <linearGradient id="mrrGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#635bff" stopOpacity="0.35" />
                  <stop offset="100%" stopColor="#635bff" stopOpacity="0" />
                </linearGradient>
              </defs>
              {sparkPath ? (
                <>
                  <path d={`${sparkPath} L${sparkW - sparkPad},${sparkH - sparkPad} L${sparkPad},${sparkH - sparkPad} Z`} fill="url(#mrrGrad)" opacity={drawProgress} />
                  <path
                    d={sparkPath}
                    fill="none"
                    stroke="#635bff"
                    strokeWidth="3"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    strokeDasharray={2000}
                    strokeDashoffset={(1 - drawProgress) * 2000}
                  />
                </>
              ) : null}
            </svg>
          </div>
        </div>
      </div>
      {/* Right column headline */}
      <div
        style={{
          position: 'absolute',
          right: 56,
          top: 130,
          bottom: 120,
          width: '36%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 26,
          opacity: cardOpacity,
        }}
      >
        <div
          style={{
            fontSize: headlineText.length > 18 ? 56 : 72,
            lineHeight: 1.16,
            fontWeight: 950,
            color: theme.colors.text,
            textShadow: LANDSCAPE_HEADLINE_SHADOW,
            letterSpacing: 0.2,
          }}
        >
          {headlineText}
        </div>
      </div>
    </ShotShell>
  );
};

// Templates that require a real evidence asset to look right. When the
// scene has no asset attached (``evidence.src`` empty) we route them to
// a typography fallback so the shot doesn't render an empty chrome box.
const EVIDENCE_FALLBACK: Record<string, React.FC<ShotTemplateProps>> = {
  repo_full_bleed: StoryBeatLandscape,
  repo_evidence_zoom: VariableLandscape,
  readme_visual_card: StepListLandscape,
};

const EVIDENCE_TEMPLATES = new Set<string>([
  'repo_full_bleed',
  'repo_evidence_zoom',
  'readme_visual_card',
]);

const TEMPLATES: Record<string, React.FC<ShotTemplateProps>> = {
  impact_title_card: DefinitionLandscape,
  keyword_punch_card: VariableLandscape,
  judgement_card: AssertionLandscape,
  step_list_card: StepListLandscape,
  quote_highlight_card: QuoteHighlightLandscape,
  story_beat_card: StoryBeatLandscape,
  signal_pulse_card: SignalPulseLandscape,
  // Evidence-bearing templates — handled specially in the dispatcher
  // (see below) so they only render the showcase when there's a real
  // asset to show, falling back to typography otherwise. Listed here
  // for completeness but the dispatcher overrides this routing.
  repo_full_bleed: EvidenceShowcaseLandscape,
  repo_evidence_zoom: EvidenceShowcaseLandscape,
  readme_visual_card: EvidenceShowcaseLandscape,
  // Visualization markers — see ``video_director.py``. ``viz_*`` is a
  // synthetic visual_type the Python side stamps on a shot when
  // ``Visualization`` was extracted; here we just route to the matching
  // info-graphic component.
  viz_flow_chart: FlowChartLandscape,
  viz_bar_chart: BarChartLandscape,
  // Creator portrait templates — used when source is a solo creator
  // (Pieter Levels / Greg Isenberg / Rob Walling). Visual_types are
  // emitted by ``_shot_specs_for_creator_scene`` in video_director.py.
  portrait_card: PortraitCardLandscape,
  timeline_landscape: TimelineLandscape,
  tweet_quote_card: TweetQuoteCardLandscape,
  project_portfolio_grid: ProjectPortfolioGridLandscape,
};

export const LandscapeShotDispatcher: React.FC<ShotTemplateProps> = (props) => {
  // Prefer ``shot.visualization`` over ``visual_type``: when the director
  // attached a chart payload, the renderer should always honour it even
  // if the visual_type happens to match a typography template (defensive
  // against partial migrations / direct-edited plans).
  const viz = props.shot?.visualization;
  if (viz) {
    if (viz.kind === 'flow_chart') return <FlowChartLandscape {...props} />;
    if (viz.kind === 'bar_chart') return <BarChartLandscape {...props} />;
    if (viz.kind === 'timeline') return <TimelineLandscape {...props} />;
    if (viz.kind === 'comparison') return <ProjectPortfolioGridLandscape {...props} />;
    if (viz.kind === 'code_editor') return <MockCodeEditorLandscape {...props} />;
    if (viz.kind === 'terminal') return <MockTerminalLandscape {...props} />;
    if (viz.kind === 'comparison_table') return <MockComparisonTableLandscape {...props} />;
    if (viz.kind === 'browser_agent') return <MockBrowserAgentLandscape {...props} />;
    if (viz.kind === 'star_history') return <MockStarHistoryLandscape {...props} />;
    if (viz.kind === 'mrr_dashboard') return <MockMRRDashboardLandscape {...props} />;
  }
  const visualType = props.shot?.visual_type || '';
  // Evidence-bearing templates: render the showcase ONLY when an asset
  // is attached. Without an asset we'd render an empty chrome window
  // which reads as "missing image" — fall back to typography instead.
  if (EVIDENCE_TEMPLATES.has(visualType)) {
    const hasAsset = Boolean(props.evidence?.src);
    if (hasAsset) {
      return <EvidenceShowcaseLandscape {...props} />;
    }
    const Fallback = EVIDENCE_FALLBACK[visualType];
    if (Fallback) return <Fallback {...props} />;
  }
  if (TEMPLATES[visualType]) {
    const Template = TEMPLATES[visualType];
    return <Template {...props} />;
  }
  // Unknown visual_type → safe fallback: signal pulse (typography-only,
  // works without any evidence asset).
  return <SignalPulseLandscape {...props} />;
};

// Suppress dead-code warnings on the legacy photographic templates;
// see TEMPLATES rationale above for why we keep them.
void RepoLandscape;
void EvidenceLandscape;
void BrowserLandscape;
void ReadmeLandscape;
