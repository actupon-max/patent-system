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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="patent-review",
                                 description="Patent Review System：台灣發明專利說明書與圖式格式檢查（不修改原檔）")
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
