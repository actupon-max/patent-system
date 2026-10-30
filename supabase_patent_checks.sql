-- ══════════════════════════════════════════════════════════
-- 群淵 GDIP — 送件前檢查紀錄（Patent Review System）
-- 在 Supabase Dashboard → SQL Editor 執行一次
-- ══════════════════════════════════════════════════════════

create table if not exists patent_checks (
  id              uuid primary key default gen_random_uuid(),
  patent_id       uuid not null references patents(id) on delete cascade,
  -- claims：Claim 初稿檢查 / draft：說明書初稿 / final：完稿檢查 / tipo_conversion：智慧局轉檔人工確認
  stage           text not null check (stage in ('claims','draft','final','tipo_conversion')),
  docx_file_id    uuid,
  pdf_file_id     uuid,
  docx_name       text,
  pdf_name        text,
  must_fix        int  not null default 0,   -- 必改
  suggest         int  not null default 0,   -- 建議
  manual          int  not null default 0,   -- 需人工確認
  issues          jsonb,                     -- 問題清單
  meta            jsonb,                     -- 工具版本、規則版本、檔案雜湊等
  tool_version    text,
  rules_version   text,
  note            text,
  checked_by      text,
  checked_at      timestamptz not null default now()
);

create index if not exists patent_checks_patent_idx on patent_checks (patent_id, checked_at desc);

alter table patent_checks enable row level security;
-- 與其他資料表一致：anon key + 應用層權限控制
drop policy if exists "anon_all_patent_checks" on patent_checks;
create policy "anon_all_patent_checks" on patent_checks for all using (true) with check (true);

select '✅ patent_checks 建立完成' as message;
