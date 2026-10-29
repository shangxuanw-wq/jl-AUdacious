-- 收詢價信：連接的信箱、收到的信、詢價單加上信件欄位
CREATE TABLE IF NOT EXISTS rfq.mailboxes (
  id smallserial PRIMARY KEY,
  email text NOT NULL UNIQUE,
  refresh_token_enc text NOT NULL,          -- AES-GCM 加密（金鑰 MAIL_TOKEN_KEY 只在 Vercel）
  connected_by text,
  connected_at timestamptz NOT NULL DEFAULT now(),
  last_poll_at timestamptz,
  last_poll_ok_at timestamptz,
  last_error text
);

CREATE TABLE IF NOT EXISTS rfq.inbound_messages (
  id bigserial PRIMARY KEY,
  mailbox_id smallint NOT NULL REFERENCES rfq.mailboxes(id) ON DELETE CASCADE,
  gmail_id text NOT NULL,
  thread_id text,
  message_id_header text,
  subject text,
  from_addr text,
  reply_to text,
  received_at timestamptz,
  rfq_number text,
  rfq_id bigint REFERENCES rfq.rfqs(id),
  status text NOT NULL CHECK (status IN ('created', 'updated', 'ignored', 'error')),
  error text,
  attachments jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (mailbox_id, gmail_id)
);
CREATE INDEX IF NOT EXISTS inbound_messages_rfq_idx ON rfq.inbound_messages (rfq_id);

ALTER TABLE rfq.rfqs
  ADD COLUMN IF NOT EXISTS project_name text,
  ADD COLUMN IF NOT EXISTS need_date_text text,
  ADD COLUMN IF NOT EXISTS contact_name text,
  ADD COLUMN IF NOT EXISTS contact_email text,
  ADD COLUMN IF NOT EXISTS reply_to text,
  ADD COLUMN IF NOT EXISTS spec_text text,
  ADD COLUMN IF NOT EXISTS last_message_id bigint REFERENCES rfq.inbound_messages(id),
  ADD COLUMN IF NOT EXISTS mail_count int NOT NULL DEFAULT 0;

GRANT SELECT, INSERT, UPDATE, DELETE ON rfq.mailboxes, rfq.inbound_messages TO rfq_app;
GRANT USAGE, SELECT, UPDATE ON SEQUENCE rfq.mailboxes_id_seq, rfq.inbound_messages_id_seq TO rfq_app;

ALTER TABLE rfq.mailboxes ENABLE ROW LEVEL SECURITY;
ALTER TABLE rfq.inbound_messages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rfq_app_all ON rfq.mailboxes;
DROP POLICY IF EXISTS rfq_app_all ON rfq.inbound_messages;
CREATE POLICY rfq_app_all ON rfq.mailboxes FOR ALL TO rfq_app USING (true) WITH CHECK (true);
CREATE POLICY rfq_app_all ON rfq.inbound_messages FOR ALL TO rfq_app USING (true) WITH CHECK (true);

INSERT INTO rfq.schema_migrations (version) VALUES ('004_mail') ON CONFLICT DO NOTHING;
