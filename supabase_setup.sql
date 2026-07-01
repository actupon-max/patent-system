-- ══════════════════════════════════════════════════════════
-- 智權技術顧問 — 專利申請管理系統
-- Supabase 資料庫初始化腳本
-- 在 Supabase Dashboard → SQL Editor 執行此腳本
-- ══════════════════════════════════════════════════════════

-- 1. 使用者帳號表
create table if not exists patent_users (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  email       text not null unique,
  password    text not null,
  role        text not null default 'attorney' check (role in ('admin','attorney','viewer')),
  active      boolean not null default true,
  created_at  timestamptz default now()
);

-- 2. 專利案件表
create table if not exists patents (
  id           uuid primary key default gen_random_uuid(),
  case_no      text,
  name         text not null,
  type         text not null default '新型' check (type in ('新型','發明')),
  client       text not null,
  app_date     date,
  approve_date date,
  tech_desc    text,
  claim_desc   text,
  status       text not null default '申請中'
               check (status in ('申請中','實體審查中','已核准','維護中','已到期','已放棄')),
  service_fee  numeric default 0,
  app_fee      numeric default 0,
  other_cost   numeric default 0,
  maint_date   date,
  maint_fee    numeric default 0,
  maint_note   text,
  created_at   timestamptz default now(),
  updated_at   timestamptz default now()
);

-- 3. updated_at 自動更新觸發器
create or replace function update_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists patents_updated_at on patents;
create trigger patents_updated_at
  before update on patents
  for each row execute function update_updated_at();

-- 4. RLS（Row Level Security）設定
--    此系統使用 anon key + 應用層驗證，開放 REST API 讀寫
alter table patent_users enable row level security;
alter table patents       enable row level security;

-- 開放 anon key 的 CRUD（應用層自行控制權限）
create policy "anon_all_users"   on patent_users for all using (true) with check (true);
create policy "anon_all_patents" on patents       for all using (true) with check (true);

-- 5. 預設管理員帳號
--    密碼: admin1234（SHA-256 雜湊，請登入後立即修改）
insert into patent_users (name, email, password, role, active)
values ('系統管理員', 'admin@ipfirm.com',
        'sha256:ac9689e2272427085e35b9d3e3e8bed88cb3434828b43b86fc0596cad4c6e270',
        'admin', true)
on conflict (email) do nothing;

-- 若已存在舊明文密碼帳號，執行下方語句強制升級：
-- update patent_users
-- set password = 'sha256:ac9689e2272427085e35b9d3e3e8bed88cb3434828b43b86fc0596cad4c6e270'
-- where email = 'admin@ipfirm.com' and password not like 'sha256:%';

-- 6. 範例資料（選擇性執行）
insert into patents (case_no, name, type, client, app_date, approve_date, tech_desc, claim_desc, status, service_fee, app_fee, other_cost, maint_date, maint_fee, maint_note)
values
  ('PAT-2024-001', '高效散熱結構', '新型', '台達電子',
   '2024-03-15', '2024-09-20',
   '一種應用於功率模組之散熱鰭片結構，具備交錯排列設計以提升氣流效率，可降低熱阻30%。',
   '獨立項1：一種散熱結構，包含基板及複數個鰭片，其特徵在於鰭片以交錯方式排列。',
   '維護中', 45000, 3200, 2000, '2025-03-15', 3200, '第2年年費'),

  ('PAT-2024-002', '垂直共振腔面射型雷射封裝模組', '發明', 'Epistar',
   '2024-06-01', NULL,
   'VCSEL陣列封裝技術，含主動冷卻與波長穩定控制機制，應用於光通訊高速傳輸，目標速率400G以上。',
   '獨立項1：一種VCSEL封裝模組，包含雷射陣列、驅動電路與溫控單元，其特徵在於溫控單元採用TEC主動控溫。',
   '申請中', 80000, 7500, 5000, NULL, 0, NULL),

  ('PAT-2023-003', '微型LED驅動電路', '發明', '友達光電',
   '2023-11-10', '2024-08-05',
   'MicroLED背板驅動電路架構，採用薄膜電晶體主動矩陣控制，降低功耗30%，適用於AR/VR顯示器。',
   '獨立項1：一種MicroLED驅動電路，其特徵在於採用電流補償機制，含補償電晶體及儲存電容。',
   '維護中', 90000, 7500, 8000, '2025-11-10', 7500, '第2年年費，需提早60天繳納')

on conflict do nothing;

-- 完成訊息
select '✅ 資料庫初始化完成' as message,
       (select count(*) from patent_users) as users,
       (select count(*) from patents) as patents;
