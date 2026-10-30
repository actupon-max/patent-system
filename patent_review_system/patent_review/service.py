"""給平台（Vercel API）呼叫的介面：輸入檔案位元組，回傳 JSON 可序列化的結果。"""
from __future__ import annotations

import base64
import io
import tempfile
from pathlib import Path

from .report import write_case_xlsx
from .runner import check_case, load_rules


def run_check_bytes(docx: bytes, pdf: bytes | None = None, *, stage: str | None = None, case: str = "案件",
                    docx_name: str = "說明書.docx", pdf_name: str = "圖式.pdf", ignore: set[str] | None = None,
                    with_xlsx: bool = True) -> dict:
    rules = load_rules()
    with tempfile.TemporaryDirectory() as td:
        dp = Path(td) / Path(docx_name).name
        dp.write_bytes(docx)
        pp = None
        if pdf:
            pp = Path(td) / Path(pdf_name).name
            pp.write_bytes(pdf)
        res = check_case(str(dp), str(pp) if pp else None, rules=rules, stage=stage, case=case, ignore=ignore)

    out = {
        "case": res.case,
        "meta": {k: ("" if v is None else str(v)) for k, v in res.meta.items()},
        "counts": {s: res.count(s) for s in ("必改", "建議", "需人工確認", "資訊")},
        "issues": [i.to_dict() for i in res.sorted_issues()],
        "tables": res.tables,
    }
    if with_xlsx:
        buf = io.BytesIO()
        write_case_xlsx(res, buf)
        out["xlsx_b64"] = base64.b64encode(buf.getvalue()).decode("ascii")
    return out
