"""產生合成測試樣本（不含任何真實案件內容）。

    python tests/fixtures/make_samples.py <輸出資料夾>

clean          ：格式正確的完整案件，必改應為 0
case1_like     ：仿第一案已知問題（圖4 未引用、請求項8 前置基礎重複）
case2_like     ：仿第二案已知問題（半形括號）
dirty          ：編修殘留（螢光、彩色字、追蹤修訂、空白段落）與段號錯誤
claims_only    ：只有請求項的初稿
autonum        ：段號使用 Word 自動編號
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"

BASE = {
    "title": "光纖感測裝置",
    "field": ["本發明係關於一種光纖感測裝置，特別是關於一種可量測溫度之光纖感測裝置。"],
    "prior": ["習知的溫度感測器容易受到電磁干擾，量測結果不穩定。"],
    "summary": ["本發明提供一種光纖感測裝置，包含一光纖及一殼體，殼體具有一開口供光纖穿過。"],
    "drawings": ["圖1為本發明光纖感測裝置之立體圖。", "圖2為本發明光纖感測裝置之剖面圖。",
                 "圖3為本發明光纖之示意圖。", "圖4為本發明殼體之示意圖。"],
    "embodiments": [
        "請參閱圖1及圖2，光纖感測裝置1包含光纖10及殼體20。",
        "請參閱圖3，光纖10具有纖芯11及包層12，纖芯11被包層12包覆。",
        "請參閱圖4，殼體20具有開口21，光纖10穿過開口21。",
    ],
    "symbols": ["1：光纖感測裝置", "10：光纖", "11：纖芯", "12：包層", "20：殼體", "21：開口"],
    "claims": [
        "一種光纖感測裝置，包含：一光纖；以及一殼體，具有一開口，該光纖穿過該開口。",
        "如請求項1所述之光纖感測裝置，其中該光纖具有一纖芯及一包層。",
        "如請求項2所述之光纖感測裝置，其中該包層包覆該纖芯。",
        "如請求項1所述之光纖感測裝置，其中該殼體為金屬材質。",
        "如請求項1或2所述之光纖感測裝置，其中該開口為圓形。",
        "如請求項1所述之光纖感測裝置，其中該光纖為單模光纖。",
        "如請求項3所述之光纖感測裝置，其中該纖芯之直徑為9μm。",
        "如請求項1所述之光纖感測裝置，其中該開口位於該殼體之一側。",
    ],
    "abstract": "本發明提供一種光纖感測裝置，包含一光纖及一殼體，殼體具有一開口，光纖穿過開口，可量測溫度並避免電磁干擾。",
    "rep": "圖1",
    "rep_symbols": ["1：光纖感測裝置", "10：光纖", "20：殼體"],
}

# 每頁圖：(圖號, [符號])
FIGS = [("1", ["1", "10", "20"]), ("2", ["10", "20", "21"]), ("3", ["10", "11", "12"]), ("4", ["20", "21"])]


def _setup(doc):
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(12)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "新細明體")
    st.paragraph_format.line_spacing = 1.5
    st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY


def build_docx(path: Path, d: dict, autonum: bool = False) -> Document:
    doc = Document()
    _setup(doc)
    n = [0]

    def para(t, numbered=True):
        if numbered and not autonum:
            n[0] += 1
            t = f"【{n[0]:04d}】{t}"
        p = doc.add_paragraph(t)
        if numbered and autonum:
            _apply_autonum(doc, p)
        return p

    para(f"【發明名稱】{d['title']}", False)
    for key, head in (("field", "技術領域"), ("prior", "先前技術"), ("summary", "發明內容"),
                      ("drawings", "圖式簡單說明"), ("embodiments", "實施方式")):
        para(f"【{head}】", False)
        for t in d[key]:
            para(t)
    para("【符號說明】", False)
    for t in d["symbols"]:
        para(t, False)
    para("【申請專利範圍】", False)
    for i, t in enumerate(d["claims"], start=1):
        para(f"【第{i}項】{t}", False)
    para("【摘要】", False)
    para(d["abstract"], False)
    para(f"【代表圖】{d['rep']}", False)
    para("【代表圖之符號簡單說明】", False)
    for t in d["rep_symbols"]:
        para(t, False)
    doc.save(path)
    return doc


def _apply_autonum(doc, p):
    """把段落套上 lvlText「【%1】」、四位數補零的自動編號。"""
    numbering = doc.part.numbering_part.element
    if numbering.find(qn("w:num") + "[@" + qn("w:numId") + "='99']") is None:
        an = OxmlElement("w:abstractNum")
        an.set(qn("w:abstractNumId"), "99")
        lvl = OxmlElement("w:lvl")
        lvl.set(qn("w:ilvl"), "0")
        for tag, attrs in (("w:start", {"w:val": "1"}), ("w:numFmt", {"w:val": "custom", "w:format": "0001, 0002, 0003, ..."}),
                           ("w:lvlText", {"w:val": "【%1】"})):
            e = OxmlElement(tag)
            for k, v in attrs.items():
                e.set(qn(k), v)
            lvl.append(e)
        an.append(lvl)
        first_num = numbering.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(an)
        else:
            numbering.append(an)
        num = OxmlElement("w:num")
        num.set(qn("w:numId"), "99")
        a = OxmlElement("w:abstractNumId")
        a.set(qn("w:val"), "99")
        num.append(a)
        numbering.append(num)
    ppr = p._p.get_or_add_pPr()
    numpr = OxmlElement("w:numPr")
    il = OxmlElement("w:ilvl")
    il.set(qn("w:val"), "0")
    nid = OxmlElement("w:numId")
    nid.set(qn("w:val"), "99")
    numpr.append(il)
    numpr.append(nid)
    ppr.insert(0, numpr)


def build_pdf(path: Path, figs=FIGS, label_pt: float = 14, sym_pt: float = 14, color=False):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(TTFont("WQY", FONT_PATH, subfontIndex=0))
    c = canvas.Canvas(str(path), pagesize=A4, initialFontName="WQY")
    w, h = A4
    for label, syms in figs:
        c.setStrokeColorRGB(1, 0, 0) if color else c.setStrokeColorRGB(0, 0, 0)
        c.rect(150, 400, 300, 250)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("WQY", sym_pt)
        for k, s in enumerate(syms):
            c.line(460, 620 - k * 60, 500, 640 - k * 60)
            c.drawString(505, 640 - k * 60, s)
        c.setFont("WQY", label_pt)
        c.drawString(w / 2 - 15, 300, f"圖{label}")
        c.showPage()
    c.save()


def build_raster_pdf(path: Path, dpi: int = 150, color=True):
    """點陣圖式：一頁 A4 影像、無文字層。"""
    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    w_in, h_in = 4, 3
    im = Image.new("RGB", (w_in * dpi, h_in * dpi), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, w_in * dpi - 20, h_in * dpi - 20], outline=(255, 0, 0) if color else (0, 0, 0), width=4)
    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawImage(ImageReader(im), 100, 400, width=w_in * 72, height=h_in * 72)
    c.showPage()
    c.save()


def variants() -> dict[str, dict]:
    v = {"clean": copy.deepcopy(BASE)}

    c1 = copy.deepcopy(BASE)
    # 圖4 未在實施方式引用
    c1["embodiments"][2] = "殼體20具有開口21，光纖10穿過開口21。"
    # 請求項8 重複以「一」引入光纖
    c1["claims"][7] = "如請求項1所述之光纖感測裝置，更包含一光纖，設置於該殼體內。"
    v["case1_like"] = c1

    c2 = copy.deepcopy(BASE)
    c2["embodiments"][1] = "請參閱圖3，光纖10具有纖芯11及包層12，纖芯11被包層12包覆(如圖3所示)。"
    c2["claims"][0] = "一種光纖感測裝置，包含：一光纖(10)；以及一殼體(20)，具有一開口(21)，該光纖穿過該開口。"
    v["case2_like"] = c2

    v["dirty"] = copy.deepcopy(BASE)
    v["autonum"] = copy.deepcopy(BASE)
    return v


def make_dirty(path: Path):
    """在 clean 版本上加入編修殘留與段號錯誤。"""
    doc = Document(path)
    paras = doc.paragraphs
    target = next(p for p in paras if p.text.startswith("【0009】"))
    r = target.add_run("（待確認）")
    hl = OxmlElement("w:highlight")
    hl.set(qn("w:val"), "yellow")
    r._r.get_or_add_rPr().append(hl)
    target2 = next(p for p in paras if p.text.startswith("【0010】"))
    r2 = target2.add_run("紅字備註")
    r2.font.color.rgb = __import__("docx.shared", fromlist=["RGBColor"]).RGBColor(0xFF, 0, 0)
    # 追蹤修訂（插入）
    ins = OxmlElement("w:ins")
    ins.set(qn("w:id"), "1")
    ins.set(qn("w:author"), "tester")
    rr = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "新增文字"
    rr.append(t)
    ins.append(rr)
    target2._p.append(ins)
    # 空白段落
    target2._p.addnext(OxmlElement("w:p"))
    # 段號跳號：把【0006】改成【0007】
    p6 = next(p for p in paras if p.text.startswith("【0006】"))
    for run in p6.runs:
        run.text = run.text.replace("【0006】", "【0007】")
    doc.save(path)


def make_claims_only(path: Path):
    doc = Document()
    _setup(doc)
    for t in ["1. 一種光纖感測裝置，包含：一光纖；以及一殼體，具有一開口，該光纖穿過該開口。",
              "2. 如請求項1所述之光纖感測裝置，其中該光纖具有一纖芯。",
              "3. 如請求項1所述之光纖感測裝置，更包含一光纖，設置於該殼體內。",
              "4. 如請求項1及2所述之光纖感測裝置，其中該蓋板覆蓋該開口。",
              "5. 如請求項6所述之感測器，其中該殼體為金屬。"]:
        doc.add_paragraph(t)
    doc.save(path)


def main(out: str) -> None:
    out_dir = Path(out)
    for name, d in variants().items():
        case = out_dir / name
        case.mkdir(parents=True, exist_ok=True)
        build_docx(case / f"{name}_說明書.docx", d, autonum=(name == "autonum"))
        build_pdf(case / f"{name}_圖式.pdf")
    make_dirty(out_dir / "dirty" / "dirty_說明書.docx")
    (out_dir / "claims_only").mkdir(parents=True, exist_ok=True)
    make_claims_only(out_dir / "claims_only" / "claims_only_請求項.docx")
    # 圖式問題：彩色、字太小
    bad = out_dir / "bad_pdf"
    bad.mkdir(parents=True, exist_ok=True)
    build_docx(bad / "bad_pdf_說明書.docx", BASE)
    build_pdf(bad / "bad_pdf_圖式.pdf", label_pt=14, sym_pt=7, color=True)
    raster = out_dir / "raster_pdf"
    raster.mkdir(parents=True, exist_ok=True)
    build_docx(raster / "raster_pdf_說明書.docx", BASE)
    build_raster_pdf(raster / "raster_pdf_圖式.pdf")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "samples/synthetic")
