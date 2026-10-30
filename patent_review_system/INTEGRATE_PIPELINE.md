請把格式檢查器 Patent Review System 整合進這個平台（patent_pipeline，localhost:8787），作為流程中自動執行的檢查關卡。先列出整合計畫給我確認，再動手。

【取得檢查器】
- 若 ~/patent-system 不存在：git clone https://github.com/actupon-max/patent-system.git ~/patent-system
- cd ~/patent-system && git fetch origin && git checkout claude/taiwan-patent-format-checker-95m5i4 && git pull
- 用平台目前使用的 Python 環境安裝：pip install -e ~/patent-system/patent_review_system
- 說明見 patent_review_system/README.md；規則在 rules.yaml，不要把規則數值寫死在平台程式裡

【呼叫方式（Python）】
    from patent_review.runner import check_case, load_rules
    from patent_review.report import write_case_xlsx, write_json
    res = check_case(docx路徑, pdf路徑或None, stage="claims" | "draft" | "final", case=案號)
    res.count("必改"), res.count("建議"), res.count("需人工確認")
    res.sorted_issues()  # 每項有 rule、location、message、actual、expected、severity、basis、quote、id

【插入時機】
1. ② 請求項初稿產出後 → stage="claims"，檢查請求項 docx
2. ③ 整合說明書產出後 → stage="draft"，檢查說明書 docx＋圖式 PDF（有的話）
3. 送件前（人工覆核定稿／as_filed 之前）→ stage="final"

【併入現有驗證關卡】
- 必改 → block（該階段不得通過）；建議、需人工確認 → advisory
- 沿用現有「伺服器獨立驗證」的呈現方式，在 localhost:8787 看得到結果

【紀錄】
- Excel 與 JSON 報告存到案件 output/_process/，檔名含階段與版本
- Supabase：agent_runs 新增 stage='format_check'（summary 寫各嚴重度數量）；deliverables 新增 doc_type='format_check'
- 不得修改任何交付物本身

【驗收】
- 在 ~/patent-system/patent_review_system 執行 python3 -m pytest，全部通過
- 拿 GD-260930-01 與劉教授兩案實際跑一次：第一案須抓到「圖4 未引用」「請求項8 前置基礎重複」，第二案須抓到「半形括號」
- 回報每案抓到的問題、誤報，以及需要調整 rules.yaml 的地方
