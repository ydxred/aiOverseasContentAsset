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

CREATE INDEX IF NOT EXISTS idx_tasks_content_id ON tasks (content_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_content_id ON artifacts (content_id);
CREATE INDEX IF NOT EXISTS idx_model_runs_content_id ON model_runs (content_id);
CREATE INDEX IF NOT EXISTS idx_topic_opportunities_content_id ON topic_opportunities (content_id);
CREATE INDEX IF NOT EXISTS idx_media_jobs_content_id ON media_jobs (content_id);
CREATE INDEX IF NOT EXISTS idx_feedback_content_id ON feedback (content_id);

