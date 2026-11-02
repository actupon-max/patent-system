"""B. 申請專利範圍檢查：編號、依附、前言一致、前置基礎、說明書支持。"""
from __future__ import annotations

import re

from ..model import Issue, Result
from ..structure import Claim, Spec
from ..terms import parse_symbol_list, find_body_symbols

F = "申請專利範圍"


def run(spec: Spec, res: Result) -> None:
    claims = spec.claims
    if not claims:
        if spec.has("claims") or spec.rules.get("_stage") == "claims":
            res.add(Issue(F, "申請專利範圍", "B01", "找不到請求項（項號格式無法辨識）", actual="0 項",
                          expected="【第1項】或「1.」開頭", severity="必改", basis=spec.rules["claims"]["basis"]))
        return
    check_numbering(spec, res)
    check_one_sentence(spec, res)
    check_dependency(spec, res)
    check_preamble(spec, res)
    terms = element_terms(spec)
    derived = derived_terms(spec, terms)
    res.meta["前置基礎詞典數"] = f"{len(terms)}（符號說明）＋{len(derived)}（由請求項推得）"
    if spec.rules.get("_enabled", {}).get("antecedent", True):
        check_antecedent(spec, res, terms, derived)
        check_owned_intro_repeat(spec, res)
    if spec.rules.get("_enabled", {}).get("support", True):
        check_support(spec, res)
    res.tables["請求項依附"] = [
        {"請求項": c.num, "類型": "獨立項" if not c.refs else ("多項附屬" if len(c.refs) > 1 else "附屬項"),
         "依附": "、".join(map(str, c.refs)), "前言": c.preamble[:40]} for c in claims]


def check_numbering(spec: Spec, res: Result) -> None:
    cfg = spec.rules["claims"]
    expected = 1
    seen = set()
    for c in spec.claims:
        if c.num in seen:
            res.add(Issue(F, c.loc, "B01", "請求項編號重複", actual=str(c.num), expected=str(expected),
                          severity=cfg["severity"], basis=cfg["basis"]))
        elif c.num != expected:
            res.add(Issue(F, c.loc, "B01", "請求項編號不連續", actual=str(c.num), expected=str(expected),
                          severity=cfg["severity"], basis=cfg["basis"]))
        seen.add(c.num)
        expected = c.num + 1


def check_one_sentence(spec: Spec, res: Result) -> None:
    cfg = spec.rules["claims"]
    if not cfg.get("one_sentence", True):
        return
    for c in spec.claims:
        t = c.text.strip()
        n = t.count("。")
        if n == 0:
            res.add(Issue(F, c.loc, "B02", "請求項未以句號結尾", actual=t[-10:], expected="以「。」結尾",
                          severity=cfg["severity"], basis="專利法施行細則第18條（請求項以一句為之）"))
        elif n > 1 or not t.endswith("。"):
            i = t.find("。")
            res.add(Issue(F, c.loc, "B02", "請求項含多個句號（應以一句為之）", actual=f"{n} 個句號；「{t[max(0, i - 8):i + 1]}」",
                          expected="僅結尾一個「。」", severity=cfg["severity"],
                          basis="專利法施行細則第18條（請求項以一句為之）", quote=t[max(0, i - 8):i + 1]))


def check_dependency(spec: Spec, res: Result) -> None:
    cfg = spec.rules["claims"]
    sev, basis = cfg["severity"], cfg["basis"]
    nums = {c.num for c in spec.claims}
    by_num = {c.num: c for c in spec.claims}
    for c in spec.claims:
        for r in c.refs:
            if r >= c.num:
                res.add(Issue(F, c.loc, "B03", "依附在後或自身的請求項", actual=f"依附請求項{r}",
                              expected=f"只能依附請求項1–{c.num - 1}", severity=sev, basis=basis, quote=c.ref_text))
            elif r not in nums:
                res.add(Issue(F, c.loc, "B03", "依附不存在的請求項", actual=f"依附請求項{r}",
                              expected="存在的項號", severity=sev, basis=basis, quote=c.ref_text))
        if len(c.refs) > 1:
            alt = any(w in c.ref_text for w in cfg["alternative_words"])
            conj = any(w in c.ref_text for w in cfg["conjunctive_words"])
            if conj and not alt:
                res.add(Issue(F, c.loc, "B03", "多項附屬項未以擇一形式記載", actual=c.ref_text,
                              expected="例如「如請求項1或2」「如請求項1至3中任一項」", severity=sev, basis=basis,
                              quote=c.ref_text))
            elif not alt:
                res.add(Issue(F, c.loc, "B03", "多項附屬項未明示擇一（缺「或／任一」）", actual=c.ref_text,
                              expected="「中任一項」或「或」", severity="建議", basis=basis, quote=c.ref_text))
            # 多項附屬不得直接或間接依附多項附屬
            stack, visited = list(c.refs), set()
            while stack:
                r = stack.pop()
                if r in visited or r not in by_num or r >= c.num:
                    continue
                visited.add(r)
                if len(by_num[r].refs) > 1:
                    res.add(Issue(F, c.loc, "B03", "多項附屬項直接或間接依附另一多項附屬項",
                                  actual=f"經由請求項{r}", expected="不得依附多項附屬項", severity=sev, basis=basis,
                                  quote=c.ref_text))
                    break
                stack += by_num[r].refs
    # 循環依附（項號錯誤時才可能發生）
    for c in spec.claims:
        path, cur = [c.num], c
        while cur.refs:
            nxt = cur.refs[0]
            if nxt in path:
                res.add(Issue(F, c.loc, "B03", "循環依附", actual="→".join(map(str, path + [nxt])),
                              expected="無循環", severity=sev, basis=basis))
                break
            if nxt not in by_num:
                break
            path.append(nxt)
            cur = by_num[nxt]


def subject_of(c: Claim) -> str | None:
    """取前言標的名稱：獨立項「一種X，」；附屬項「如請求項n所述之X，」。"""
    pre = c.preamble
    if not c.refs:
        m = re.match(r"^\s*一種\s*(.+?)\s*(?:，|,|：|:|包含|包括|係包含|其包含|其特徵|$)", pre)
        return m.group(1).strip() if m else None
    m = re.search(r"(?:所述|所記載|所定義)?(?:之|的)\s*(.+?)\s*$", pre)
    if m:
        return re.sub(r"^(?:任一項|中任一項|任一)(?:所述)?(?:之|的)?", "", m.group(1)).strip()
    return None


def root_of(c: Claim, by_num: dict) -> Claim:
    seen = set()
    while c.refs and c.refs[0] in by_num and c.refs[0] < c.num and c.num not in seen:
        seen.add(c.num)
        c = by_num[c.refs[0]]
    return c


def check_preamble(spec: Spec, res: Result) -> None:
    cfg = spec.rules["claims"]
    by_num = {c.num: c for c in spec.claims}
    for c in spec.claims:
        if not c.refs:
            continue
        root = root_of(c, by_num)
        a, b = subject_of(c), subject_of(root)
        if a and b and a != b:
            res.add(Issue(F, c.loc, "B04", "附屬項前言名稱與其獨立項不一致", actual=a,
                          expected=f"{b}（請求項{root.num}）", severity=cfg["severity"],
                          basis="專利審查基準（附屬項應包含所依附請求項之標的名稱）", quote=c.preamble))


def element_terms(spec: Spec) -> list[str]:
    cfg = spec.rules["antecedent"]
    names = [e.name for e in parse_symbol_list(spec, "symbols")]
    names += [e.name for e in parse_symbol_list(spec, "rep_symbols")]
    names += cfg.get("extra_terms", [])
    names = [n for n in names if n and n not in cfg.get("ignore_terms", [])]
    return sorted(set(names), key=len, reverse=True)


PREAMBLE_REF = re.compile(r"(?:請求項\s*\d+\s*項?|任一項|中任一|之一)\s*$")


def _span(text: str, j: int, cfg: dict) -> str:
    """從位置 j 取出元件名稱候選：遇停止字、或長度達下限後遇到動詞字即結束。"""
    sc = cfg["support_check"]
    stop, end_chars = set(sc["stop_chars"]), set(cfg.get("term_end_chars", ""))
    k = j
    while k < len(text) and k - j < sc["max_len"] and text[k] not in stop \
            and re.match(r"[\u3400-\u9fffA-Za-z0-9]", text[k]):
        if k - j >= sc["min_len"] and text[k] in end_chars:
            break
        k += 1
    return text[j:k]


def derived_terms(spec: Spec, terms: list[str]) -> list[str]:
    """沒有符號說明（例如請求項初稿）時，由「該X」反推元件名稱。

    取「該」之後到停止字為止的字串，再找出在請求項中曾以引入詞出現的最長前綴；
    這些詞的判斷可信度較低，報告時標「需人工確認」。
    """
    cfg = spec.rules["antecedent"]
    refm = sorted(cfg["ref_markers"], key=len, reverse=True)
    intro = sorted(cfg["intro_markers"], key=len, reverse=True)
    all_text = "".join(c.text for c in spec.claims)
    out = set()
    for m in re.finditer("|".join(map(re.escape, refm)), all_text):
        if PREAMBLE_REF.search(all_text[: m.start()]):
            continue
        span = _span(all_text, m.end(), cfg)
        if len(span) < 2 or any(span.startswith(t) for t in terms):
            continue
        best = None
        for L in range(len(span), 1, -1):
            pre = span[:L]
            if any(mk + pre in all_text for mk in intro):
                best = pre
                break
        out.add(best or span)
    return sorted(out - set(terms) - set(cfg.get("ignore_terms", [])), key=len, reverse=True)


def _chain(c: Claim, by_num: dict) -> list[Claim]:
    """請求項及其依附來源（由獨立項往下）；多項附屬取第一個依附路徑。"""
    out, cur, seen = [c], c, {c.num}
    while cur.refs and cur.refs[0] in by_num and cur.refs[0] not in seen and cur.refs[0] < cur.num:
        cur = by_num[cur.refs[0]]
        seen.add(cur.num)
        out.append(cur)
    return list(reversed(out))


def scan_terms(text: str, terms: list[str], cfg: dict) -> list[tuple[str, str, int, str]]:
    """回傳 [(term, kind(intro/intro_soft/ref/bare), pos, marker)]，採最長詞優先、不重疊。

    intro_soft：引入詞前接 soft_intro_prefix（例「該光纖之一模場直徑」的「之」）——算已引入，
    但不據以判定重複（同名不同所屬元件常見；重複由 check_owned_intro_repeat 比對所屬元件）。
    """
    intro = sorted(cfg["intro_markers"], key=len, reverse=True)
    refm = sorted(cfg["ref_markers"], key=len, reverse=True)
    not_pre = cfg["not_intro_prefix"]
    soft_pre = cfg.get("soft_intro_prefix", [])
    hits, i = [], 0
    while i < len(text):
        t = next((t for t in terms if text.startswith(t, i)), None)
        if not t:
            i += 1
            continue
        before = text[:i]
        kind, marker = "bare", ""
        r = next((m for m in refm if before.endswith(m)), None)
        if r:
            kind, marker = "ref", r
        else:
            m = next((m for m in intro if before.endswith(m)), None)
            if m:
                pre = before[: len(before) - len(m)]
                if any(pre.endswith(x) for x in not_pre):
                    pass
                elif any(pre.endswith(x) for x in soft_pre):
                    kind, marker = "intro_soft", m
                else:
                    kind, marker = "intro", m
        hits.append((t, kind, i, marker))
        i += len(t)
    return hits


def check_antecedent(spec: Spec, res: Result, terms: list[str], derived: list[str] = ()) -> None:
    cfg = spec.rules["antecedent"]
    if not cfg.get("enabled", True):
        return
    if not terms:
        res.add(Issue(F, "申請專利範圍", "B05", "沒有符號說明可建立元件詞典，前置基礎改由請求項用語推得（結果需人工確認）",
                      severity="資訊", basis=cfg["basis"]))
    low = set(derived)
    terms = sorted(set(terms) | low, key=len, reverse=True)
    if not terms:
        return
    by_num = {c.num: c for c in spec.claims}
    for c in spec.claims:
        introduced: dict[str, str] = {}
        for anc in _chain(c, by_num)[:-1]:
            for t, kind, _, _ in scan_terms(anc.text, terms, cfg):
                if kind in ("intro", "intro_soft"):
                    introduced.setdefault(t, anc.loc)
        reported = set()
        for t, kind, pos, marker in scan_terms(c.text, terms, cfg):
            quote = c.text[max(0, pos - 6): pos + len(t) + 2]
            if kind == "ref" and PREAMBLE_REF.search(c.text[: pos - len(marker)]):
                continue  # 「如請求項1所述之X」是前言標的，不是元件引用
            if kind == "ref" and t not in introduced and (t, "ref") not in reported:
                reported.add((t, "ref"))
                res.add(Issue(F, c.loc, "B05", f"「{marker}{t}」缺乏前置基礎", actual=f"「{quote}」",
                              expected=f"先以「一{t}」引入",
                              severity="需人工確認" if t in low else cfg["severity"], basis=cfg["basis"], quote=quote))
            elif kind == "intro":
                if t in introduced and (t, "intro") not in reported:
                    reported.add((t, "intro"))
                    res.add(Issue(F, c.loc, "B05", f"「{t}」重複以「{marker}」引入（前置基礎重複）",
                                  actual=f"「{quote}」；已於{introduced[t]}引入",
                                  expected=f"改為「該{t}」；若為不同元件請改用不同名稱",
                                  severity="需人工確認" if t in low else cfg["severity"],
                                  basis=cfg["basis"], quote=quote))
                introduced.setdefault(t, c.loc)
            elif kind == "intro_soft":
                introduced.setdefault(t, c.loc)


def check_owned_intro_repeat(spec: Spec, res: Result) -> None:
    """附屬項以「該A之一B」引入 B，而依附鏈上前項已有一字不差的「該A之一B」→ B 重複引入。

    「之一」在詞典比對中不視為引入（避免「其中之一」誤報），因此「該第一光纖之一模場直徑」這類
    帶所屬元件的引入另外比對：所屬元件 A 與名稱 B 都相同才算，不同元件各自的 B（第一／第二光纖各有
    模場直徑）不會誤報。
    """
    cfg = spec.rules["antecedent"]
    pat = cfg.get("owned_intro_pattern")
    if not pat:
        return
    rx = re.compile(pat)
    by_num = {c.num: c for c in spec.claims}

    def phrases(c: Claim) -> list[tuple[str, str, int]]:
        out = []
        for m in rx.finditer(c.text):
            name = _span(c.text, m.end(), cfg)
            if len(name) >= 2 and name not in cfg.get("ignore_terms", []):
                out.append((m.group(1), name, m.start()))
        return out

    for c in spec.claims:
        if not c.refs:
            continue
        prior: dict[tuple[str, str], str] = {}
        for anc in _chain(c, by_num)[:-1]:
            for owner, name, _ in phrases(anc):
                prior.setdefault((owner, name), anc.loc)
        reported = set()
        for owner, name, pos in phrases(c):
            if (owner, name) in prior and (owner, name) not in reported:
                reported.add((owner, name))
                quote = c.text[pos: pos + len(owner) + len(name) + 3]
                res.add(Issue(F, c.loc, "B05", f"「{name}」重複以「一」引入（前置基礎重複）",
                              actual=f"「{quote}」；已於{prior[(owner, name)]}引入",
                              expected=f"改為「該{owner}之該{name}」", severity=cfg["severity"],
                              basis=cfg["basis"], quote=quote))


def check_support(spec: Spec, res: Result) -> None:
    """請求項中「該／所述 X」的 X 是否出現在說明書內文（不含申請專利範圍與摘要）。"""
    cfg = spec.rules["antecedent"]
    sc = cfg.get("support_check", {})
    if not sc.get("enabled", True):
        return
    desc = spec.section_text(*spec.description_keys) + spec.section_text("symbols")
    if not desc.strip():
        return  # 僅有請求項初稿時無法檢查
    stop = set(sc["stop_chars"])
    refm = sorted(cfg["ref_markers"], key=len, reverse=True)
    missing: dict[str, str] = {}
    for c in spec.claims:
        for m in re.finditer("|".join(map(re.escape, refm)), c.text):
            j = m.end()
            k = j
            while k < len(c.text) and k - j < sc["max_len"] and c.text[k] not in stop \
                    and re.match(r"[㐀-鿿A-Za-z0-9]", c.text[k]):
                k += 1
            cand = c.text[j:k]
            if len(cand) < sc["min_len"] or cand in desc:
                continue
            # 逐步縮短，只要有任一長度 ≥ min_len 的前綴出現在說明書就視為有支持
            if any(cand[:L] in desc for L in range(len(cand) - 1, sc["min_len"] - 1, -1)):
                continue
            missing.setdefault(cand, c.loc)
    for term, loc in missing.items():
        res.add(Issue(F, loc, "B06", "請求項用語在說明書內文找不到", actual=term, expected="說明書內文有相同用語",
                      severity=sc["severity"], basis="專利法第26條第2項（請求項應為說明書所支持）"))


__all__ = ["run", "element_terms", "scan_terms", "find_body_symbols"]
