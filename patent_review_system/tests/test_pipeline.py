"""patent-review gate：找最新版、block/pass、報告位置、不改交付物。"""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from patent_review import pipeline
from patent_review.cli import main


def _case(tmp_path, samples, name, files):
    root = tmp_path / "GD-261030-01"
    for rel, src in files.items():
        dst = root / "output" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(next((samples / src[0]).glob(src[1])), dst)
    return root


def test_finds_highest_version_and_blocks(tmp_path, samples):
    root = _case(tmp_path, samples, "case1_like", {
        "③ 整合說明書 (完稿)_v2.docx": ("clean", "*.docx"),
        "_versions/③ 整合說明書 (完稿)_v10.docx": ("case1_like", "*.docx"),
        "正式圖式_v1.pdf": ("case1_like", "*.pdf"),
    })
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "output").rglob("*.*")}
    gate = pipeline.run_gate(str(root), "draft")
    assert gate["docx_version"] == 10 and gate["pdf"].endswith("正式圖式_v1.pdf")
    assert gate["gate"] == "block" and gate["case"] == "GD-261030-01"
    assert any(i["rule"] == "C07" for i in gate["blocking"])
    proc = root / "output" / "_process"
    assert (proc / "format_check_draft_v10.xlsx").exists() and (proc / "format_check_draft_v10.json").exists()
    assert json.loads((proc / "format_check_draft_latest.json").read_text(encoding="utf-8"))["gate"] == "block"
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in before.items())


def test_clean_passes(tmp_path, samples):
    root = _case(tmp_path, samples, "clean", {
        "③ 整合說明書 (完稿)_v1.docx": ("clean", "*.docx"), "圖式_v1.pdf": ("clean", "*.pdf")})
    gate = pipeline.run_gate(str(root), "draft")
    assert gate["gate"] == "pass" and gate["counts"]["必改"] == 0


def test_cli_exit_codes(tmp_path, samples, capsys):
    root = _case(tmp_path, samples, "claims_only", {"② 請求項 (claims)_v3.docx": ("case1_like", "*.docx")})
    assert main(["gate", str(root), "--stage", "claims", "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["stage"] == "claims" and out["docx_version"] == 3
    assert main(["gate", str(root), "--stage", "final", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["gate"] == "error"


def test_summary_line():
    g = {"gate": "block", "stage": "claims", "stage_label": "請求項初稿", "docx_version": 5,
         "counts": {"必改": 1, "建議": 2, "需人工確認": 0, "資訊": 0},
         "blocking": [{"rule": "B05", "location": "請求項8", "message": "重複引入"}]}
    assert pipeline.summary_line(g) == "格式檢查未通過｜請求項初稿（claims）v5｜必改 1　建議 2　需人工確認 0｜B05 請求項8：重複引入"


@pytest.mark.parametrize("name,ver", [("③ 整合說明書 (完稿)_v12.docx", 12), ("client_draft_final_v1.08.02修2.docx", 1),
                                      ("操作手冊.docx", 0)])
def test_file_version(name, ver):
    assert pipeline.file_version(Path(name)) == ver


def test_record_supabase(tmp_path, monkeypatch, rules):
    calls = []

    def fake_rest(url, key, method, path, body=None):
        calls.append((method, path.split("?")[0], body))
        if path.startswith("cases"):
            return [{"id": "c1"}]
        if method == "GET":
            return [{"version": 2}]
        return [{"id": "new"}]
    monkeypatch.setattr(pipeline, "_rest", fake_rest)
    root = tmp_path / "GD-1"
    gate = {"gate": "pass", "case": "GD-1", "stage": "final", "stage_label": "送件版", "docx_version": 1,
            "counts": {"必改": 0, "建議": 0, "需人工確認": 0, "資訊": 0}, "blocking": [],
            "reports": {"xlsx": str(root / "output/_process/format_check_final_v1.xlsx")},
            "started_at": "t0", "finished_at": "t1"}
    out = pipeline.record_supabase(gate, str(root), rules, url="https://x.supabase.co", key="k")
    assert out == {"agent_run_id": "new", "deliverable_id": "new"}
    run = next(b for m, p, b in calls if p == "agent_runs")
    deliv = next(b for m, p, b in calls if p == "deliverables" and m == "POST")
    assert run["stage"] == "format_check" and run["status"] == "done" and run["case_id"] == "c1"
    assert deliv["doc_type"] == "format_check" and deliv["version"] == 3
    assert deliv["docx_path"] == "_process/format_check_final_v1.xlsx"
