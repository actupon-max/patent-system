# Patent Review System

台灣發明專利說明書（.docx）與圖式（.pdf）格式檢查器。

- **不修改原檔**：只讀取，輸出 Excel 報告。
- **規則全部在 `rules.yaml`**：程式不寫死規格值，委員會調整規則只改設定檔。
- **只報告程式能確定的事**：需要判斷語意的項目標「需人工確認」；LLM 檢查必須附原文引句，引句在原文找不到就丟棄。
- **同一份輸入，每次結果都一樣**：每個問題有穩定 ID，報告記錄工具版本、規則版本和檔案雜湊值。

## 三個檢查階段

| 階段 | 參數 | 適用 | 檢查內容 |
|---|---|---|---|
| 請求項初稿 | `--stage claims` | 只有請求項的 Word 檔（可以沒有任何段落標題） | 編號、一句為之、依附、多項附屬、前置基礎、全半形、用語 |
| 說明書初稿 | `--stage draft` | 說明書＋請求項＋摘要，圖式可有可無 | 上列＋段落結構、段號、摘要字數、說明書支持、符號對照、圖號引用、代表圖 |
| 送件版 | `--stage final`（預設） | 送件前定稿 | 全部，含字型行距、編修殘留、轉檔風險、規費、圖式 PDF |

各階段啟用哪些檢查寫在 `rules.yaml` 的 `stages:`。

## 平台上的送件前檢查

群淵 GDIP 平台的案件詳情頁有「✅ 送件前檢查」區塊，四個步驟：

| 步驟 | 檢查的檔案 | 階段 |
|---|---|---|
| 1 Claim 初稿檢查 | 「Claim」分類最新的 .docx | `claims` |
| 2 完整說明書檢查 | 「完稿」分類最新的 .docx＋最新的 .pdf | `draft` |
| 3 送件前最終檢查 | 同上 | `final` |
| 4 智慧局轉檔人工確認 | 第 3 步通過後，由專利師按鈕確認 | — |

1、2 步做過，3 步針對**最新版檔案**必改為 0，4 步確認後，才顯示「🟢 可送件」。上傳新版本檔案後，舊的檢查結果會標「檔案已更新，需重新檢查」。
檢查紀錄存在 Supabase `patent_checks` 表（先執行專案根目錄的 `supabase_patent_checks.sql`）。
檢查在 Vercel 函式 `/api/patent_check` 執行，檔案只在函式暫存目錄處理，不另外保存；雲端沒有 OCR，點陣圖式的符號比對需人工確認。

## 安裝（Mac）

```bash
cd patent_review_system
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # 需要 LLM 檢查再加：pip install -e ".[llm]"
brew install poppler tesseract tesseract-lang   # pdffonts/pdfimages；OCR 用（選用）
```

## 使用

```bash
# 一個案件資料夾（內含說明書 .docx 與圖式 .pdf）
patent-review ~/Desktop/GDIP/案件/A001

# 多案一起跑，另外產生總表.xlsx
patent-review samples/case1 samples/case2 -o reports

# 請求項初稿
patent-review 請求項初稿.docx --stage claims

# 單一檔案指定圖式
patent-review 說明書.docx --pdf 圖式.pdf

# 已確認不是問題的項目，把 ID 寫進 ignore.yaml（一行一個）後
patent-review samples/case1 --ignore samples/case1/ignore.yaml
```

結束碼：有「必改」時回傳 1，否則 0，可以接批次腳本。

### 報告內容

- **總表**：工具與規則版本、檔案雜湊值、各嚴重度數量、段號來源、摘要字數、請求項數等
- **問題清單**：ID、嚴重度、規則、檔案、位置（【00xx】／請求項n／圖n／第n頁）、描述、實際值、期望值、依據、原文引句、處理狀態欄
- **符號對照表**：符號 × 符號說明名稱 × 內文名稱與位置 × 圖式頁
- **請求項依附**：每項類型與依附關係

嚴重度：`必改`／`建議`／`需人工確認`／`資訊`。

## 規則一覽

| 編號 | 項目 | 編號 | 項目 |
|---|---|---|---|
| A01 | 必備段落、順序、重複 | B01 | 請求項編號連續 |
| A02 | 段號連續、重號、自動編號／純文字 | B02 | 每項一句（一個句號） |
| A03 | 字型、字級、行距、對齊 | B03 | 依附在前、多項附屬擇一、不得依附多項附屬、循環 |
| A04 | 中文語境半形標點 | B04 | 附屬項前言名稱與獨立項一致 |
| A05 | 用語與單位一致（± / 加減、μm / 微米…） | B05 | 前置基礎缺漏、重複以「一」引入 |
| A06 | 摘要 ≤ 250 字 | B06 | 請求項用語在說明書找不到（需人工確認） |
| A07 | 追蹤修訂、註解、螢光、彩色字、隱藏文字、空白段落 | C01–C05 | 符號三方對照 |
| A08 | 轉檔風險（OLE 方程式、文字方塊、功能變數…） | C06 | 圖式簡單說明與 PDF 圖數 |
| A09 | 規費試算（請求項數、頁數） | C07 | 每張圖在實施方式被引用 |
| D01–D09 | 圖式 PDF：A4、方向、旋轉、字型嵌入、文字層、色彩、解析度、字高、圖號 | C08 | 「圖1」／「第1圖」不混用 |
| E01 | 策略性字句（固定字串） | C09 | 代表圖與代表圖符號 |
| E02 | LLM 語意檢查（選用，需人工確認） | | |

## 委員會如何調整規則

1. 改 `rules.yaml`（數值、清單、嚴重度、各階段啟用的群組），並更新最上方的 `rules_version`。
2. 誤報或漏報時，先在 `tests/fixtures/make_samples.py` 加一個能重現的小樣本，再在 `tests/test_synthetic.py` 加一條測試，最後修規則或程式。
3. 執行 `python3 -m pytest`，全部通過才合併。
4. 在 `CHANGELOG.md` 記一筆。新增規則升次版號，修正誤報升修訂號（`patent_review/__init__.py`）。

## 驗收：劉教授兩案

真實案件不進 git。放到 `samples/case1`、`samples/case2` 後執行：

```bash
PATENT_SAMPLES_DIR=samples python3 -m pytest tests/test_real_samples.py -v -s
```

合格門檻寫在 `tests/expected_issues.yaml`：第一案「圖4 未引用」「請求項8 前置基礎重複」、第二案「半形括號」。
把審查意見表其他項目逐條補進 `review_sheet`，測試會印出召回率。

## LLM 語意檢查（E02）

預設關閉。未公開案件送出前，請先確認 API 的資料保留政策。

```bash
export ANTHROPIC_API_KEY=...
patent-review samples/case1 --llm
```

LLM 只檢查錯字、用語不一、數值矛盾、策略性字句。每個問題都必須附原文引句，
程式會回到原文逐字比對（只容許全半形與空白差異），比對不到的直接丟棄，總表會列出採用與丟棄數。

## 限制

- **智慧局實際轉檔模擬不了**：A08 只列出高風險元素，送件前仍須人工跑一次正式轉檔。
- 前置基礎以「符號說明」建立元件詞典；詞典以外的抽象元件（例如「處理單元」）可加進 `rules.yaml` 的 `antecedent.extra_terms`。
- 字型、行距的預設值標為「事務所規格」，請依實際送件規範確認。
- 圖式無文字層時需要 tesseract 才能擷取符號；OCR 結果一律標「需人工確認」。
