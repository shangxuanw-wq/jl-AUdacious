-- 假澳得仕報價 API 的狀態（開發用，跟 rfq 正式資料分開）
CREATE SCHEMA IF NOT EXISTS mock_partner;

CREATE TABLE mock_partner.rfqs (
  number text PRIMARY KEY CHECK (number ~ '^AUD-RFQ-[0-9]{4}-[0-9]{4,}$'),
  status text NOT NULL DEFAULT 'sent' CHECK (status IN ('requested', 'preparing', 'sent', 'quoted', 'closed', 'cancelled')),
  send_pending boolean NOT NULL DEFAULT false,
  snapshot boolean NOT NULL DEFAULT true,
  quantity int NOT NULL DEFAULT 1,
  unit text NOT NULL DEFAULT '件' CHECK (unit IN ('件', '套')),
  item_name text,
  material_text text,
  published_candidate_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mock_partner.candidates (
  id uuid PRIMARY KEY,
  rfq_number text NOT NULL REFERENCES mock_partner.rfqs(number) ON DELETE CASCADE,
  revision int NOT NULL,
  status text NOT NULL CHECK (status IN ('pending', 'published', 'superseded', 'rejected')),
  event_id text,
  quote_revision text,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  parsed jsonb NOT NULL,
  issues jsonb NOT NULL,
  request_id text NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (rfq_number, revision)
);
CREATE UNIQUE INDEX candidates_event_uidx ON mock_partner.candidates (rfq_number, event_id) WHERE event_id IS NOT NULL;

CREATE TABLE mock_partner.faults (
  id bigserial PRIMARY KEY,
  spec jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mock_partner.request_log (
  id bigserial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  request_id text NOT NULL,
  status int NOT NULL,
  rfq text,
  event_id text,
  body text,
  response jsonb,
  fault jsonb
);

INSERT INTO mock_partner.rfqs (number, status, send_pending, snapshot, quantity, unit, item_name, material_text) VALUES
  ('AUD-RFQ-2026-0099', 'sent', false, true, 1, '件', '工件 AUD-RFQ-2026-0099-1', 'PLA'),
  ('AUD-RFQ-2026-0098', 'closed', false, true, 1, '件', '工件 AUD-RFQ-2026-0098-1', 'PLA'),
  ('AUD-RFQ-2026-0097', 'preparing', true, true, 1, '件', '工件 AUD-RFQ-2026-0097-1', 'PLA'),
  ('AUD-RFQ-2026-0096', 'preparing', false, true, 1, '件', '工件 AUD-RFQ-2026-0096-1', 'PLA'),
  ('AUD-RFQ-2026-0095', 'sent', false, false, 1, '件', '工件 AUD-RFQ-2026-0095-1', 'PLA'),
  ('AUD-RFQ-2026-0094', 'sent', false, true, 10, '套', '工件 AUD-RFQ-2026-0094-1', '鋁 6061');

INSERT INTO rfq.schema_migrations (version) VALUES ('002_mock_partner');
