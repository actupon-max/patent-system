"""以合成樣本驗證各項規則。"""
from conftest import find

from patent_review.checks.semantic import locate
from patent_review.structure import build_spec


# ── 驗收門檻：劉教授兩案的三個已知問題（以合成樣本重現） ──
def test_case1_figure4_not_referenced(run):
    res = run("case1_like")
    hits = find(res, "C07", message="圖4未在實施方式中被引用")
    assert hits and hits[0].severity == "必改"


def test_case1_claim8_duplicate_antecedent(run):
    res = run("case1_like")
    hits = find(res, "B05", location="請求項8", message="重複")
    assert hits and "光纖" in hits[0].message and hits[0].severity == "必改"


def test_case2_halfwidth_brackets(run):
    res = run("case2_like")
    hits = find(res, "A04")
    assert {h.location for h in hits} >= {"【0009】", "請求項1"}
    assert all("(" in h.message or ")" in h.message for h in hits)


# ── 反向測試：乾淨樣本不可有必改／建議 ──
def test_clean_has_no_findings(run):
    res = run("clean")
    bad = [i for i in res.issues if i.severity in ("必改", "建議", "需人工確認")]
    assert bad == [], [f"{i.rule} {i.location} {i.message}" for i in bad]


def test_autonumber_detected_and_clean(run):
    res = run("autonum")
    assert res.meta["段號來源"] == "Word 自動編號"
    assert res.count("必改") == 0, [f"{i.rule} {i.location} {i.message}" for i in res.issues]


def test_dirty_residue_and_numbering(run):
    res = run("dirty")
    assert find(res, "A02", message="跳號")
    assert find(res, "A02", message="重複")
    assert find(res, "A07", message="追蹤修訂")
    assert find(res, "A07", message="螢光")
    assert find(res, "A07", message="彩色字")
    assert find(res, "A07", message="空白段落")


def test_bad_pdf_color_and_label_height(run):
    res = run("bad_pdf")
    assert len(find(res, "D05", message="彩色")) == 4
    assert find(res, "D07")


def test_claims_stage_without_headings(run):
    res = run("claims_only", stage="claims")
    assert not find(res, "A01"), "請求項初稿階段不應檢查段落標題"
    assert find(res, "B03", location="請求項4", message="擇一")
    assert find(res, "B03", location="請求項5", message="在後")
    dup = find(res, "B05", location="請求項3", message="重複")
    assert dup and dup[0].severity == "需人工確認"  # 無符號說明時由請求項推得，可信度較低
    assert find(res, "B05", location="請求項4", message="蓋板")


def test_symbol_table_built(run):
    res = run("clean")
    rows = {r["符號"]: r for r in res.tables["符號對照表"]}
    assert rows["10"]["符號說明名稱"] == "光纖"
    assert rows["10"]["內文名稱"] == "光纖"
    assert "1" in rows["10"]["圖式頁"]


def test_issue_ids_stable(run, samples, rules):
    from patent_review.runner import check_case
    a = run("case1_like")
    d = samples / "case1_like"
    b = check_case(str(next(d.glob("*.docx"))), str(next(d.glob("*.pdf"))), rules=rules, case="case1_like")
    assert [i.id for i in a.sorted_issues()] == [i.id for i in b.sorted_issues()]
    ignored = check_case(str(next(d.glob("*.docx"))), str(next(d.glob("*.pdf"))), rules=rules,
                         ignore={a.issues[0].id})
    assert len(ignored.issues) == len(a.issues) - 1


def test_llm_quote_must_exist(samples, rules):
    """E 項：引句必須能在原文逐字找到，否則丟棄。"""
    spec = build_spec(str(next((samples / "clean").glob("*.docx"))), rules)
    assert locate(spec, "纖芯11被包層12包覆") == "【0009】"
    assert locate(spec, "該包層包覆該纖芯") == "請求項3"
    assert locate(spec, "光纖穿過殼體的側壁") is None   # 捏造的引句


def test_cli_writes_reports(samples, tmp_path):
    from patent_review.cli import main
    code = main([str(samples / "clean"), str(samples / "case1_like"), "-o", str(tmp_path)])
    assert code == 1   # 有必改時回傳 1，可接 CI 或批次腳本
    assert (tmp_path / "clean_檢查報告.xlsx").exists()
    assert (tmp_path / "case1_like_final_檢查報告.json").exists()
    assert (tmp_path / "總表.xlsx").exists()


def test_raster_pdf_dpi_color_text_layer(run):
    res = run("raster_pdf")
    assert find(res, "D06", actual="150 dpi")
    assert find(res, "D05", message="彩色")
    assert find(res, "D04")


def test_pdf_checks_without_poppler(samples, rules, monkeypatch):
    """雲端平台沒有 poppler 時，改用 pypdf 檢查字型嵌入、影像解析度與色彩。"""
    from patent_review import pdf_reader
    from patent_review.runner import check_case
    monkeypatch.setattr(pdf_reader, "HAVE_POPPLER", False)
    for name, rule, kw in (("raster_pdf", "D06", {"actual": "150 dpi"}), ("raster_pdf", "D05", {"message": "彩色"}),
                           ("bad_pdf", "D05", {"message": "彩色"})):
        d = samples / name
        res = check_case(str(next(d.glob("*.docx"))), str(next(d.glob("*.pdf"))), rules=rules)
        assert find(res, rule, **kw), (name, rule)
    d = samples / "clean"
    res = check_case(str(next(d.glob("*.docx"))), str(next(d.glob("*.pdf"))), rules=rules)
    assert not find(res, "D03"), "嵌入字型不應被報未嵌入"


def test_json_report_for_platform(samples, tmp_path):
    """平台上傳用的報告：含階段、版本與檔案完整 sha256，平台據此確認報告對應的檔案。"""
    import hashlib
    import json
    from patent_review.cli import main
    d = samples / "case1_like"
    main([str(d), "--stage", "draft", "-o", str(tmp_path)])
    rep = json.loads((tmp_path / "case1_like_draft_檢查報告.json").read_text(encoding="utf-8"))
    assert rep["format"] == "patent-review-report/1"
    assert rep["stage"] == "draft"
    assert rep["counts"]["必改"] == 2
    docx = next(d.glob("*.docx"))
    pdf = next(d.glob("*.pdf"))
    assert rep["files"]["docx"]["sha256"] == hashlib.sha256(docx.read_bytes()).hexdigest()
    assert rep["files"]["pdf"]["sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()

