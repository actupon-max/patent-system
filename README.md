# 智權技術顧問 — 專利申請管理系統
## 部署指南（GitHub + Supabase + Vercel）

---

## 步驟一：Supabase 建立資料庫

1. 前往 https://supabase.com → 登入 → New Project
2. 輸入專案名稱（例：`patent-system`），選擇資料中心（建議 **Southeast Asia - Singapore**）
3. 等待專案啟動（約1~2分鐘）
4. 前往 **SQL Editor**，貼上 `supabase_setup.sql` 內容並執行
5. 確認輸出訊息為 `✅ 資料庫初始化完成`
6. 前往 **Settings → API**，複製：
   - **Project URL**（例：`https://abcxyz.supabase.co`）
   - **anon public key**（長字串）

---

## 步驟二：填入 index.html 的 Supabase 設定

開啟 `index.html`，找到第 20-21 行：

```javascript
const SB_URL = "https://YOUR_PROJECT.supabase.co";  // ← 替換
const SB_KEY = "YOUR_ANON_KEY";                      // ← 替換
```

填入你的 Supabase URL 和 anon key。

---

## 步驟三：GitHub 建立 Repository

```bash
# 在本機終端機執行
git init
git add .
git commit -m "init: patent management system"

# 在 GitHub 建立新 repo，然後：
git remote add origin https://github.com/YOUR_USERNAME/patent-system.git
git branch -M main
git push -u origin main
```

或直接在 GitHub 網頁上傳 `index.html` 和 `vercel.json` 兩個檔案。

---

## 步驟四：Vercel 部署

1. 前往 https://vercel.com → 登入 → **New Project**
2. 點選 **Import Git Repository** → 選擇你的 GitHub repo
3. Framework Preset 選 **Other**（無需 Build Command）
4. 點擊 **Deploy**（30秒內完成）
5. 部署完成後取得網址（例：`https://patent-system.vercel.app`）

---

## 步驟五：首次登入

| 欄位 | 值 |
|------|-----|
| 信箱 | `admin@ipfirm.com` |
| 密碼 | `admin1234` |

⚠️ **登入後請立即前往「帳號管理」修改密碼！**

---

## 帳號角色說明

| 角色 | 權限 |
|------|------|
| **管理員** (admin) | 全部功能，含帳號管理 |
| **專利師** (attorney) | 新增/編輯案件、查看分析，不含帳號管理 |
| **觀察者** (viewer) | 僅能查看，無法新增或修改 |

---

## 資料庫表格結構

### `patent_users`（帳號）
| 欄位 | 類型 | 說明 |
|------|------|------|
| id | uuid | 主鍵 |
| name | text | 姓名 |
| email | text | 信箱（唯一） |
| password | text | 密碼 |
| role | text | admin / attorney / viewer |
| active | boolean | 帳號是否啟用 |

### `patents`（專利案件）
| 欄位 | 類型 | 說明 |
|------|------|------|
| id | uuid | 主鍵 |
| case_no | text | 案件編號 |
| name | text | 案件名稱 |
| type | text | 新型 / 發明 |
| client | text | 客戶名稱 |
| app_date | date | 申請日期 |
| approve_date | date | 核准日期 |
| tech_desc | text | 技術內容描述 |
| claim_desc | text | Claim 描述 |
| status | text | 申請中/實體審查中/已核准/維護中/已到期/已放棄 |
| service_fee | numeric | 服務費 |
| app_fee | numeric | 申請規費 |
| other_cost | numeric | 其他成本 |
| maint_date | date | 下次維護費繳納日 |
| maint_fee | numeric | 維護費用 |
| maint_note | text | 維護備註 |

---

## 更新流程（日後修改）

```bash
# 修改 index.html 後
git add index.html
git commit -m "update: 新增功能說明"
git push
```

Vercel 會自動偵測 GitHub 推送並重新部署（約30秒）。

---

## 檔案清單

```
patent-system/
├── index.html          ← 主系統（全功能單一檔案）
├── vercel.json         ← Vercel 路由設定
├── supabase_setup.sql  ← 資料庫初始化腳本
└── README.md           ← 本部署指南
```

---

## 安全性：密碼雜湊（SHA-256）

本系統使用瀏覽器原生 **Web Crypto API** 對密碼進行 SHA-256 雜湊，無需任何外部套件：

- 新增帳號時，密碼自動雜湊後才寫入 Supabase（格式：`sha256:<hex>`）
- 登入時，輸入密碼在前端雜湊後比對，伺服器端永遠不儲存明文
- **舊明文密碼自動升級**：若資料庫仍有明文密碼，首次登入成功後自動升級為雜湊格式
- 預設管理員密碼 `admin1234` 在 SQL 腳本中已預先雜湊

> ⚠️ SHA-256 適合內部系統快速部署。若需更高安全等級，建議升級為 Supabase Edge Function + bcrypt。

---

## 防止 Supabase 自動休眠（GitHub Actions Cron）

Supabase 免費方案超過 7 天未活動會自動暫停。本專案已加入 `.github/workflows/keep-alive.yml`，每天 **台灣時間 08:00** 自動 ping 一次資料庫。

### 設定 GitHub Secrets

進入 GitHub repo → **Settings → Secrets and variables → Actions** → 新增：

| Secret 名稱 | 值 |
|-------------|-----|
| `SUPABASE_URL` | 你的 Project URL（例：`https://abcxyz.supabase.co`）|
| `SUPABASE_ANON_KEY` | 你的 anon public key |

設定完成後，Actions 每天自動執行，可在 **Actions** 分頁查看紀錄，也可手動點 **Run workflow** 測試。
