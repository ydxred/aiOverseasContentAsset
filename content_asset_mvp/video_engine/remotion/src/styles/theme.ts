/**
 * Visual style: "AI Lab Terminal"
 * 给 AI 开发者看的 AI 工具科普视频。
 * 视觉锚点 = GitHub Dark / Jupyter / Terminal / VSCode。
 * 详细规范见 assets/visual_style_guide.json
 */
export const theme = {
  colors: {
    background: '#0E1116',
    backgroundDeep: '#070A0F',
    panel: '#161B22',
    panelSoft: 'rgba(22,27,34,0.78)',
    panelBorder: 'rgba(125,133,144,0.18)',

    primary: '#5EFF8F',
    primarySoft: 'rgba(94,255,143,0.16)',
    secondary: '#B388FF',
    secondarySoft: 'rgba(179,136,255,0.18)',
    warning: '#FF9E5C',
    warningSoft: 'rgba(255,158,92,0.18)',

    diffAdd: '#3FB950',
    diffDel: '#F85149',

    text: '#E6EDF3',
    textSoft: '#B1BAC4',
    muted: '#7D8590',
    comment: '#8B949E',

    glow: 'rgba(94,255,143,0.18)',
    grid: 'rgba(125,133,144,0.06)',

    accent: '#5EFF8F',
    danger: '#FF9E5C'
  },
  fonts: {
    mono: "'JetBrains Mono', 'Fira Code', ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
    ui: "Inter, 'Source Han Sans SC', 'Noto Sans SC', system-ui, sans-serif"
  },
  fontFamily: "Inter, 'Source Han Sans SC', 'Noto Sans SC', sans-serif",
  width: 1080,
  height: 1920,
  safeArea: {
    x: 72,
    y: 1220,
    width: 936,
    height: 360
  },
  shot: {
    top: 180,
    height: 1050,
    // Chrome (browser/terminal/jupyter frame) padding inside the shot area.
    // Lowered from the previous 140/120 to lift screenshot coverage from
    // ~34% of the canvas to ~45%, while keeping clear of the subtitle band
    // at y=1220.
    chromePaddingTop: 72,
    chromePaddingBottom: 56
  },
  // 16:9 landscape variant for B 站 / YouTube / 抖音横版.
  // Centered safe areas, top ribbon ~96px, bottom subtitle band ~140px.
  landscape: {
    width: 1920,
    height: 1080,
    ribbonTop: 36,
    ribbonHeight: 60,
    safeArea: {
      x: 96,
      y: 920,
      width: 1728,
      height: 140
    },
    shot: {
      top: 132,
      height: 768,
      paddingX: 96
    },
    columns: {
      // Left = text column, right = visual column.
      // 36/64 split gives screenshots room to breathe like a real IDE demo
      // while keeping text wide enough for ~14 Chinese characters per line.
      leftRatio: 0.36,
      gap: 56
    }
  }
};
