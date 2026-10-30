"""把段落切成「發明名稱／技術領域／…／申請專利範圍／摘要」等段落，並解析段號與請求項。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .docx_reader import DocxData, Para, read_docx

PARA_NO = re.compile(r"^【(\d{4})】")


@dataclass
class Claim:
    num: int
    text: str
    para_idx: int
    refs: list[int] = field(default_factory=list)   # 依附的項號
    ref_text: str = ""                              # 依附語句原文
    preamble: str = ""

    @property
    def loc(self) -> str:
        return f"請求項{self.num}"


@dataclass
class Spec:
    data: DocxData
    rules: dict
    headings: list[tuple[str, int, str]] = field(default_factory=list)  # (key, 段落序號, 標題後文字)
    claims: list[Claim] = field(default_factory=list)

    @property
    def paras(self) -> list[Para]:
        return self.data.paras

    def section_paras(self, *keys: str) -> list[Para]:
        return [p for p in self.paras if p.section in keys and not p.is_heading]

    def section_text(self, *keys: str) -> str:
        return "\n".join(p.body for p in self.section_paras(*keys))

    def heading_rest(self, key: str) -> str:
        for k, _, rest in self.headings:
            if k == key:
                return rest
        return ""

    def has(self, key: str) -> bool:
        return any(k == key for k, _, _ in self.headings)

    @property
    def description_keys(self) -> tuple[str, ...]:
        return ("field", "prior_art", "summary", "drawings", "embodiments")

    @property
    def abstract_text(self) -> str:
        if self.has("abstract_zh"):
            return self.section_text("abstract_zh")
        return self.section_text("abstract")

    @property
    def title(self) -> str:
        t = self.heading_rest("title")
        return t or (self.section_paras("title")[0].body if self.section_paras("title") else "")


def build_spec(path: str, rules: dict) -> Spec:
    data = read_docx(path)
    spec = Spec(data=data, rules=rules)
    req = [(s["key"], re.compile(s["pattern"])) for s in rules["sections"]["required"]]
    opt = [(s["key"], re.compile(s["pattern"])) for s in rules["sections"].get("optional", [])]

    current = None
    in_abstract = False
    for p in data.paras:
        text = p.text.strip()
        matched = None
        for key, pat in req + opt:
            m = pat.match(text)
            if m:
                matched = (key, text[m.end():].strip())
                break
        if matched:
            key, rest = matched
            if key in ("abstract",):
                in_abstract = True
            # 摘要頁內再次出現的發明名稱屬於摘要，不算重複段落
            if in_abstract and key in ("title", "title_en"):
                key = "abstract_title"
            p.is_heading = True
            p.section = key
            spec.headings.append((key, p.idx, rest))
            current = key
            continue
        p.section = current

        # 段號：Word 自動編號優先，其次純文字
        if p.auto_label and PARA_NO.match(p.auto_label):
            p.number = int(PARA_NO.match(p.auto_label).group(1))
            p.number_source = "auto"
        elif PARA_NO.match(text):
            p.number = int(PARA_NO.match(text).group(1))
            p.number_source = "text"

    # 請求項初稿：文件可以沒有任何段落標題，整份視為申請專利範圍
    if rules.get("_stage") == "claims" and not spec.has("claims"):
        for p in data.paras:
            if not p.is_heading:
                p.section = "claims"
                p.number, p.number_source = None, None
        spec.headings.append(("claims", -1, ""))

    spec.claims = parse_claims(spec)
    return spec


def parse_claims(spec: Spec) -> list[Claim]:
    rc = spec.rules["claims"]
    starts = [re.compile(x) for x in rc["start_patterns"]]
    claims: list[Claim] = []
    for p in spec.section_paras("claims"):
        label = (p.auto_label or "") + p.text
        m = next((s.match(label.strip()) for s in starts if s.match(label.strip())), None)
        if m:
            body = label.strip()[m.end():].strip()
            claims.append(Claim(num=int(m.group(1)), text=body, para_idx=p.idx))
        elif claims and p.text:
            claims[-1].text += p.text
    for c in claims:
        _parse_dependency(c, rc)
    return claims


def _parse_dependency(c: Claim, rc: dict) -> None:
    pre_m = re.search(rc["preamble_end"], c.text)
    c.preamble = c.text[: pre_m.start()] if pre_m else c.text
    ref_re = re.compile(rc["ref_pattern"])
    cont_re = re.compile(rc["list_continuation"])
    m = ref_re.search(c.preamble)
    if not m:
        return
    refs: list[int] = []
    a, b = int(m.group(1)), m.group(2)
    refs += list(range(a, int(b) + 1)) if b else [a]
    end = m.end()
    while True:
        m2 = cont_re.match(c.preamble[end:])
        if not m2:
            break
        refs.append(int(m2.group(1)))
        end += m2.end()
        m3 = re.match(r"\s*項", c.preamble[end:])
        if m3:
            end += m3.end()
    c.refs = refs
    # 依附語句往後多取一段，用於判斷「任一」等擇一字樣
    c.ref_text = c.preamble[m.start(): min(len(c.preamble), end + 8)]


__all__ = ["Spec", "Claim", "build_spec", "read_docx"]
