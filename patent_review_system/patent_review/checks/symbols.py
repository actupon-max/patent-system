"""C. 符號與圖式對應：三方對照（內文／符號說明／圖式）、圖號宣告與引用、代表圖。"""
from __future__ import annotations

import re
from collections import defaultdict

from ..model import Issue, Result
from ..pdf_reader import PdfData
from ..structure import Spec
from ..terms import find_body_symbols, parse_symbol_list

F = "說明書"


def _fig_key(s: str) -> str:
    return s.upper()


def run(spec: Spec, res: Result, pdf: PdfData | None) -> None:
    check_symbol_table(spec, res, pdf)
    figs = check_figures(spec, res, pdf)
    check_rep_figure(spec, res, pdf, figs)


# ── 符號三方對照 ──
def check_symbol_table(spec: Spec, res: Result, pdf: PdfData | None) -> None:
    cfg = spec.rules["symbols"]
    sev, basis = cfg["severity"], cfg["basis"]
    entries = parse_symbol_list(spec, "symbols")
    if not entries:
        if spec.has("symbols"):
            res.add(Issue(F, "符號說明", "C01", "符號說明為空或格式無法辨識，未做符號對照",
                          severity="需人工確認", basis=basis))
        return
    by_sym: dict[str, set] = defaultdict(set)
    by_name: dict[str, set] = defaultdict(set)
    first_loc: dict[str, str] = {}
    for e in entries:
        by_sym[e.symbol].add(e.name)
        by_name[e.name].add(e.symbol)
        first_loc.setdefault(e.symbol, e.loc)
    names = list(by_name)

    body: dict[str, list[tuple[str | None, str]]] = defaultdict(list)
    for p in spec.section_paras(*spec.description_keys):
        for sym, name, _ in find_body_symbols(spec, p.body, names):
            body[sym].append((name, p.loc()))

    fig_syms: dict[str, list[int]] = defaultdict(list)
    has_fig_text = False
    if pdf:
        for pg in pdf.pages:
            if pg.words:
                has_fig_text = True
            for w in pg.symbols:
                s = w.text.replace("′", "'").replace("’", "'")
                if pg.num not in fig_syms[s]:
                    fig_syms[s].append(pg.num)

    # 同一符號兩個名稱（符號說明內）
    for sym, ns in by_sym.items():
        if len(ns) > 1:
            res.add(Issue(F, first_loc[sym], "C03", f"符號 {sym} 對應兩個以上名稱", actual="、".join(sorted(ns)),
                          expected="一個符號只對應一個名稱", severity=sev, basis=basis))
    # 同一名稱兩個符號
    for name, ss in by_name.items():
        if len(ss) > 1 and not _variants(ss):
            res.add(Issue(F, "符號說明", "C04", f"「{name}」使用兩個以上符號", actual="、".join(sorted(ss)),
                          expected="一個名稱一個符號（同元件多個時用 10a、10b）",
                          severity=cfg["same_name_two_symbols_severity"], basis=basis))
    # 內文 vs 符號說明
    for sym, uses in body.items():
        if sym not in by_sym:
            locs = "、".join(sorted({l for _, l in uses})[:5])
            res.add(Issue(F, locs, "C02", f"內文使用符號 {sym}，符號說明未列", actual=sym,
                          expected="列入符號說明", severity=sev, basis=basis))
            continue
        for name, loc in uses:
            if name and name not in by_sym[sym]:
                res.add(Issue(F, loc, "C03", f"符號 {sym} 在內文的名稱與符號說明不同", actual=f"{name}{sym}",
                              expected=f"{'、'.join(sorted(by_sym[sym]))}{sym}", severity=sev, basis=basis))
                break
    for sym in by_sym:
        if sym not in body:
            res.add(Issue(F, first_loc[sym], "C01", f"符號說明列有 {sym}，內文未使用", actual=f"{sym} {'、'.join(by_sym[sym])}",
                          expected="內文以「名稱＋符號」出現", severity=cfg["unused_in_body_severity"], basis=basis))
    # 圖式 vs 符號說明
    if pdf and has_fig_text:
        for sym, pages in fig_syms.items():
            if sym not in by_sym:
                res.add(Issue("圖式", "、".join(f"第{n}頁" for n in pages), "C05", f"圖中符號 {sym} 在符號說明未列",
                              actual=sym, expected="列入符號說明", severity=sev, basis=basis))
        for sym in by_sym:
            if sym not in fig_syms and not sym.upper().startswith("S"):
                res.add(Issue("圖式", "全部圖式", "C05", f"符號說明列有 {sym}，圖式中找不到",
                              actual=f"{sym} {'、'.join(by_sym[sym])}", expected="圖中標示該符號",
                              severity=cfg["unused_in_body_severity"], basis=basis))
    elif pdf:
        res.add(Issue("圖式", "全部圖式", "C05", "圖式無文字層且未進行 OCR，未比對圖中符號",
                      severity="需人工確認", basis=basis))

    res.tables["符號對照表"] = [
        {"符號": sym,
         "符號說明名稱": "、".join(sorted(by_sym.get(sym, []))),
         "內文名稱": "、".join(sorted({n for n, _ in body.get(sym, []) if n})),
         "內文位置": "、".join(sorted({l for _, l in body.get(sym, [])})[:5]),
         "圖式頁": "、".join(map(str, fig_syms.get(sym, []))) if pdf else "未提供",
         } for sym in sorted(set(by_sym) | set(body) | set(fig_syms), key=_sym_sort)]


def _variants(ss: set) -> bool:
    """10a、10b 這種同元件多個實例視為合理。"""
    bases = {re.sub(r"[a-z'′’]+$", "", s) for s in ss}
    return len(bases) == 1


def _sym_sort(s: str):
    m = re.match(r"([A-Za-z]?)(\d+)(.*)", s)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else ("~", 0, s)


# ── 圖號 ──
def _refs_in(text: str, fc: dict) -> list[tuple[str, int]]:
    pat = re.compile(fc["ref_pattern"])
    one = r"\s*(?:圖|第)?\s*(\d+[A-Za-z]?)(?:\s*圖)?"
    rng = re.compile(r"\s*(?:" + "|".join(map(re.escape, fc["range_words"])) + ")" + one)
    lst = re.compile(r"\s*(?:" + "|".join(map(re.escape, fc["list_words"])) + ")" + one)
    out = []
    for m in pat.finditer(text):
        first = next(g for g in m.groups() if g)
        out.append((_fig_key(first), m.start()))
        end, prev = m.end(), first
        while True:
            r = rng.match(text, end)
            if r:
                a, b = re.match(r"(\d+)", prev), re.match(r"(\d+)", r.group(1))
                if a and b and prev.isdigit() and r.group(1).isdigit():
                    out += [(str(k), m.start()) for k in range(int(prev) + 1, int(r.group(1)) + 1)]
                else:
                    out.append((_fig_key(r.group(1)), m.start()))
                prev, end = r.group(1), r.end()
                continue
            ls = lst.match(text, end)
            if ls:
                out.append((_fig_key(ls.group(1)), m.start()))
                prev, end = ls.group(1), ls.end()
                continue
            break
    return out


def check_figures(spec: Spec, res: Result, pdf: PdfData | None) -> list[str]:
    fc = spec.rules["figures"]
    sev, basis = fc["severity"], fc["basis"]
    decl = re.compile(fc["declare_pattern"])
    declared: list[str] = []
    for p in spec.section_paras("drawings"):
        m = decl.match(p.body)
        if m:
            f = _fig_key(next(g for g in m.groups() if g))
            if f in declared:
                res.add(Issue(F, p.loc(), "C06", f"圖式簡單說明重複說明圖{f}", actual=f"圖{f}",
                              expected="每圖一次", severity=sev, basis=basis))
            declared.append(f)
    res.meta["圖式簡單說明圖數"] = len(declared)
    if not declared:
        if spec.has("drawings"):
            res.add(Issue(F, "圖式簡單說明", "C06", "圖式簡單說明中找不到「圖n為…」格式的宣告",
                          severity="需人工確認", basis=basis))
        return declared

    # 實施方式引用
    refs: dict[str, list[str]] = defaultdict(list)
    for p in spec.section_paras(*fc["ref_sections"]):
        for f, _ in _refs_in(p.body, fc):
            refs[f].append(p.loc())
    for f in declared:
        if f not in refs:
            res.add(Issue(F, "實施方式", "C07", f"圖{f}未在實施方式中被引用", actual="0 次",
                          expected="至少一次（例如「請參閱圖" + f + "」）", severity=sev, basis=basis))
    for f, locs in refs.items():
        if f not in declared:
            res.add(Issue(F, locs[0], "C07", f"實施方式引用了圖{f}，但圖式簡單說明沒有此圖", actual=f"圖{f}",
                          expected="、".join(f"圖{x}" for x in declared), severity=sev, basis=basis))

    # 圖號寫法一致
    if fc.get("style_consistency", True):
        full = "\n".join(p.body for p in spec.paras if p.section)
        a = len(re.findall(r"(?<!第)圖\s*\d", full))
        b = len(re.findall(r"第\s*\d+[A-Za-z]?\s*圖", full))
        if a and b:
            res.add(Issue(F, "全文", "C08", "圖號寫法混用「圖1」與「第1圖」", actual=f"圖n×{a}、第n圖×{b}",
                          expected="擇一", severity=fc["style_severity"], basis=basis))

    # PDF 圖數
    if pdf:
        pdf_figs: list[str] = []
        for pg in pdf.pages:
            for f, _ in pg.labels:
                if f not in pdf_figs:
                    pdf_figs.append(f)
        res.meta["圖式PDF圖數"] = len(pdf_figs)
        if any(pg.words for pg in pdf.pages):
            for f in declared:
                if f not in pdf_figs:
                    res.add(Issue("圖式", "全部圖式", "C06", f"圖式簡單說明有圖{f}，PDF 找不到此圖號",
                                  actual="、".join(f"圖{x}" for x in pdf_figs) or "無", expected=f"圖{f}",
                                  severity=sev, basis=basis))
            for f in pdf_figs:
                if f not in declared:
                    res.add(Issue("圖式", "全部圖式", "C06", f"PDF 有圖{f}，圖式簡單說明未說明",
                                  actual=f"圖{f}", expected="、".join(f"圖{x}" for x in declared), severity=sev, basis=basis))
    return declared


# ── 代表圖 ──
def check_rep_figure(spec: Spec, res: Result, pdf: PdfData | None, declared: list[str]) -> None:
    rc = spec.rules["rep_figure"]
    sev = rc["severity"]
    basis = "專利法施行細則第21條（指定代表圖及其符號簡單說明）"
    if not spec.has("rep_figure"):
        return
    text = spec.heading_rest("rep_figure") + " " + spec.section_text("rep_figure")
    if re.search(rc["none_pattern"], text):
        if parse_symbol_list(spec, "rep_symbols"):
            res.add(Issue(F, "代表圖", "C09", "指定無代表圖，卻列有代表圖符號", severity=sev, basis=basis))
        return
    m = re.search(rc["pattern"], text)
    if not m:
        res.add(Issue(F, "代表圖", "C09", "無法辨識指定代表圖", actual=text.strip()[:30], expected="例如「圖1」",
                      severity="需人工確認", basis=basis))
        return
    rep = _fig_key(m.group(1))
    res.meta["代表圖"] = f"圖{rep}"
    if declared and rep not in declared:
        res.add(Issue(F, "代表圖", "C09", f"指定代表圖 圖{rep} 不在圖式中", actual=f"圖{rep}",
                      expected="、".join(f"圖{x}" for x in declared), severity=sev, basis=basis))
    main = {e.symbol: e.name for e in parse_symbol_list(spec, "symbols")}
    rep_entries = parse_symbol_list(spec, "rep_symbols")
    for e in rep_entries:
        if e.symbol not in main:
            res.add(Issue(F, "代表圖之符號簡單說明", "C09", f"代表圖符號 {e.symbol} 不在符號說明中",
                          actual=f"{e.symbol}：{e.name}", expected="與符號說明一致", severity=sev, basis=basis))
        elif main[e.symbol] != e.name:
            res.add(Issue(F, "代表圖之符號簡單說明", "C09", f"代表圖符號 {e.symbol} 名稱與符號說明不同",
                          actual=e.name, expected=main[e.symbol], severity=sev, basis=basis))
    if pdf:
        pages = [pg for pg in pdf.pages if any(f == rep for f, _ in pg.labels)]
        if len(pages) == 1 and pages[0].words:
            pg = pages[0]
            # 同頁有多張圖時，只取最靠近該圖號的符號不可靠 → 僅在單圖頁比對
            if len({f for f, _ in pg.labels}) == 1:
                on_fig = {w.text.replace("′", "'") for w in pg.symbols}
                listed = {e.symbol for e in rep_entries}
                for s in sorted(on_fig - listed, key=_sym_sort):
                    res.add(Issue("圖式", f"圖{rep}（第{pg.num}頁）", "C09", f"代表圖中的符號 {s} 未列於代表圖符號說明",
                                  actual=s, expected="列入代表圖之符號簡單說明", severity=sev, basis=basis))
            else:
                res.add(Issue("圖式", f"第{pg.num}頁", "C09", "代表圖與其他圖在同一頁，未自動比對代表圖符號",
                              severity="需人工確認", basis=basis))
