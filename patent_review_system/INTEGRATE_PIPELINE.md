請把格式檢查器 Patent Review System 接進這個平台（patent_pipeline，localhost:8787），作為流程中自動執行的檢查關卡。先列出整合計畫給我確認，再動手。

【取得檢查器】
- 若 ~/patent-system 不存在：git clone https://github.com/actupon-max/patent-system.git ~/patent-system
- cd ~/patent-system && git fetch origin && git checkout claude/fervent-gates-vnp2im && git pull
- 用平台目前使用的 Python 環境安裝：pip install -e ~/patent-system/patent_review_system
- 說明見 patent_review_system/README.md「patent_pipeline 自動關卡」；規則與檔名樣式在 rules.yaml（pipeline:），不要寫死在平台程式裡

【呼叫方式】檢查器已提供關卡指令，平台只要呼叫並解析結果：
    patent-review gate <案件資料夾> --stage claims|draft|final --json --supabase
- 案件資料夾 = 含 output/ 的那一層（例：…/GDIP/01_案件/GD-260930-01）
- 結束碼 0 通過、1 必改（block）、2 找不到檔案；stdout 為 JSON（gate、counts、blocking、advisory、reports）
- --supabase 需要環境變數 SUPABASE_URL、SUPABASE_KEY（沿用平台既有的值）；它會寫 agent_runs（stage=format_check）與 deliverables（doc_type=format_check），平台不要再重複寫
- 平台若是 Python，也可直接 from patent_review.pipeline import run_gate

【插入時機】
1. ② 請求項初稿產出後 → --stage claims
2. ③ 整合說明書產出後 → --stage draft
3. 送件前（人工覆核定稿／as_filed 之前）→ --stage final
- 先確認 rules.yaml pipeline.stages 的檔名樣式和平台實際輸出的檔名一致；不一致就改 rules.yaml，或呼叫時加 --docx／--pdf

【併入現有驗證關卡】
- gate=block → 該階段不得通過（同「伺服器獨立驗證未通過」）；advisory 只顯示
- 沿用現有「伺服器獨立驗證」的呈現方式，在 localhost:8787 看得到 blocking／advisory 清單與報告連結
- 不得修改任何交付物本身

【驗收】
- 在 ~/patent-system/patent_review_system 執行 python3 -m pytest，全部通過
- 拿 GD-260930-01 與劉教授兩案實際跑一次：第一案須抓到「圖4 未引用」「請求項8 前置基礎重複」，第二案須抓到「半形括號」
- 回報每案抓到的問題、誤報，以及需要調整 rules.yaml 的地方
