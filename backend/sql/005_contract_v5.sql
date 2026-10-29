-- 契約 2026-10-29.5：規格版次、測試單、報價對應的規格版次、報價回信
ALTER TABLE rfq.rfqs
  ADD COLUMN IF NOT EXISTS spec_revision int NOT NULL DEFAULT 1 CHECK (spec_revision >= 1),
  ADD COLUMN IF NOT EXISTS is_test boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS spec_changed_at timestamptz;

ALTER TABLE rfq.inbound_messages
  ADD COLUMN IF NOT EXISTS spec_revision int,
  ADD COLUMN IF NOT EXISTS is_test boolean NOT NULL DEFAULT false;

ALTER TABLE rfq.quotes
  ADD COLUMN IF NOT EXISTS rfq_revision int CHECK (rfq_revision IS NULL OR rfq_revision >= 1);
UPDATE rfq.quotes q SET rfq_revision = r.spec_revision FROM rfq.rfqs r WHERE r.id = q.rfq_id AND q.rfq_revision IS NULL;

-- 報價回信（附 PDF）：一份報價版次一筆；mode = live 寄給承辦人、self 寄給自己（開發期）
CREATE TABLE IF NOT EXISTS rfq.quote_mails (
  id bigserial PRIMARY KEY,
  quote_id bigint NOT NULL REFERENCES rfq.quotes(id),
  mode text NOT NULL CHECK (mode IN ('live', 'self')),
  to_addr text NOT NULL,
  subject text NOT NULL,
  thread_id text,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
  gmail_message_id text,
  error text,
  attempt_count int NOT NULL DEFAULT 0,
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz
);
CREATE INDEX IF NOT EXISTS quote_mails_quote_idx ON rfq.quote_mails (quote_id);

-- 假澳得仕：規格版次、測試單
ALTER TABLE mock_partner.rfqs
  ADD COLUMN IF NOT EXISTS spec_revision int NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS is_test boolean NOT NULL DEFAULT false;
ALTER TABLE mock_partner.candidates
  ADD COLUMN IF NOT EXISTS spec_revision int,
  ADD COLUMN IF NOT EXISTS self_test boolean NOT NULL DEFAULT false;

GRANT SELECT, INSERT, UPDATE, DELETE ON rfq.quote_mails TO rfq_app;
GRANT USAGE, SELECT, UPDATE ON SEQUENCE rfq.quote_mails_id_seq TO rfq_app;
ALTER TABLE rfq.quote_mails ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rfq_app_all ON rfq.quote_mails;
CREATE POLICY rfq_app_all ON rfq.quote_mails FOR ALL TO rfq_app USING (true) WITH CHECK (true);

INSERT INTO rfq.schema_migrations (version) VALUES ('005_contract_v5') ON CONFLICT DO NOTHING;
