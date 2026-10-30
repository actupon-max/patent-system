"""命令列：patent-review [選項] 案件資料夾或 .docx ..."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import __version__
from .report import terminal_summary, write_case_xlsx, write_json, write_summary_xlsx
from .runner import check_case, load_rules


def _cases(inputs: list[str], pdf: str | None) -> list[tuple[str, str | None, str]]:
    out = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            docs = sorted(x for x in p.glob("*.docx") if not x.name.startswith("~$"))
            pdfs = sorted(p.glob("*.pdf"))
            if not docs:
                print(f"⚠ {p} 內沒有 .docx，略過", file=sys.stderr)
            for d in docs:
                match = next((x for x in pdfs if x.stem in d.stem or d.stem in x.stem), None)
                use = match or (pdfs[0] if len(pdfs) == 1 else None)
                name = p.name if len(docs) == 1 else f"{p.name}-{d.stem}"
                out.append((str(d), str(use) if use else None, name))
        elif p.suffix.lower() == ".docx":
            out.append((str(p), pdf, p.stem))
        else:
            print(f"⚠ 無法辨識的輸入：{p}", file=sys.stderr)
    return out


def _load_ignore(path: str | None) -> set[str]:
    if not path:
        return set()
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    if isinstance(data, dict):
        data = data.get("ignore", [])
    return {str(x).split()[0] for x in data}


def serve_main(argv: list[str]) -> int:
    from .server import DEFAULT_PORT, DEFAULT_SUPABASE, serve
    ap = argparse.ArgumentParser(prog="patent-review serve",
                                 description="啟動本機服務，讓群淵 GDIP 平台直接呼叫這台電腦上的檢查器")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"連接埠（預設 {DEFAULT_PORT}）")
    ap.add_argument("--allow-origin", action="append", default=[],
                    help="允許呼叫的平台網址，例如 https://gdip.example.com（*.vercel.app 已預設允許）")
    ap.add_argument("--supabase-url", default=DEFAULT_SUPABASE, help="平台檔案庫網址")
    ap.add_argument("-o", "--out", default="~/PatentReview報告", help="Excel 報告存放資料夾")
    ap.add_argument("--rules", help="規則檔路徑")
    a = ap.parse_args(argv)
    serve(a.port, a.supabase_url, a.allow_origin, a.out, a.rules)
    return 0


def gate_main(argv: list[str]) -> int:
    import json
    from .pipeline import record_supabase, run_gate, summary_line
    ap = argparse.ArgumentParser(prog="patent-review gate",
                                 description="patent_pipeline 關卡：檢查案件某階段最新檔，報告寫到 output/_process；"
                                             "結束碼 0=通過、1=必改（block）、2=錯誤")
    ap.add_argument("case_dir", help="案件資料夾（內含 output/）")
    ap.add_argument("--stage", required=True, choices=["claims", "draft", "final"])
    ap.add_argument("--docx", help="指定 Word 檔（預設依 rules.yaml pipeline 樣式找最新版）")
    ap.add_argument("--pdf", help="指定圖式 PDF")
    ap.add_argument("--case", help="案號（預設為資料夾名稱）")
    ap.add_argument("--rules", help="規則檔路徑")
    ap.add_argument("--supabase", action="store_true",
                    help="寫入 Supabase agent_runs／deliverables（讀 SUPABASE_URL、SUPABASE_KEY）")
    ap.add_argument("--json", action="store_true", help="stdout 只輸出 JSON 結果（給平台程式解析）")
    a = ap.parse_args(argv)
    rules = load_rules(a.rules)
    try:
        gate = run_gate(a.case_dir, a.stage, docx=a.docx, pdf=a.pdf, case=a.case, rules=rules)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"gate": "error", "error": str(e)}, ensure_ascii=False) if a.json else f"✗ {e}")
        return 2
    if a.supabase:
        try:
            gate["supabase"] = record_supabase(gate, a.case_dir, rules)
        except Exception as e:  # 紀錄失敗不影響關卡結果
            gate["supabase"] = {"error": str(e)}
    if a.json:
        print(json.dumps(gate, ensure_ascii=False, indent=2))
    else:
        print(summary_line(gate))
        for i in gate["advisory"][:20]:
            print(f"  [{i['severity']}] {i['rule']} {i['location']}：{i['message']}")
        print(f"報告：{gate['reports']['xlsx']}")
    return 1 if gate["gate"] == "block" else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["serve"]:
        return serve_main(argv[1:])
    if argv[:1] == ["gate"]:
        return gate_main(argv[1:])
    ap = argparse.ArgumentParser(prog="patent-review",
                                 description="Patent Review System：台灣發明專利說明書與圖式格式檢查（不修改原檔）",
                                 epilog="平台一鍵檢查：patent-review serve　｜　pipeline 關卡：patent-review gate")
    ap.add_argument("inputs", nargs="+", help="案件資料夾（內含 .docx 與 .pdf）或 .docx 檔")
    ap.add_argument("--pdf", help="單一 .docx 時指定圖式 PDF")
    ap.add_argument("--stage", help="檢查階段：claims（請求項初稿）/ draft（說明書初稿）/ final（送件版）")
    ap.add_argument("--rules", help="規則檔路徑（預設為工具目錄下的 rules.yaml）")
    ap.add_argument("-o", "--out", default="reports", help="報告輸出資料夾（預設 ./reports）")
    ap.add_argument("--ignore", help="已確認非問題的 ID 清單（YAML）")
    ap.add_argument("--llm", action="store_true", help="啟用 E 項 LLM 語意檢查（未公開案件請先確認資料政策）")
    ap.add_argument("--no-json", action="store_true", help="不輸出 JSON（平台上傳用的檢查報告）")
    ap.add_argument("--version", action="version", version=f"Patent Review System {__version__}")
    a = ap.parse_args(argv)

    rules = load_rules(a.rules)
    ignore = _load_ignore(a.ignore)
    out = Path(a.out)
    results = []
    for docx, pdf, name in _cases(a.inputs, a.pdf):
        res = check_case(docx, pdf, rules=rules, stage=a.stage, case=name, use_llm=a.llm, ignore=ignore)
        results.append(res)
        write_case_xlsx(res, out / f"{name}_檢查報告.xlsx")
        if not a.no_json:
            write_json(res, out / f"{name}_{res.stage}_檢查報告.json")
        print(terminal_summary(res))
        print()
    if not results:
        return 2
    if len(results) > 1:
        write_summary_xlsx(results, out / "總表.xlsx")
    print(f"報告已輸出至 {out.resolve()}")
    return 1 if any(r.count("必改") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
