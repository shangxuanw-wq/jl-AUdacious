-- 估價模組資料表（schema rfq）。只用 PostgreSQL 16 就有的語法。
CREATE SCHEMA IF NOT EXISTS rfq;

CREATE TABLE IF NOT EXISTS rfq.schema_migrations (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rfq.customers (
  id smallserial PRIMARY KEY,
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  max_items_per_quote int NOT NULL DEFAULT 1 CHECK (max_items_per_quote >= 1),
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO rfq.customers (code, name, max_items_per_quote) VALUES ('AUD', '澳得仕 3D 工作室', 1);

CREATE TABLE rfq.rfqs (
  id bigserial PRIMARY KEY,
  customer_id smallint NOT NULL REFERENCES rfq.customers(id),
  rfq_number text NOT NULL,
  item_name text NOT NULL,
  material_text text NOT NULL,
  quantity int NOT NULL CHECK (quantity BETWEEN 1 AND 100000),
  unit text NOT NULL CHECK (unit IN ('pcs', 'sets')),
  need_date date,
  source text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'email')),
  status text NOT NULL DEFAULT 'received' CHECK (status IN ('received', 'quoting', 'quoted', 'closed')),
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (customer_id, rfq_number)
);

CREATE TABLE rfq.quotes (
  id bigserial PRIMARY KEY,
  rfq_id bigint NOT NULL REFERENCES rfq.rfqs(id),
  quote_no text NOT NULL CHECK (quote_no ~ '^AU[0-9]{8}$'),
  quote_revision int NOT NULL DEFAULT 1 CHECK (quote_revision >= 1),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sending', 'sent', 'failed', 'superseded')),
  quote_date date NOT NULL,
  valid_until date NOT NULL,
  currency char(3) NOT NULL DEFAULT 'TWD',
  tax_included boolean NOT NULL DEFAULT false,
  tax_rate numeric(5,4) NOT NULL DEFAULT 0.0500 CHECK (tax_rate >= 0 AND tax_rate < 1),
  lead_basis text NOT NULL DEFAULT 'po' CHECK (lead_basis IN ('po', 'quote')),
  delivery_date date,
  note text NOT NULL DEFAULT '' CHECK (char_length(note) <= 1000),
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (quote_no, quote_revision),
  CHECK (valid_until >= quote_date)
);
CREATE INDEX quotes_rfq_idx ON rfq.quotes (rfq_id);

CREATE TABLE rfq.quote_items (
  id bigserial PRIMARY KEY,
  quote_id bigint NOT NULL REFERENCES rfq.quotes(id),
  line_no int NOT NULL CHECK (line_no >= 1),
  part text NOT NULL,
  material text NOT NULL,
  qty int NOT NULL CHECK (qty BETWEEN 1 AND 100000),
  unit text NOT NULL CHECK (unit IN ('pcs', 'sets')),
  unit_price numeric(12,2) NOT NULL CHECK (unit_price > 0),
  lead_days int NOT NULL CHECK (lead_days BETWEEN 0 AND 365),
  UNIQUE (quote_id, line_no)
);

CREATE TABLE rfq.quote_no_counters (
  day date PRIMARY KEY,
  last_seq int NOT NULL
);

CREATE TABLE rfq.quote_dispatches (
  id bigserial PRIMARY KEY,
  quote_id bigint NOT NULL REFERENCES rfq.quotes(id),
  event_id text NOT NULL UNIQUE,
  target_url text NOT NULL,
  payload jsonb NOT NULL,
  payload_text text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN (
    'pending', 'sending', 'retry_wait', 'accepted', 'duplicate', 'published',
    'rejected', 'not_found', 'conflict', 'gave_up', 'blocked')),
  attempt_count int NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  sending_started_at timestamptz,
  last_http_status int,
  last_error_code text,
  last_response jsonb,
  candidate_id text,
  candidate_revision int,
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX quote_dispatches_quote_idx ON rfq.quote_dispatches (quote_id);
CREATE INDEX quote_dispatches_due_idx ON rfq.quote_dispatches (next_attempt_at)
  WHERE status IN ('pending', 'retry_wait', 'sending');

CREATE TABLE rfq.dispatch_attempts (
  id bigserial PRIMARY KEY,
  dispatch_id bigint NOT NULL REFERENCES rfq.quote_dispatches(id),
  attempt_no int NOT NULL,
  request_id text NOT NULL,
  started_at timestamptz NOT NULL,
  finished_at timestamptz,
  http_status int,
  error text,
  response_text text
);
CREATE INDEX dispatch_attempts_dispatch_idx ON rfq.dispatch_attempts (dispatch_id);

INSERT INTO rfq.schema_migrations (version) VALUES ('001_rfq');
