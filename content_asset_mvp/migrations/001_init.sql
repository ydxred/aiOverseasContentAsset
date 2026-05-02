CREATE TABLE IF NOT EXISTS contents (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT UNIQUE NOT NULL,
  source_url TEXT NOT NULL,
  source_type TEXT NOT NULL,
  title TEXT,
  author TEXT,
  published_at TEXT,
  duration INTEGER,
  language TEXT,
  status TEXT NOT NULL,
  total_score INTEGER,
  risk_level TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  task_type TEXT NOT NULL,
  status TEXT NOT NULL,
  retry_count INTEGER DEFAULT 0,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  file_path TEXT NOT NULL,
  version TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_runs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  task_type TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_estimate REAL,
  status TEXT NOT NULL,
  error_message TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_id TEXT UNIQUE NOT NULL,
  source_type TEXT NOT NULL,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  category TEXT,
  trust_score INTEGER DEFAULT 0,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_opportunities (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  topic_cluster TEXT,
  foreign_heat INTEGER,
  domestic_gap INTEGER,
  user_value INTEGER,
  content_rebuildability INTEGER,
  risk_score INTEGER,
  opportunity_score INTEGER,
  decision TEXT NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_jobs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  template_id TEXT,
  platform TEXT,
  output_path TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  feedback_type TEXT NOT NULL,
  reviewer TEXT,
  is_topic_useful INTEGER,
  is_script_usable INTEGER,
  main_issues TEXT,
  notes TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_candidates (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  candidate_id TEXT UNIQUE NOT NULL,
  source_id TEXT,
  source_type TEXT NOT NULL,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  category TEXT,
  status TEXT NOT NULL,
  decision TEXT,
  score INTEGER,
  reason TEXT,
  signals JSONB,
  discovered_from JSONB,
  raw_payload JSONB,
  review_package_content_id TEXT,
  review_package_generated_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publish_tasks (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id TEXT UNIQUE NOT NULL,
  content_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  platform_name TEXT,
  status TEXT NOT NULL,
  priority TEXT,
  scheduled_at TEXT,
  account TEXT,
  publish_url TEXT,
  published_at TEXT,
  title TEXT,
  suitable INTEGER,
  metrics JSONB,
  metrics_latest JSONB,
  manual_review_risks JSONB,
  raw_payload JSONB,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publish_metric_snapshots (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id TEXT NOT NULL,
  content_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  label TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  metrics JSONB,
  note TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (task_id, label, captured_at)
);

CREATE TABLE IF NOT EXISTS feedback_reports (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  report_type TEXT NOT NULL,
  report_path TEXT,
  generated_at TEXT NOT NULL,
  raw_payload JSONB NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_feedback_suggestions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_key TEXT NOT NULL,
  source_type TEXT,
  source_name TEXT,
  action TEXT NOT NULL,
  recommended_weight_delta REAL DEFAULT 0,
  related_content_ids JSONB,
  reasons JSONB,
  evidence_tasks JSONB,
  raw_payload JSONB,
  generated_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_content_id ON tasks (content_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_content_id ON artifacts (content_id);
CREATE INDEX IF NOT EXISTS idx_model_runs_content_id ON model_runs (content_id);
CREATE INDEX IF NOT EXISTS idx_topic_opportunities_content_id ON topic_opportunities (content_id);
CREATE INDEX IF NOT EXISTS idx_media_jobs_content_id ON media_jobs (content_id);
CREATE INDEX IF NOT EXISTS idx_feedback_content_id ON feedback (content_id);
CREATE INDEX IF NOT EXISTS idx_source_candidates_source_id ON source_candidates (source_id);
CREATE INDEX IF NOT EXISTS idx_source_candidates_status ON source_candidates (status);
CREATE INDEX IF NOT EXISTS idx_publish_tasks_content_id ON publish_tasks (content_id);
CREATE INDEX IF NOT EXISTS idx_publish_tasks_status ON publish_tasks (status);
CREATE INDEX IF NOT EXISTS idx_publish_metric_snapshots_task_id ON publish_metric_snapshots (task_id);
CREATE INDEX IF NOT EXISTS idx_source_feedback_suggestions_source_key ON source_feedback_suggestions (source_key);

