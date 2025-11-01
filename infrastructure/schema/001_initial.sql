-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";  -- For generating UUIDs
CREATE EXTENSION IF NOT EXISTS "vector";      -- For AI embeddings

-- Packages table: tracks NPM/PyPI packages discovered and installed
CREATE TABLE packages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name VARCHAR(255) NOT NULL,
  version VARCHAR(50),
  package_manager VARCHAR(50) NOT NULL,  -- 'npm' or 'pip'
  description TEXT,
  installed_at TIMESTAMP DEFAULT NOW(),
  metadata JSONB  -- stores extra info like download count, GitHub stars
);
CREATE INDEX idx_packages_name ON packages(name);

-- Research papers table: stores arXiv papers and extracted algorithms
CREATE TABLE research_papers (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  arxiv_id VARCHAR(50) UNIQUE,
  title TEXT NOT NULL,
  authors TEXT[],
  abstract TEXT,
  published_date DATE,
  pdf_url TEXT,
  algorithms_extracted JSONB,  -- JSON of algorithms found in paper
  time_complexity VARCHAR(100),  -- e.g., "O(log n)"
  space_complexity VARCHAR(100),
  implemented BOOLEAN DEFAULT FALSE,  -- has this been turned into code?
  success_score FLOAT,  -- how well did implementation work?
  abstract_embedding VECTOR(384),  -- AI embedding for semantic search
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_papers_arxiv ON research_papers(arxiv_id);
CREATE INDEX idx_papers_embedding ON research_papers 
  USING ivfflat (abstract_embedding vector_cosine_ops);

-- Generated code table: every piece of code the AI creates
CREATE TABLE generated_code (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  file_path TEXT NOT NULL,
  code_type VARCHAR(50),  -- 'component', 'function', 'api-route'
  language VARCHAR(50),   -- 'typescript', 'python'
  content TEXT NOT NULL,
  dependencies JSONB,  -- which packages does this code need?
  user_prompt TEXT,    -- original user request
  research_paper_id UUID REFERENCES research_papers(id),
  syntax_valid BOOLEAN,
  lint_passing BOOLEAN,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Task executions table: tracks every user request end-to-end
CREATE TABLE task_executions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_intent TEXT NOT NULL,
  agent_plan JSONB,        -- the step-by-step plan the AI created
  capabilities_used JSONB, -- which packages/APIs/papers were used
  generated_files JSONB,   -- list of files created
  status VARCHAR(50),      -- 'pending', 'running', 'success', 'failed'
  error_message TEXT,
  execution_time_ms INTEGER,
  tokens_used INTEGER,
  estimated_cost_usd DECIMAL(10,4),
  user_rating INTEGER,     -- 1-5 stars from user
  created_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP
);

-- Performance metrics table: tracks code performance for optimization
CREATE TABLE performance_metrics (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  code_id UUID REFERENCES generated_code(id),
  metric_type VARCHAR(100) NOT NULL,  -- 'cpu', 'memory', 'latency', 'throughput'
  value FLOAT NOT NULL,
  unit VARCHAR(50),                   -- 'ms', 'MB', 'ops/sec', '%'
  baseline_value FLOAT,               -- original performance before optimization
  improvement_percent FLOAT,          -- calculated improvement over baseline
  timestamp TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_metrics_code ON performance_metrics(code_id);
CREATE INDEX idx_metrics_type ON performance_metrics(metric_type);

-- User feedback table: learns from user interactions
CREATE TABLE user_feedback (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  task_id UUID REFERENCES task_executions(id),
  code_id UUID REFERENCES generated_code(id),
  feedback_type VARCHAR(50) NOT NULL,  -- 'explicit' or 'implicit'
  rating INTEGER CHECK (rating BETWEEN 1 AND 5),  -- 1-5 star rating
  comment TEXT,
  user_edits JSONB,  -- tracks what changes user made to generated code
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_feedback_task ON user_feedback(task_id);
CREATE INDEX idx_feedback_code ON user_feedback(code_id);
CREATE INDEX idx_feedback_type ON user_feedback(feedback_type);
