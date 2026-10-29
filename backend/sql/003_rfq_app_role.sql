-- 估價模組專用連線帳號＋RLS（2026-10-29 已在 Supabase 執行；密碼不寫在這裡）
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rfq_app') THEN
    CREATE ROLE rfq_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END $$;
-- ALTER ROLE rfq_app LOGIN PASSWORD '<只在 Vercel 的 RFQ_DATABASE_URL 裡>';

GRANT USAGE ON SCHEMA rfq, mock_partner TO rfq_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA rfq, mock_partner TO rfq_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA rfq, mock_partner TO rfq_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA rfq, mock_partner GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rfq_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA rfq, mock_partner GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO rfq_app;

DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT schemaname, tablename FROM pg_tables WHERE schemaname IN ('rfq', 'mock_partner') LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.schemaname, t.tablename);
    EXECUTE format('DROP POLICY IF EXISTS rfq_app_all ON %I.%I', t.schemaname, t.tablename);
    EXECUTE format('CREATE POLICY rfq_app_all ON %I.%I FOR ALL TO rfq_app USING (true) WITH CHECK (true)', t.schemaname, t.tablename);
  END LOOP;
END $$;
