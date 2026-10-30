"""輸出：每案 Excel 報告、多案總表、終端摘要、JSON。"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .model import SEVERITY_ORDER, Result

FILL = {"必改": "F8CBAD", "建議": "FFE699", "需人工確認": "BDD7EE", "資訊": "E2EFDA"}
HEAD = PatternFill("solid", fgColor="D9D9D9")
COLUMNS = ["ID", "嚴重度", "規則", "檔案", "位置", "問題描述", "實際值", "期望值", "依據", "原文引句", "處理狀態", "備註"]
WIDTHS = [12, 10, 7, 10, 18, 40, 36, 30, 30, 30, 10, 20]


def _sheet(ws, header, rows, widths=None):
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = HEAD
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths or [18] * len(header), start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")


def write_case_xlsx(res: Result, path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "總表"
    ws.append(["案件", res.case])
    for k, v in res.meta.items():
        ws.append([k, "" if v is None else str(v)])
    ws.append([])
    ws.append(["嚴重度", "數量"])
    for s in SEVERITY_ORDER:
        ws.append([s, res.count(s)])
    ws.append([])
    ws.append(["規則", "數量"])
    for rule, n in sorted(Counter(i.rule for i in res.issues).items()):
        ws.append([rule, n])
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 60

    ws = wb.create_sheet("問題清單")
    _sheet(ws, COLUMNS, [[i.id, i.severity, i.rule, i.file, i.location, i.message, i.actual, i.expected,
                          i.basis, i.quote, "", ""] for i in res.sorted_issues()], WIDTHS)
    for row in ws.iter_rows(min_row=2):
        color = FILL.get(row[1].value)
        if color:
            row[1].fill = PatternFill("solid", fgColor=color)
    ws.auto_filter.ref = ws.dimensions

    for name, rows in res.tables.items():
        if not rows:
            continue
        t = wb.create_sheet(name[:31])
        header = list(rows[0].keys())
        _sheet(t, header, [[r.get(h, "") for h in header] for r in rows])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_summary_xlsx(results: list[Result], path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "總表"
    header = ["案件", "檢查階段", *SEVERITY_ORDER.keys(), "合計", "規則版本", "工具版本"]
    _sheet(ws, header, [[r.case, r.meta.get("檢查階段", ""), *[r.count(s) for s in SEVERITY_ORDER],
                         len(r.issues), r.meta.get("規則版本", ""), r.meta.get("工具版本", "")] for r in results],
           [24, 16, 8, 8, 12, 8, 8, 14, 28])
    ws2 = wb.create_sheet("全部問題")
    _sheet(ws2, ["案件", *COLUMNS], [[r.case, i.id, i.severity, i.rule, i.file, i.location, i.message, i.actual,
                                     i.expected, i.basis, i.quote, "", ""]
                                    for r in results for i in r.sorted_issues()], [16, *WIDTHS])
    ws2.auto_filter.ref = ws2.dimensions
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_json(res: Result, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"case": res.case, "meta": res.meta, "issues": [i.to_dict() for i in res.sorted_issues()],
                                "tables": res.tables}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def terminal_summary(res: Result, limit: int = 40) -> str:
    lines = [f"═══ {res.case} ═══"]
    for k in ("檢查階段", "規則版本", "說明書", "圖式"):
        if k in res.meta:
            lines.append(f"  {k}：{res.meta[k]}")
    lines.append("  " + "　".join(f"{s} {res.count(s)}" for s in SEVERITY_ORDER))
    shown = 0
    for i in res.sorted_issues():
        if i.severity == "資訊":
            continue
        if shown >= limit:
            lines.append(f"  …其餘 {len(res.issues) - shown} 項請見 Excel 報告")
            break
        extra = f"｜實際：{i.actual}" if i.actual else ""
        lines.append(f"  [{i.severity}] {i.rule} {i.location}：{i.message}{extra}")
        shown += 1
    return "\n".join(lines)
