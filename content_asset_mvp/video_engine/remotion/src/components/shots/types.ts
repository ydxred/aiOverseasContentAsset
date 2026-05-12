export type EvidenceItem = {
  src: string;
  label?: string;
  role?: string;
};

// Mirrors ``Visualization`` in ``app/video_director.py``. Optional payload
// attached to a shot when the heuristic / LLM extractor finds a clean
// data shape we can render as an info-graphic instead of typography.
//
// Field semantics match the Python side; we keep the shape liberal here
// because the Remotion renderer is intentionally tolerant — if the
// payload is malformed for the requested ``kind``, the shot dispatcher
// falls back to typography.
export type VisualizationKind =
  | 'bar_chart'
  | 'flow_chart'
  | 'timeline'
  | 'comparison';

export type VisualizationDatum = {
  // bar_chart
  label?: string;
  value?: number;
  unit?: string;
  // flow_chart
  icon?: string;
  tone?: string;
  // timeline
  date?: string;
  // comparison
  side?: string;
};

export type Visualization = {
  kind: VisualizationKind;
  title?: string;
  caption?: string;
  data: VisualizationDatum[];
};

export type DirectorShot = {
  shot_id?: string;
  /** Present on every exported shot from ``video_director`` — used by editorial templates. */
  scene_id?: string;
  visual_type?: string;
  start?: number;
  end?: number;
  screen_text?: string;
  motion?: string;
  highlight?: string;
  purpose?: string;
  english_label?: string;
  label_style?: 'cell' | 'comment' | 'section' | 'shell' | 'traceback';
  // Real Chinese/English narrative tokens propagated from the parent
  // ``DirectorScene`` (see ``video_director.py``). StepListLandscape
  // consumes this directly to render numbered step cells; other templates
  // fall back to ``screen_text``.
  subtitle_keywords?: string[];
  // Structured info-graphic payload. When present, the shot dispatcher
  // bypasses ``visual_type`` and renders the chart/flow/timeline component.
  visualization?: Visualization;
};

export type ShotTemplateProps = {
  shot?: DirectorShot;
  evidence?: EvidenceItem;
  title: string;
  index: number;
  total: number;
  shotIndex?: number;
  repoName?: string;
};
