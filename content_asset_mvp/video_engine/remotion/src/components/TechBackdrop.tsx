import React, {useMemo} from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../styles/theme';

// Drift lines (the "matrix-rain" of code/ML samples in the side gutters)
// were originally meant as ambient texture, but at full 1080p they stay
// legible enough that the viewer reads strings like
// ``tool_call: send_whatsapp('Other Peter')`` or ``grad_norm = 1.7e-3``
// — content from unrelated demo videos that creates cognitive friction
// for narrative shorts (Pieter Levels portrait, Browser-Use overview).
// Reference creators (MyElc / 计算机大白) keep backdrops to grid + glow.
// Off by default; flip ``REMOTION_SHOW_BACKDROP_DRIFT=1`` to bring back.
const SHOW_BACKDROP_DRIFT =
  typeof process !== 'undefined' &&
  process.env &&
  process.env.REMOTION_SHOW_BACKDROP_DRIFT === '1';

// Two parallel pools keep the backdrop "relevant" across content types.
// The AGENT pool is meant for AI-agent / browser-automation videos (our
// YouTube lane today); the ML pool is the original training-metric flavour
// for model / research repos. Mixing both by index keeps the rim live and
// avoids the "same line loops every 2 seconds" read.
const AGENT_SAMPLES = [
  "await page.goto('https://clawd.bot')",
  'const result = await agent.run(task)',
  'fetch(\'/api/v1/check_in\', {method:POST})',
  'await click(\'#book-flight\')',
  "tool_call: send_whatsapp('Other Peter')",
  'openai.chat.completions.create(...)',
  'mcp.registerTool(\'home.lights\')',
  "agent.memory.recall('last flight')",
  'assert can_execute(task) == True',
  "intent = classify('book a flight')",
  'voice_message.send(recipient)',
  'if hallucination_detected: retry(task)',
  'browser.wait_for_selector(\'.submit\')',
  "dag = planner.build('trip-to-tokyo')",
  'agent.act(observation)',
];

const ML_SAMPLES = [
  'x.shape = (1, 768, 32, 32)',
  'loss = 0.234',
  'attention[0,5,:,:]',
  'grad_norm = 1.7e-3',
  'lr_scheduler.step()',
  'with torch.no_grad():',
  'model.eval()',
  'tokenizer.encode(prompt)',
  '[INFO] step 1240 / 5000',
  'embed_dim = 4096',
  'RoPE(theta=10000)',
  'FlashAttention-2',
  'cosine_sim(q, k) = 0.83',
  'kv_cache_hits = 7421',
  'top_p = 0.92, temp = 0.7',
  'load_state_dict(ckpt)',
  'autograd.grad(loss, params)',
  'F.softmax(logits, dim=-1)',
  'rope_cache_seq_len=8192',
  'micro_batch_size = 4',
];

// Interleave so adjacent drift lines are from different pools — the
// viewer's rim vision sees an evolving, not looping, mix.
const TENSOR_SAMPLES = AGENT_SAMPLES.flatMap((line, idx) => [line, ML_SAMPLES[idx % ML_SAMPLES.length]]);

type DriftLine = {
  text: string;
  xPct: number;
  yStart: number;
  speed: number;
  fontSize: number;
  opacity: number;
};

const buildLines = (count: number): DriftLine[] => {
  // Place drift lines in two side gutters: left 2~26% and right 74~98%.
  // Center 26~74% stays clean so foreground headlines don't fight a moving
  // backdrop. This mimics how real AI-demo videos let the "matrix rain"
  // run only along the rim.
  const lines: DriftLine[] = [];
  for (let i = 0; i < count; i += 1) {
    const t = TENSOR_SAMPLES[(i * 7 + 3) % TENSOR_SAMPLES.length];
    const onLeft = i % 2 === 0;
    const xPct = onLeft ? 2 + ((i * 11) % 24) : 74 + ((i * 13) % 24);
    const yStart = (i * 137) % 1920;
    const speed = 6 + ((i * 5) % 11);
    const fontSize = 14 + ((i * 3) % 6);
    // Pulled back from the old 0.065/0.12 range — at full 1080p they
    // were legible enough that viewers parsed "intent = classify(...)"
    // / "for j = 0..N, temp = 0.7" / "tool_call: send" as content,
    // not ambience (user flagged with red arrows on Screenshot_1).
    // 0.04 base / 0.07 accent keeps the rim drift sensed in peripheral
    // vision but stops the strings from being read.
    const base = i % 5 === 0 ? 0.07 : 0.04;
    const opacity = base + ((i * 11) % 7) * 0.003;
    lines.push({text: t, xPct, yStart, speed, fontSize, opacity});
  }
  return lines;
};

// Per-scene tonal palette. Each scene gets its own glow color so the
// viewer's peripheral vision picks up "we're in a different beat" before
// any caption is read. Calibrated against MyElc / 计算机大白 reference
// footage where each section uses a different hue family (warm intro,
// cool main, accent for data).
//
// Colours below stay inside the same low-saturation, dark-base palette
// the rest of theme.ts uses so the change is FELT, not loud.
type SceneTone = 'hook' | 'context' | 'evidence' | 'takeaway' | 'neutral';
const TONE_PALETTE: Record<SceneTone, {primary: string; secondary: string; primarySpot: string; secondarySpot: string}> = {
  // Hook: pink-magenta + warm gold corner — "look here, energy"
  hook:     {primary: 'rgba(255,108,168,0.22)', secondary: 'rgba(255,200,120,0.18)', primarySpot: '20% 18%',  secondarySpot: '85% 80%'},
  // Context: cool cyan + violet — "let me explain the setup"
  context:  {primary: 'rgba(94,255,143,0.18)',  secondary: 'rgba(179,136,255,0.18)', primarySpot: '18% 14%',  secondarySpot: '82% 86%'},
  // Evidence: green + amber — "here is the data"
  evidence: {primary: 'rgba(94,255,143,0.22)',  secondary: 'rgba(255,158,92,0.18)',  primarySpot: '15% 80%',  secondarySpot: '80% 20%'},
  // Takeaway: amber + violet — "wrap up + my judgement"
  takeaway: {primary: 'rgba(255,158,92,0.22)',  secondary: 'rgba(179,136,255,0.20)', primarySpot: '85% 22%',  secondarySpot: '18% 80%'},
  // Neutral fallback (= original cyan/violet pairing).
  neutral:  {primary: 'rgba(94,255,143,0.18)',  secondary: 'rgba(179,136,255,0.18)', primarySpot: '18% 14%',  secondarySpot: '82% 86%'},
};

export const TechBackdrop: React.FC<{seed?: number; gridSpacing?: number; tone?: SceneTone}> = ({
  gridSpacing = 64,
  tone = 'neutral',
}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  const time = frame / fps;
  const lines = useMemo(() => buildLines(18), []);

  const gridImage = useMemo(
    () =>
      `linear-gradient(${theme.colors.grid} 1px, transparent 1px), linear-gradient(90deg, ${theme.colors.grid} 1px, transparent 1px)`,
    []
  );

  const palette = TONE_PALETTE[tone] ?? TONE_PALETTE.neutral;

  return (
    <AbsoluteFill style={{backgroundColor: theme.colors.background, overflow: 'hidden'}}>
      <AbsoluteFill
        style={{
          backgroundImage: gridImage,
          backgroundSize: `${gridSpacing}px ${gridSpacing}px`,
          backgroundPosition: '0px 0px'
        }}
      />
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle at ${palette.primarySpot}, ${palette.primary} 0%, transparent 38%)`,
          opacity: 0.85
        }}
      />
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle at ${palette.secondarySpot}, ${palette.secondary} 0%, transparent 42%)`,
          opacity: 0.7
        }}
      />
      {SHOW_BACKDROP_DRIFT ? (
        <AbsoluteFill style={{fontFamily: theme.fonts.mono, color: theme.colors.textSoft}}>
          {lines.map((ln, idx) => {
            const traveled = time * ln.speed;
            const yRaw = ln.yStart - traveled;
            const yMod = ((yRaw % (height + 200)) + (height + 200)) % (height + 200) - 100;
            return (
              <div
                key={idx}
                style={{
                  position: 'absolute',
                  left: `${ln.xPct}%`,
                  top: yMod,
                  fontSize: ln.fontSize,
                  opacity: ln.opacity,
                  whiteSpace: 'nowrap',
                  letterSpacing: 0.5,
                  fontFeatureSettings: '"liga" on, "calt" on'
                }}
              >
                {ln.text}
              </div>
            );
          })}
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.55) 100%)',
          pointerEvents: 'none'
        }}
      />
    </AbsoluteFill>
  );
};
