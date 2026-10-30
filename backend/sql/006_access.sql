-- 權限與白名單：一筆規則 = 一個 email 或一整個網域，對應一個角色
--   admin  管理員：全部功能＋管理成員＋信箱設定
--   member 成員：建立／送出報價、回信、收信
--   viewer 唯讀：只能看、下載附件
-- 同一個人同時符合 email 規則和網域規則時，以 email 規則為準（email 規則停用 = 擋下這個人）。
-- 環境變數 ALLOWED_EMAILS 裡的帳號永遠是管理員（避免把自己鎖在門外）。
CREATE TABLE IF NOT EXISTS rfq.access_rules (
  id bigserial PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('email', 'domain')),
  value text NOT NULL CHECK (value = lower(value) AND length(value) BETWEEN 3 AND 254),
  role text NOT NULL CHECK (role IN ('admin', 'member', 'viewer')),
  active boolean NOT NULL DEFAULT true,
  note text NOT NULL DEFAULT '' CHECK (length(note) <= 200),
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (kind, value)
);

-- 實際登入過的人（看得到誰靠「整個網域」規則進來）
CREATE TABLE IF NOT EXISTS rfq.user_logins (
  email text PRIMARY KEY CHECK (email = lower(email)),
  name text NOT NULL DEFAULT '',
  role text NOT NULL,
  via text NOT NULL,
  first_login_at timestamptz NOT NULL DEFAULT now(),
  last_login_at timestamptz NOT NULL DEFAULT now(),
  login_count int NOT NULL DEFAULT 1
);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rfq_app') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON rfq.access_rules, rfq.user_logins TO rfq_app;
    GRANT USAGE, SELECT, UPDATE ON SEQUENCE rfq.access_rules_id_seq TO rfq_app;
    ALTER TABLE rfq.access_rules ENABLE ROW LEVEL SECURITY;
    ALTER TABLE rfq.user_logins ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS rfq_app_all ON rfq.access_rules;
    CREATE POLICY rfq_app_all ON rfq.access_rules FOR ALL TO rfq_app USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS rfq_app_all ON rfq.user_logins;
    CREATE POLICY rfq_app_all ON rfq.user_logins FOR ALL TO rfq_app USING (true) WITH CHECK (true);
  END IF;
END $$;

INSERT INTO rfq.schema_migrations (version) VALUES ('006_access') ON CONFLICT DO NOTHING;
