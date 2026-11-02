"""A. 說明書格式檢查。"""
from __future__ import annotations

import re

from ..model import Issue, Result
from ..structure import Spec

F = "說明書"
CJK = r"[㐀-鿿豈-﫿　-〿＀-￯]"


def run(spec: Spec, res: Result) -> None:
    check_sections(spec, res)
    check_paragraph_numbers(spec, res)
    check_typography(spec, res)
    check_width(spec, res)
    check_units(spec, res)
    check_abstract(spec, res)
    check_residue(spec, res)
    check_conversion_risk(spec, res)
    check_fees(spec, res)


def check_sections(spec: Spec, res: Result) -> None:
    cfg = spec.rules["sections"]
    order = [s["key"] for s in cfg["required"]]
    names = {s["key"]: s["name"] for s in cfg["required"]}
    found = [(k, i) for k, i, _ in spec.headings if k in names]
    seen: dict[str, int] = {}
    for k, i in found:
        if k in seen:
            res.add(Issue(F, spec.paras[i].loc(), "A01", f"段落標題重複：{names[k]}",
                          actual=f"第{seen[k] + 1}段與第{i + 1}段", expected="只出現一次",
                          severity=cfg["severity"], basis=cfg["basis"]))
        else:
            seen[k] = i
    for k in order:
        if k not in seen:
            res.add(Issue(F, "全文", "A01", f"缺少必備段落：{names[k]}", actual="未找到",
                          expected=f"【{names[k]}】", severity=cfg["severity"], basis=cfg["basis"]))
    # order_groups：各組內部須依序；組與組之間不比（摘要頁在前或在後皆可）。未設定時整份 required 為一組
    for group in cfg.get("order_groups") or [order]:
        present = [k for k in group if k in seen]
        actual_order = sorted(present, key=lambda k: seen[k])
        if actual_order != present:
            # 找出第一個順序錯誤的位置
            for a, e in zip(actual_order, present):
                if a != e:
                    res.add(Issue(F, spec.paras[seen[a]].loc(), "A01", f"段落順序錯誤：{names[a]} 出現在 {names[e]} 之前",
                                  actual="→".join(names[x] for x in actual_order),
                                  expected="→".join(names[x] for x in present),
                                  severity=cfg["severity"], basis=cfg["basis"]))
                    break


def check_paragraph_numbers(spec: Spec, res: Result) -> None:
    cfg = spec.rules["paragraph_numbers"]
    sev, basis = cfg["severity"], cfg["basis"]
    paras = [p for p in spec.section_paras(*cfg["numbered_sections"]) if p.text or p.auto_label]
    expected = cfg["start"]
    seen: dict[int, str] = {}
    sources = set()
    for p in paras:
        if p.number is None:
            if p.section in cfg.get("list_sections_allow_unnumbered", []):
                continue
            res.add(Issue(F, f"{p.loc()}（{_snippet(p.text)}）", "A02", "段落缺少段號",
                          actual="無段號", expected=f"【{expected:04d}】", severity=sev, basis=basis))
            continue
        sources.add(p.number_source)
        if p.number in seen:
            res.add(Issue(F, p.loc(), "A02", "段號重複", actual=f"【{p.number:04d}】",
                          expected=f"【{expected:04d}】", severity=sev, basis=basis))
        elif p.number != expected:
            kind = "跳號" if p.number > expected else "順序倒退"
            res.add(Issue(F, p.loc(), "A02", f"段號{kind}", actual=f"【{p.number:04d}】",
                          expected=f"【{expected:04d}】", severity=sev, basis=basis))
        seen[p.number] = p.loc()
        expected = p.number + 1
    if len(sources) > 1 and not cfg.get("allow_mixed", False):
        res.add(Issue(F, "全文", "A02", "段號混用 Word 自動編號與純文字",
                      actual="自動編號＋純文字", expected="擇一", severity=sev, basis=basis))
    res.meta["段號來源"] = {"auto": "Word 自動編號", "text": "純文字"}.get(next(iter(sources)), "混用") \
        if len(sources) == 1 else ("混用" if sources else "無")
    # 申請專利範圍、摘要不應有段號
    for p in spec.section_paras("claims", "abstract", "abstract_zh"):
        if p.number is not None:
            res.add(Issue(F, p.loc(), "A02", "申請專利範圍／摘要不應編段號", actual=f"【{p.number:04d}】",
                          expected="無段號", severity="建議", basis=basis))


def _font_ok(name, allowed, aliases) -> bool:
    if name is None:
        return True
    for key in allowed:
        if name == key or name in aliases.get(key, []):
            return True
    return False


def check_typography(spec: Spec, res: Result) -> None:
    cfg = spec.rules["typography"]
    if not cfg.get("enabled", True):
        return
    sev, basis, aliases = cfg["severity"], cfg["basis"], cfg.get("font_aliases", {})
    buckets: dict[str, list[tuple[str, str]]] = {}
    for p in spec.paras:
        if p.section is None or not p.text:
            continue
        loc = p.loc()
        has_cjk = any(re.search(CJK, r.text) for r in p.runs)
        for r in p.runs:
            if re.search(CJK, r.text) and not _font_ok(r.east_asia_font, cfg["east_asia_fonts"], aliases):
                buckets.setdefault("中文字型不符", []).append((loc, str(r.east_asia_font)))
                break
        for r in p.runs:
            if re.search(r"[A-Za-z0-9]", r.text) and not _font_ok(r.ascii_font, cfg["ascii_fonts"], aliases):
                buckets.setdefault("英數字型不符", []).append((loc, str(r.ascii_font)))
                break
        sizes = {r.size_pt for r in p.runs if r.size_pt}
        bad = [s for s in sizes if not cfg["size_pt"]["min"] <= s <= cfg["size_pt"]["max"]]
        if bad:
            buckets.setdefault("字級不符", []).append((loc, "、".join(f"{s:g}pt" for s in sorted(bad))))
        ls = cfg.get("line_spacing", {}).get(p.line_rule or "")
        if p.line_rule and ls and not ls["min"] <= (p.line_value or 0) <= ls["max"]:
            buckets.setdefault("行距不符", []).append((loc, f"{p.line_rule} {p.line_value:g}"))
        elif p.line_rule and p.line_rule != "multiple" and "multiple" in cfg.get("line_spacing", {}):
            buckets.setdefault("行距不符", []).append((loc, f"{p.line_rule} {p.line_value:g}pt"))
        if p.alignment not in cfg["alignment"] and has_cjk:
            buckets.setdefault("對齊方式不符", []).append((loc, str(p.alignment)))
    expected = {
        "中文字型不符": "、".join(cfg["east_asia_fonts"]),
        "英數字型不符": "、".join(cfg["ascii_fonts"]),
        "字級不符": f"{cfg['size_pt']['min']}–{cfg['size_pt']['max']}pt",
        "行距不符": "、".join(f"{k} {v['min']}–{v['max']}" for k, v in cfg.get("line_spacing", {}).items()),
        "對齊方式不符": "、".join(str(a) for a in cfg["alignment"]),
    }
    limit = cfg.get("max_listed", 30)
    for msg, items in buckets.items():
        for loc, actual in items[:limit]:
            res.add(Issue(F, loc, "A03", msg, actual=actual, expected=expected[msg], severity=sev, basis=basis))
        if len(items) > limit:
            res.add(Issue(F, "全文", "A03", f"{msg}（其餘 {len(items) - limit} 段未逐一列出）",
                          actual=f"共 {len(items)} 段", expected=expected[msg], severity=sev, basis=basis))


def check_width(spec: Spec, res: Result) -> None:
    cfg = spec.rules["width_check"]
    if not cfg.get("enabled", True):
        return
    exempt = cfg.get("section_exempt_chars") or {}
    pats: dict[str, re.Pattern | None] = {}

    def pat_for(section: str) -> re.Pattern | None:
        if section not in pats:
            chars = "".join(c for c in cfg["halfwidth_chars"] if c not in exempt.get(section, ""))
            esc = re.escape(chars)
            pats[section] = re.compile(rf"(?:(?<={CJK})[{esc}])|(?:[{esc}](?={CJK}))") if chars else None
        return pats[section]

    for p in spec.paras:
        if p.section is None or p.section in cfg.get("skip_sections", []) or p.is_heading:
            continue
        pat = pat_for(p.section)
        if pat is None:
            continue
        text = p.body
        hits = list(pat.finditer(text))
        if not hits:
            continue
        loc = _claim_loc(spec, p) or p.loc()
        found = "".join(sorted({h.group() for h in hits}))
        examples = "；".join(_ctx(text, h.start()) for h in hits[:3])
        res.add(Issue(F, loc, "A04", f"中文語境使用半形標點 {found}（{len(hits)} 處）",
                      actual=examples, expected="".join(cfg["fullwidth_map"].get(c, c) for c in found),
                      severity=cfg["severity"], basis=cfg["basis"], quote=examples))


def check_units(spec: Spec, res: Result) -> None:
    cfg = spec.rules["unit_consistency"]
    if not cfg.get("enabled", True):
        return
    skip = set(spec.rules["width_check"].get("skip_sections", []))
    paras = [p for p in spec.paras if p.section and p.section not in skip]
    full = "\n".join(p.body for p in paras)
    for group in cfg["groups"]:
        used = {}
        for term in group:
            n = full.count(term)
            if n:
                used[term] = n
        if len(used) > 1:
            locs = []
            for term in used:
                p = next((p for p in paras if term in p.body), None)
                if p:
                    locs.append(f"{term}@{_claim_loc(spec, p) or p.loc()}")
            res.add(Issue(F, "、".join(locs), "A05", "同一文件混用不同寫法",
                          actual="、".join(f"{t}×{n}" for t, n in used.items()), expected="擇一使用",
                          severity=cfg["severity"], basis=cfg["basis"]))


def check_abstract(spec: Spec, res: Result) -> None:
    cfg = spec.rules["abstract"]
    text = spec.abstract_text
    if not text:
        return
    t = text
    if not cfg.get("count_whitespace", False):
        t = re.sub(r"\s", "", t)
    if not cfg.get("count_punctuation", True):
        t = re.sub(r"[　-〿＀-／：-＠,.;:()!?]", "", t)
    n = len(t)
    res.meta["摘要字數"] = n
    if n > cfg["max_chars"]:
        res.add(Issue(F, "摘要", "A06", "中文摘要超過字數上限", actual=f"{n} 字",
                      expected=f"≤ {cfg['max_chars']} 字", severity=cfg["severity"], basis=cfg["basis"]))


def check_residue(spec: Spec, res: Result) -> None:
    cfg = spec.rules["residue"]
    sev, basis = cfg["severity"], cfg["basis"]
    d = spec.data
    if cfg.get("check_tracked_changes"):
        for idx, kind, t in d.tracked_changes:
            res.add(Issue(F, spec.paras[idx].loc(), "A07", f"殘留追蹤修訂（{kind}）", actual=t,
                          expected="接受或拒絕所有修訂", severity=sev, basis=basis))
    if cfg.get("check_comments"):
        for idx, t in d.comments:
            loc = spec.paras[idx].loc() if idx is not None else "全文"
            res.add(Issue(F, loc, "A07", "殘留註解", actual=t, expected="刪除註解", severity=sev, basis=basis))
    allowed = {c.lower() for c in cfg.get("allowed_colors", [])}
    for p in spec.paras:
        for r in p.runs:
            if cfg.get("check_highlight") and r.highlight:
                res.add(Issue(F, p.loc(), "A07", "殘留螢光標示／網底", actual=f"{r.highlight}：{r.text[:20]}",
                              expected="無", severity=sev, basis=basis))
                break
        for r in p.runs:
            if cfg.get("check_color") and r.color and r.color.lower() not in allowed:
                res.add(Issue(F, p.loc(), "A07", "彩色字", actual=f"#{r.color}：{r.text[:20]}",
                              expected="黑色／自動", severity=sev, basis=basis))
                break
        for r in p.runs:
            if cfg.get("check_hidden") and r.hidden:
                res.add(Issue(F, p.loc(), "A07", "隱藏文字", actual=r.text[:30], expected="刪除或取消隱藏",
                              severity=sev, basis=basis))
                break
    if cfg.get("check_empty_paragraphs"):
        empties = [p for p in spec.paras if p.section and not p.text and not p.is_heading and not p.auto_label
                   and not p.in_table]
        if empties:
            locs = []
            for p in empties:
                prev = next((q for q in reversed(spec.paras[:p.idx]) if q.text), None)
                locs.append(f"{prev.loc() if prev else '開頭'}之後")
            res.add(Issue(F, "、".join(locs[:15]) + ("…" if len(locs) > 15 else ""), "A07",
                          "空白段落", actual=f"{len(empties)} 個", expected="0",
                          severity=cfg.get("empty_paragraph_severity", "建議"), basis=basis))


def check_conversion_risk(spec: Spec, res: Result) -> None:
    seen = set()
    for idx, kind in spec.data.risky_objects:
        key = (idx, kind)
        if key in seen:
            continue
        seen.add(key)
        res.add(Issue(F, spec.paras[idx].loc(), "A08", f"轉檔風險：{kind}", actual=kind,
                      expected="送件前以智慧局轉檔確認", severity="需人工確認",
                      basis="智慧局電子送件轉檔（程式無法模擬，僅列出高風險元素）"))


def check_fees(spec: Spec, res: Result) -> None:
    cfg = spec.rules["fees"]
    if not cfg.get("enabled", True):
        return
    n = len(spec.claims)
    res.meta["請求項數"] = n
    res.meta["說明書頁數(Word 記錄)"] = spec.data.pages
    if n > cfg["claims_free"]:
        res.add(Issue(F, "申請專利範圍", "A09", "請求項超過免加收項數", actual=f"{n} 項",
                      expected=f"≤ {cfg['claims_free']} 項（超過每項加收）", severity=cfg["severity"], basis=cfg["basis"]))
    if spec.data.pages and spec.data.pages > cfg["pages_free"]:
        res.add(Issue(F, "全文", "A09", "頁數可能超過免加收頁數（以 Word 儲存時的頁數估計）",
                      actual=f"{spec.data.pages} 頁", expected=f"≤ {cfg['pages_free']} 頁",
                      severity=cfg["severity"], basis=cfg["basis"]))


def _snippet(t: str, n: int = 15) -> str:
    return t[:n] + ("…" if len(t) > n else "")


def _ctx(t: str, i: int, w: int = 6) -> str:
    return "「" + t[max(0, i - w): i + w + 1] + "」"


def _claim_loc(spec: Spec, p) -> str | None:
    if p.section != "claims":
        return None
    c = None
    for cl in spec.claims:
        if cl.para_idx <= p.idx:
            c = cl
    return c.loc if c else None
