"""讀取說明書 .docx：段落文字、段號（含 Word 自動編號）、有效格式與編修殘留。

只讀不寫，原檔不會被修改。
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field

from docx import Document
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"w": W, "a": A}


def q(tag: str) -> str:
    p, t = tag.split(":")
    return f"{{{NS[p]}}}{t}"


@dataclass
class RunInfo:
    text: str
    east_asia_font: str | None
    ascii_font: str | None
    size_pt: float | None
    color: str | None
    highlight: str | None
    hidden: bool


@dataclass
class Para:
    idx: int                       # 全文段落序號（0 起）
    text: str                      # 段落文字（不含自動編號標籤）
    style: str = ""
    auto_label: str | None = None  # Word 自動編號產生的標籤，如【0001】
    number: int | None = None      # 段號數值
    number_source: str | None = None  # text / auto
    section: str | None = None     # 所屬段落 key（由 structure 填入）
    is_heading: bool = False
    in_table: bool = False
    in_textbox: bool = False
    alignment: str | None = None
    line_rule: str | None = None
    line_value: float | None = None  # multiple: 倍數；exact/atLeast: pt
    runs: list[RunInfo] = field(default_factory=list)

    @property
    def body(self) -> str:
        """去掉純文字段號後的內容。"""
        return re.sub(r"^【\d{4}】\s*", "", self.text).strip()

    def loc(self) -> str:
        if self.number is not None:
            return f"【{self.number:04d}】"
        return f"第{self.idx + 1}段"


@dataclass
class DocxData:
    path: str
    paras: list[Para]
    tracked_changes: list[tuple[int, str, str]]  # (段落序號, 類型, 文字)
    comments: list[tuple[int | None, str]]       # (段落序號, 註解內容)
    pages: int | None
    risky_objects: list[tuple[int, str]]         # (段落序號, 物件類型) 轉檔風險


class _StyleResolver:
    """沿著樣式繼承鏈解出段落／文字的有效格式。"""

    def __init__(self, doc):
        self.styles = {}
        self.defaults_rpr = None
        self.defaults_ppr = None
        styles_el = doc.styles.element
        for s in styles_el.findall(q("w:style")):
            self.styles[s.get(q("w:styleId"))] = s
        dd = styles_el.find(q("w:docDefaults"))
        if dd is not None:
            self.defaults_rpr = dd.find(f"{q('w:rPrDefault')}/{q('w:rPr')}")
            self.defaults_ppr = dd.find(f"{q('w:pPrDefault')}/{q('w:pPr')}")
        self.default_pstyle = None
        for sid, s in self.styles.items():
            if s.get(q("w:type")) == "paragraph" and s.get(q("w:default")) in ("1", "true"):
                self.default_pstyle = sid
        self.theme_fonts = self._theme_fonts(doc)

    @staticmethod
    def _theme_fonts(doc) -> dict:
        fonts = {}
        try:
            for rel in doc.part.rels.values():
                if rel.reltype.endswith("/theme"):
                    root = etree.fromstring(rel.target_part.blob)
                    for kind in ("major", "minor"):
                        f = root.find(f".//{q('a:' + kind + 'Font')}")
                        if f is None:
                            continue
                        latin = f.find(q("a:latin"))
                        ea = f.find(q("a:ea"))
                        hant = [x for x in f.findall(q("a:font")) if x.get("script") == "Hant"]
                        fonts[f"{kind}HAnsi"] = latin.get("typeface") if latin is not None else None
                        fonts[f"{kind}Ascii"] = fonts[f"{kind}HAnsi"]
                        ea_face = ea.get("typeface") if ea is not None else ""
                        fonts[f"{kind}EastAsia"] = ea_face or (hant[0].get("typeface") if hant else None)
        except Exception:  # 主題解析失敗不影響其他檢查
            pass
        return fonts

    def chain(self, style_id: str | None) -> list:
        out, seen = [], set()
        while style_id and style_id in self.styles and style_id not in seen:
            seen.add(style_id)
            s = self.styles[style_id]
            out.append(s)
            b = s.find(q("w:basedOn"))
            style_id = b.get(q("w:val")) if b is not None else None
        return out

    def style_name(self, style_id: str | None) -> str:
        if style_id and style_id in self.styles:
            n = self.styles[style_id].find(q("w:name"))
            return n.get(q("w:val")) if n is not None else style_id
        return ""

    def rpr_chain(self, run_el, pstyle_id) -> list:
        """由近到遠：run 直接格式 → 字元樣式 → 段落樣式 → 文件預設。"""
        chain = []
        rpr = run_el.find(q("w:rPr"))
        if rpr is not None:
            chain.append(rpr)
            rs = rpr.find(q("w:rStyle"))
            if rs is not None:
                chain += [s.find(q("w:rPr")) for s in self.chain(rs.get(q("w:val")))]
        chain += [s.find(q("w:rPr")) for s in self.chain(pstyle_id or self.default_pstyle)]
        chain.append(self.defaults_rpr)
        return [c for c in chain if c is not None]

    def ppr_chain(self, p_el, pstyle_id) -> list:
        chain = [p_el.find(q("w:pPr"))]
        chain += [s.find(q("w:pPr")) for s in self.chain(pstyle_id or self.default_pstyle)]
        chain.append(self.defaults_ppr)
        return [c for c in chain if c is not None]

    @staticmethod
    def first(chain, tag, attr=None):
        for el in chain:
            x = el.find(q(tag))
            if x is not None:
                return x if attr is None else x.get(q(attr))
        return None

    def font(self, chain, kind: str) -> str | None:
        """kind = eastAsia / ascii"""
        for el in chain:
            rf = el.find(q("w:rFonts"))
            if rf is None:
                continue
            v = rf.get(q(f"w:{kind}"))
            if v:
                return v
            th = rf.get(q(f"w:{kind}Theme"))
            if th:
                return self.theme_fonts.get(th) or f"theme:{th}"
        return None


class _Numbering:
    """把 Word 自動編號換算成實際顯示的標籤。"""

    def __init__(self, doc):
        self.num_to_abs, self.overrides, self.levels = {}, {}, {}
        self.counters: dict[tuple, int] = {}
        self.started: set = set()
        try:
            root = doc.part.numbering_part.element
        except Exception:
            return
        for an in root.findall(q("w:abstractNum")):
            aid = an.get(q("w:abstractNumId"))
            for lvl in an.findall(q("w:lvl")):
                il = int(lvl.get(q("w:ilvl")))
                start = lvl.find(q("w:start"))
                fmt = lvl.find(q("w:numFmt"))
                if fmt is None:
                    # 智慧局官方空白表把「0001, 0002…」寫在 mc:AlternateContent/mc:Choice 內，
                    # 外層沒有 w:numFmt；取第一個（Choice 在 Fallback 之前，即 Word 實際顯示者）
                    fmt = next(lvl.iter(q("w:numFmt")), None)
                txt = lvl.find(q("w:lvlText"))
                self.levels[(aid, il)] = {
                    "start": int(start.get(q("w:val"))) if start is not None else 1,
                    "fmt": fmt.get(q("w:val")) if fmt is not None else "decimal",
                    "fmt_custom": fmt.get(q("w:format")) if fmt is not None else None,
                    "text": txt.get(q("w:val")) if txt is not None else "",
                }
        for n in root.findall(q("w:num")):
            nid = n.get(q("w:numId"))
            a = n.find(q("w:abstractNumId"))
            self.num_to_abs[nid] = a.get(q("w:val")) if a is not None else None
            for ov in n.findall(q("w:lvlOverride")):
                so = ov.find(q("w:startOverride"))
                if so is not None:
                    self.overrides[(nid, int(ov.get(q("w:ilvl"))))] = int(so.get(q("w:val")))

    def label(self, num_id: str, ilvl: int) -> str | None:
        aid = self.num_to_abs.get(num_id)
        lv = self.levels.get((aid, ilvl))
        if lv is None or num_id == "0":
            return None
        key = (aid, ilvl)
        if (num_id, ilvl) in self.overrides and (num_id, ilvl) not in self.started:
            self.counters[key] = self.overrides[(num_id, ilvl)] - 1
        self.started.add((num_id, ilvl))
        self.counters[key] = self.counters.get(key, lv["start"] - 1) + 1
        # 下層計數歸零
        for k in list(self.counters):
            if k[0] == aid and k[1] > ilvl:
                del self.counters[k]
        n = self.counters[key]
        if lv["fmt"] == "decimalZero":
            s = f"{n:02d}"
        elif lv["fmt"] == "custom" and lv["fmt_custom"] and set(lv["fmt_custom"].split(",")[0]) <= {"0", "1"}:
            width = len(lv["fmt_custom"].split(",")[0])
            s = f"{n:0{width}d}"
        else:
            s = str(n)
        return re.sub(r"%\d", s, lv["text"])


def _text_of(p_el) -> str:
    """段落文字：含插入、不含刪除與功能變數代碼、不含文字方塊內文字。"""
    out = []
    for t in p_el.iter(q("w:t"), q("w:tab"), q("w:br")):
        anc = t.getparent()
        skip = False
        while anc is not None and anc is not p_el:
            if anc.tag in (q("w:del"), q("w:txbxContent"), q("w:moveFrom")):
                skip = True
                break
            anc = anc.getparent()
        if skip:
            continue
        if t.tag == q("w:t"):
            out.append(t.text or "")
        elif t.tag == q("w:tab"):
            out.append("\t")
        elif t.tag == q("w:br"):
            # 段內換行（官方空白表的符號說明：同一段落逐行「符號:文字」）；保留為換行，避免前後兩行黏成一串
            out.append("\n")
    return "".join(out)


def _runs_in(p_el):
    for r in p_el.iter(q("w:r")):
        anc = r.getparent()
        ok = True
        while anc is not None and anc is not p_el:
            if anc.tag in (q("w:txbxContent"), q("w:del")):
                ok = False
                break
            anc = anc.getparent()
        if ok:
            yield r


def read_docx(path: str) -> DocxData:
    doc = Document(path)
    sr = _StyleResolver(doc)
    numbering = _Numbering(doc)
    body = doc.element.body

    paras: list[Para] = []
    tracked: list[tuple[int, str, str]] = []
    risky: list[tuple[int, str]] = []
    comment_anchor: dict[str, int] = {}

    def handle_p(p_el, in_table=False, in_textbox=False):
        idx = len(paras)
        ppr = p_el.find(q("w:pPr"))
        ps = ppr.find(q("w:pStyle")) if ppr is not None else None
        pstyle_id = ps.get(q("w:val")) if ps is not None else None
        para = Para(idx=idx, text=_text_of(p_el).strip(), style=sr.style_name(pstyle_id or sr.default_pstyle),
                    in_table=in_table, in_textbox=in_textbox)

        # 自動編號（段落或樣式上的 numPr）
        pchain = sr.ppr_chain(p_el, pstyle_id)
        num_pr = _StyleResolver.first(pchain, "w:numPr")
        if num_pr is not None:
            nid = num_pr.find(q("w:numId"))
            il = num_pr.find(q("w:ilvl"))
            if nid is not None:
                para.auto_label = numbering.label(nid.get(q("w:val")), int(il.get(q("w:val"))) if il is not None else 0)

        para.alignment = _StyleResolver.first(pchain, "w:jc", "w:val")
        for el in pchain:
            sp = el.find(q("w:spacing"))
            if sp is not None and sp.get(q("w:line")):
                rule = sp.get(q("w:lineRule")) or "auto"
                val = int(sp.get(q("w:line")))
                para.line_rule = "multiple" if rule == "auto" else rule
                para.line_value = val / 240 if rule == "auto" else val / 20
                break

        for r in _runs_in(p_el):
            txt = "".join((t.text or "") for t in r.findall(q("w:t")))
            if not txt:
                continue
            rchain = sr.rpr_chain(r, pstyle_id)
            sz = _StyleResolver.first(rchain, "w:sz", "w:val")
            hl = _StyleResolver.first(rchain[:1] if r.find(q("w:rPr")) is not None else [], "w:highlight", "w:val")
            shd = _StyleResolver.first(rchain[:1] if r.find(q("w:rPr")) is not None else [], "w:shd", "w:fill")
            if not hl and shd and shd.lower() not in ("auto", "ffffff"):
                hl = f"網底 {shd}"
            vanish = _StyleResolver.first(rchain, "w:vanish")
            para.runs.append(RunInfo(
                text=txt,
                east_asia_font=sr.font(rchain, "eastAsia"),
                ascii_font=sr.font(rchain, "ascii"),
                size_pt=int(sz) / 2 if sz else None,
                color=_StyleResolver.first(rchain, "w:color", "w:val"),
                highlight=hl if hl and hl != "none" else None,
                hidden=vanish is not None and vanish.get(q("w:val")) not in ("0", "false"),
            ))

        # 追蹤修訂
        for tag, kind in (("w:ins", "插入"), ("w:del", "刪除"), ("w:moveFrom", "移動"), ("w:moveTo", "移動"),
                          ("w:rPrChange", "格式變更"), ("w:pPrChange", "格式變更")):
            for el in p_el.iter(q(tag)):
                t = "".join(x.text or "" for x in el.iter(q("w:t"), q("w:delText")))
                tracked.append((idx, kind, t[:40]))
        for el in p_el.iter(q("w:commentRangeStart"), q("w:commentReference")):
            comment_anchor.setdefault(el.get(q("w:id")), idx)
        # 轉檔風險物件
        for tag, kind in (("w:object", "OLE 物件（例如舊式方程式）"), ("w:fldChar", "功能變數代碼"),
                          ("w:txbxContent", "文字方塊")):
            if p_el.find(f".//{q(tag)}") is not None:
                risky.append((idx, kind))
        if p_el.find(".//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath") is not None:
            risky.append((idx, "Word 方程式"))
        if ppr is not None and ppr.find(q("w:sectPr")) is not None:
            risky.append((idx, "分節符號"))
        paras.append(para)

        # 文字方塊內的段落另外收錄
        for tb in p_el.iter(q("w:txbxContent")):
            for inner in tb.findall(q("w:p")):
                handle_p(inner, in_textbox=True)

    for child in body:
        if child.tag == q("w:p"):
            handle_p(child)
        elif child.tag == q("w:tbl"):
            for p_el in child.iter(q("w:p")):
                handle_p(p_el, in_table=True)

    # 註解
    comments: list[tuple[int | None, str]] = []
    try:
        for rel in doc.part.rels.values():
            if rel.reltype.endswith("/comments"):
                root = etree.fromstring(rel.target_part.blob)
                for c in root.findall(q("w:comment")):
                    t = "".join(x.text or "" for x in c.iter(q("w:t")))
                    comments.append((comment_anchor.get(c.get(q("w:id"))), t[:60]))
    except Exception:
        pass
    if not comments and comment_anchor:
        comments = [(i, "") for i in comment_anchor.values()]

    pages = None
    try:
        with zipfile.ZipFile(path) as z:
            if "docProps/app.xml" in z.namelist():
                m = re.search(rb"<Pages>(\d+)</Pages>", z.read("docProps/app.xml"))
                pages = int(m.group(1)) if m else None
    except Exception:
        pass

    return DocxData(path=path, paras=paras, tracked_changes=tracked, comments=comments,
                    pages=pages, risky_objects=risky)
