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

## 整合進 patent_pipeline

檢查器接在 `patent_pipeline`（localhost:8787）的流程中自動執行，整合方式見 `INTEGRATE_PIPELINE.md`：

| 時機 | 檢查的檔案 | 階段 |
|---|---|---|
| ② 請求項初稿產出後 | 請求項 docx | `claims` |
| ③ 整合說明書產出後 | 說明書 docx＋圖式 PDF | `draft` |
| 送件前 | 定稿 docx＋正式圖式 | `final` |

「必改」併入流程驗證的 block，「建議」「需人工確認」為 advisory。各階段產出後呼叫一行指令：

```bash
patent-review gate <案件資料夾> --stage claims --json --supabase   # ② 請求項初稿產出後
patent-review gate <案件資料夾> --stage draft  --json --supabase   # ③ 整合說明書產出後
patent-review gate <案件資料夾> --stage final  --json --supabase   # 人工覆核定稿／as_filed 之前
```

| 項目 | 內容 |
|---|---|
| 讀哪個檔 | `rules.yaml` 的 `pipeline.stages` 樣式，在 `output/`、`output/_versions/` 取最高 `_vN`；可用 `--docx`、`--pdf` 指定 |
| 結果 | stdout JSON：`gate`（pass／block／error）、`counts`、`blocking`（必改）、`advisory`（建議、需人工確認）、`reports` |
| 結束碼 | 0 通過、1 有必改（該階段不得通過）、2 找不到檔案或參數錯誤 |
| 報告 | `output/_process/format_check_<階段>_v<N>.xlsx／.json`，加上 `format_check_<階段>_latest.json` |
| Supabase | `--supabase` 讀環境變數 `SUPABASE_URL`、`SUPABASE_KEY`：`agent_runs` 一筆（stage=`format_check`，通過 done／未過 failed，summary 寫各嚴重度數量），`deliverables` 一筆（doc_type=`format_check`） |

交付物只讀不改。block 的嚴重度在 `pipeline.block_on` 調整。

Python 直接呼叫：

```python
from patent_review.pipeline import run_gate, record_supabase
gate = run_gate(case_dir, "draft")      # gate["gate"] == "block" 時擋下
```

## 版本

- 程式版本：`patent_review/__init__.py`（`patent-review --version`）；規則版本：`rules.yaml` 的 `rules_version`
- 變更紀錄：`CHANGELOG.md`；GitHub 標記 `patent-review-v<版號>` 可取回舊版
- 發布新版時：改 `__init__.py` 版號 → 在 `CHANGELOG.md` 加一節 → 打 tag `patent-review-v<版號>`

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

# 每次都會輸出 Excel 報告與平台上傳用的 JSON 報告（reports/<案件>_<階段>_檢查報告.json）

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
