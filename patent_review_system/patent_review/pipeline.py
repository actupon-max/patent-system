"""patent_pipeline 關卡：找出階段最新檔 → 檢查 → 報告寫到 output/_process → 回傳 block/pass。

只讀取交付物，不修改；報告與紀錄是唯一寫出的東西。
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .model import SEVERITY_ORDER
from .report import write_case_xlsx, write_json
from .runner import check_case, load_rules

VERSION_RE = re.compile(r"_v(\d+)")


def file_version(path: Path) -> int:
    """檔名最後一個 _vN 的 N（例：③ 整合說明書 (完稿)_v12.docx → 12）；沒有則為 0。"""
    found = VERSION_RE.findall(path.stem)
    return int(found[-1]) if found else 0


def find_latest(case_dir: Path, patterns: list[str], search_dirs: list[str]) -> Path | None:
    """依序試每個樣式；第一個有檔案的樣式取版本最高者（同版取修改時間最新）。"""
    for pat in patterns:
        hits = [p for d in search_dirs for p in (case_dir / d).glob(pat)
                if p.is_file() and not p.name.startswith("~$")]
        if hits:
            return max(hits, key=lambda p: (file_version(p), p.stat().st_mtime))
    return None


def run_gate(case_dir: str, stage: str, *, docx: str | None = None, pdf: str | None = None,
             case: str | None = None, rules: dict | None = None, rules_path: str | None = None) -> dict:
    rules = rules or load_rules(rules_path)
    cfg = rules["pipeline"]
    if stage not in cfg["stages"]:
        raise ValueError(f"未知的階段：{stage}（可用：{', '.join(cfg['stages'])}）")
    root = Path(case_dir).expanduser().resolve()
    case = case or root.name
    scfg = cfg["stages"][stage]
    dirs = cfg["search_dirs"]

    docx_p = Path(docx) if docx else find_latest(root, scfg["docx"], dirs)
    if not docx_p or not docx_p.is_file():
        raise FileNotFoundError(f"{case}：找不到 {stage} 階段的 Word 檔（樣式：{'、'.join(scfg['docx'])}）")
    pdf_p = Path(pdf) if pdf else (find_latest(root, scfg["pdf"], dirs) if scfg.get("pdf") else None)

    started = datetime.now(timezone.utc)
    res = check_case(str(docx_p), str(pdf_p) if pdf_p else None, rules=rules, stage=stage, case=case)
    ver = file_version(docx_p)
    out = root / cfg["report_dir"]
    base = f"format_check_{stage}_v{ver}"
    xlsx, js = out / f"{base}.xlsx", out / f"{base}.json"
    write_case_xlsx(res, xlsx)
    write_json(res, js)

    block_on = set(cfg["block_on"])
    issues = [i.to_dict() for i in res.sorted_issues() if i.severity != "資訊"]
    gate = {
        "gate": "block" if any(i["severity"] in block_on for i in issues) else "pass",
        "case": case,
        "stage": stage,
        "stage_label": rules["stages"][stage]["label"],
        "docx": str(docx_p),
        "docx_version": ver,
        "pdf": str(pdf_p) if pdf_p else None,
        "counts": {s: res.count(s) for s in SEVERITY_ORDER},
        "blocking": [i for i in issues if i["severity"] in block_on],
        "advisory": [i for i in issues if i["severity"] not in block_on],
        "reports": {"xlsx": str(xlsx), "json": str(js)},
        "tool_version": res.tool_version,
        "rules_version": res.rules_version,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (out / f"format_check_{stage}_latest.json").write_text(
        json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    return gate


def summary_line(gate: dict) -> str:
    c = gate["counts"]
    head = "格式檢查通過" if gate["gate"] == "pass" else "格式檢查未通過"
    line = (f"{head}｜{gate['stage_label']}（{gate['stage']}）v{gate['docx_version']}｜"
            f"必改 {c['必改']}　建議 {c['建議']}　需人工確認 {c['需人工確認']}")
    if gate["blocking"]:
        line += "｜" + "；".join(f"{i['rule']} {i['location']}：{i['message']}" for i in gate["blocking"][:5])
    return line


# ── Supabase 紀錄（agent_runs + deliverables）──
def _rest(url: str, key: str, method: str, path: str, body=None) -> list:
    req = urllib.request.Request(
        f"{url.rstrip('/')}/rest/v1/{path}", method=method,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "Prefer": "return=representation"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return json.loads(data) if data else []


def record_supabase(gate: dict, case_dir: str, rules: dict, url: str | None = None, key: str | None = None) -> dict:
    url = url or os.environ.get("SUPABASE_URL")
    key = key or os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("缺少 SUPABASE_URL／SUPABASE_KEY（或 SUPABASE_ANON_KEY）")
    sb = rules["pipeline"]["supabase"]
    q = urllib.parse.quote
    rows = _rest(url, key, "GET", f"cases?select=id&case_no=eq.{q(gate['case'])}")
    if not rows:
        raise RuntimeError(f"Supabase cases 找不到案號 {gate['case']}")
    case_id = rows[0]["id"]
    root = Path(case_dir).expanduser().resolve()
    rel = os.path.relpath(gate["reports"]["xlsx"], root / "output")
    summary = summary_line(gate)
    run = _rest(url, key, "POST", "agent_runs", {
        "case_id": case_id, "stage": sb["run_stage"],
        "status": "done" if gate["gate"] == "pass" else "failed",
        "output_path": gate["reports"]["xlsx"], "summary": summary,
        "started_at": gate["started_at"], "finished_at": gate["finished_at"]})
    prev = _rest(url, key, "GET", f"deliverables?select=version&case_id=eq.{case_id}"
                                  f"&doc_type=eq.{q(sb['doc_type'])}&order=version.desc&limit=1")
    deliv = _rest(url, key, "POST", "deliverables", {
        "case_id": case_id, "doc_type": sb["doc_type"],
        "doc_label": f"格式檢查報告（{gate['stage_label']}）",
        "version": (prev[0]["version"] + 1) if prev else 1,
        "docx_path": rel, "remark": summary, "created_by": "patent-review"})
    return {"agent_run_id": run[0]["id"] if run else None, "deliverable_id": deliv[0]["id"] if deliv else None}
