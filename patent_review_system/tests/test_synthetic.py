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


def test_case2_halfwidth_brackets_are_house_style(run):
    """群淵家法「(例如，…)」括號半形（2026-11-02 使用者裁示保留）：半形括號不可報。"""
    res = run("case2_like")
    assert find(res, "A04") == []


def test_halfwidth_comma_semicolon_colon(run):
    res = run("halfwidth")
    hits = find(res, "A04", location="請求項1")
    assert hits and hits[0].severity == "必改"
    assert all(c in hits[0].message for c in ",:;")


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



# ── 智慧局官方空白表版面（平台送件版 _filing/*說明書(TIPO送件格式).docx 的結構） ──
def test_tipo_official_form_clean(run):
    """摘要頁在前、段號在 mc:AlternateContent、【請求項N】自動編號、符號說明半形冒號逐行：皆不可誤報。"""
    res = run("tipo_form")
    bad = [i for i in res.issues if i.severity in ("必改", "建議", "需人工確認")]
    assert bad == [], [f"{i.rule} {i.location} {i.message}" for i in bad]
    assert len(res.tables["請求項依附"]) == 4


def test_tipo_symbol_lines_parsed(samples, rules):
    from patent_review.terms import parse_symbol_list
    rules = dict(rules, _stage="final")
    spec = build_spec(str(samples / "tipo_form" / "tipo_form_說明書.docx"), rules)
    assert {e.symbol for e in parse_symbol_list(spec, "symbols")} >= {"1", "10", "11", "12", "20", "21"}
    assert [p.number for p in spec.section_paras("field") if p.number] == [1]
    assert spec.title == "光纖感測裝置"


def test_owned_intro_repeat(run):
    """附屬項「該光纖之一纖芯」：請求項1 已有一字不差的「該光纖之一纖芯」→ 前置基礎重複。"""
    res = run("tipo_owned_dup")
    hits = find(res, "B05", location="請求項2", message="重複")
    assert hits and "纖芯" in hits[0].message and hits[0].severity == "必改"
    # 「之一纖芯」視為已引入：請求項2 不可另報「該纖芯」缺乏前置基礎
    assert not find(res, "B05", message="缺乏前置基礎")


def test_grouped_rep_symbols_need_review_not_block(samples, rules):
    """代表圖符號「10,20:光纖、殼體」多符號共用一行：名稱不同只列需人工確認，不擋。"""
    from docx import Document
    from patent_review.runner import check_case
    src = samples / "tipo_form" / "tipo_form_說明書.docx"
    doc = Document(str(src))
    p = next(p for p in doc.paragraphs if p.text.startswith("1:光纖感測裝置"))
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)
    p.runs[0].text = "10,20:光纖、殼體"
    (samples / "grouped_rep").mkdir(exist_ok=True)
    out = samples / "grouped_rep" / "grouped_rep.docx"
    doc.save(str(out))
    res = check_case(str(out), None, rules=rules, stage="final", case="grouped")
    hits = find(res, "C09", message="多符號共用一行")
    assert {h.severity for h in hits} == {"需人工確認"} and len(hits) == 2


# ── 嚴重度覆寫（rules.yaml severity_overrides；2026-11-02 裁示 D01 橫式、B04 附屬項簡稱降為建議）──
def _override_result():
    from patent_review.model import Issue, Result
    res = Result(case="ov")
    res.add(Issue("圖式", "第1頁", "D01", "頁面尺寸不是 A4", actual="216×279mm", severity="必改", basis="b"))
    res.add(Issue("圖式", "第2頁", "D01", "頁面為橫式", actual="橫式", severity="必改", basis="b"))
    res.add(Issue("圖式", "全部圖式", "D01", "頁面方向不一致", actual="橫式、直式", severity="必改", basis="b"))
    res.add(Issue("說明書", "請求項2", "B04", "附屬項前言名稱與其獨立項不一致", actual="該裝置", severity="必改"))
    res.add(Issue("說明書", "請求項3", "B03", "依附錯誤", severity="必改"))
    return res


def test_severity_overrides_from_rules(rules):
    from patent_review.runner import apply_severity_overrides
    res = _override_result()
    ids = [i.id for i in res.issues]
    assert apply_severity_overrides(res, rules) == 3
    sev = {(i.rule, i.message): i.severity for i in res.issues}
    assert sev[("D01", "頁面尺寸不是 A4")] == "必改"          # 尺寸不符不降
    assert sev[("D01", "頁面為橫式")] == "建議"
    assert sev[("D01", "頁面方向不一致")] == "建議"
    assert sev[("B04", "附屬項前言名稱與其獨立項不一致")] == "建議"
    assert sev[("B03", "依附錯誤")] == "必改"
    assert [i.id for i in res.issues] == ids                  # ID 不含嚴重度，ignore 清單照用
    assert len(res.issues) == 5                               # 不關閉檢查，問題照列
    assert "事務所裁示" in res.issues[1].basis


def test_severity_overrides_rejects_bad_entries(rules):
    import copy
    import pytest
    from patent_review.runner import apply_severity_overrides
    bad = copy.deepcopy(rules)
    bad["severity_overrides"] = [{"rule": "D01", "message": "橫式", "severity": "輕微"}]
    with pytest.raises(ValueError):
        apply_severity_overrides(_override_result(), bad)
    bad["severity_overrides"] = [{"rule": "D01", "severity": "建議"}]
    with pytest.raises(ValueError):
        apply_severity_overrides(_override_result(), bad)


def test_severity_overrides_empty_is_noop(rules):
    import copy
    from patent_review.runner import apply_severity_overrides
    r = copy.deepcopy(rules)
    r.pop("severity_overrides", None)
    res = _override_result()
    assert apply_severity_overrides(res, r) == 0
    assert res.count("必改") == 5
