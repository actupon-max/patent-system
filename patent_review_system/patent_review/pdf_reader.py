"""讀取圖式 PDF：頁面、文字層（或 OCR）、圖號、符號、字型嵌入、影像解析度與色彩。"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

PT_TO_MM = 25.4 / 72
HAVE_POPPLER = bool(shutil.which("pdfimages") and shutil.which("pdffonts"))
SYMBOL_RE = re.compile(r"^[A-Za-z]?\d{1,4}[a-z]?['′’]?$")


@dataclass
class Word:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size_pt: float | None = None   # 字級（文字層）；OCR 時為字高換算值

    def height_mm(self, cap_ratio: float) -> float:
        if self.size_pt:
            return self.size_pt * cap_ratio * PT_TO_MM
        return (self.bottom - self.top) * PT_TO_MM

    def gap_mm(self, o: "Word") -> float:
        dx = max(0.0, max(o.x0 - self.x1, self.x0 - o.x1))
        dy = max(0.0, max(o.top - self.bottom, self.top - o.bottom))
        return (dx * dx + dy * dy) ** 0.5 * PT_TO_MM


@dataclass
class PdfPage:
    num: int
    width_mm: float
    height_mm: float
    rotate: int
    has_text: bool
    ocr: bool = False
    labels: list[tuple[str, Word]] = field(default_factory=list)   # (圖號, 位置)
    symbols: list[Word] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    vector_colors: set = field(default_factory=set)               # 'color' / 'gray'
    images: list[dict] = field(default_factory=list)
    fonts: list[tuple[str, bool]] = field(default_factory=list)


@dataclass
class PdfData:
    path: str
    pages: list[PdfPage]
    ocr_available: bool
    notes: list[str] = field(default_factory=list)


def _pixels(im):
    """RGB 影像的像素 (r, g, b)。"""
    b = im.tobytes()
    return zip(b[0::3], b[1::3], b[2::3])


def _color_kind(c, tol: int) -> str | None:
    """回傳 None（黑白）、'gray'、'color'。"""
    if c is None:
        return None
    if isinstance(c, (int, float)):
        c = (c,)
    try:
        c = tuple(float(x) for x in c)
    except (TypeError, ValueError):
        return "color"   # pattern 等特殊色彩
    t = tol / 255
    if len(c) == 1:
        g = c[0]
    elif len(c) == 3:
        if max(c) - min(c) > t:
            return "color"
        g = sum(c) / 3
    elif len(c) == 4:
        if max(c[:3]) > t:
            return "color"
        g = 1 - c[3]
    else:
        return "color"
    return None if g <= t or g >= 1 - t else "gray"


def _pdfimages_list(path: str) -> list[dict]:
    if not shutil.which("pdfimages"):
        return []
    out = subprocess.run(["pdfimages", "-list", path], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines()[2:]:
        f = line.split()
        if len(f) < 14:
            continue
        try:
            rows.append({"page": int(f[0]), "num": int(f[1]), "type": f[2], "width": int(f[3]), "height": int(f[4]),
                         "color": f[5], "bpc": int(f[7]), "x_ppi": int(f[12]), "y_ppi": int(f[13])})
        except ValueError:
            continue
    return rows


def _image_is_color(path: str, page: int, tol: int) -> str | None:
    """解出影像檢查實際像素：None 黑白、'gray'、'color'。"""
    try:
        from PIL import Image
    except ImportError:
        return "unknown"
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdfimages", "-png", "-f", str(page), "-l", str(page), path, f"{td}/img"],
                       capture_output=True)
        files = sorted(Path(td).glob("img-*.png"))
        if not files:
            return "unknown"
        kinds = set()
        for f in files:
            im = Image.open(f).convert("RGB")
            im.thumbnail((400, 400))
            for r, g, b in _pixels(im):
                if max(r, g, b) - min(r, g, b) > tol:
                    return "color"
                v = (r + g + b) / 3
                if tol < v < 255 - tol:
                    kinds.add("gray")
        return "gray" if kinds else None


def _fonts(path: str, page: int) -> list[tuple[str, bool]]:
    if not shutil.which("pdffonts"):
        return []
    out = subprocess.run(["pdffonts", "-f", str(page), "-l", str(page), path], capture_output=True, text=True).stdout
    res = []
    for line in out.splitlines()[2:]:
        m = re.match(r"^(\S+)\s+.*?\s(yes|no)\s+(yes|no)\s+(yes|no)\s+\d+\s+\d+\s*$", line)
        if m:
            res.append((m.group(1), m.group(2) == "yes"))
    return res


# ── 沒有 poppler（例如雲端平台）時的替代做法 ──
def _fonts_pypdf(rp) -> list[tuple[str, bool]]:
    out = []
    try:
        fonts = rp.get("/Resources", {}).get_object().get("/Font", {}).get_object()
    except Exception:
        return out
    for ref in fonts.values():
        f = ref.get_object()
        name = str(f.get("/BaseFont", "?")).lstrip("/")
        if f.get("/Subtype") == "/Type3":
            out.append((name, True))
            continue
        desc = f.get("/FontDescriptor")
        if desc is None and f.get("/DescendantFonts"):
            desc = f["/DescendantFonts"][0].get_object().get("/FontDescriptor")
        desc = desc.get_object() if desc is not None else {}
        out.append((name, any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3"))))
    return out


def _images_fallback(rp, pg, num: int, tol: int) -> list[dict]:
    rows = []
    for k, im in enumerate(pg.images, start=1):
        sw, sh = im.get("srcsize") or (0, 0)
        w_pt, h_pt = max(im["width"], 0.01), max(im["height"], 0.01)
        rows.append({"page": num, "num": k, "width": int(sw), "height": int(sh), "color": "?", "bpc": im.get("bits") or 0,
                     "x_ppi": int(sw / (w_pt / 72)), "y_ppi": int(sh / (h_pt / 72))})
    kind = None
    try:
        for img in rp.images:
            pil = img.image.convert("RGB")
            pil.thumbnail((400, 400))
            for r, g, b in _pixels(pil):
                if max(r, g, b) - min(r, g, b) > tol:
                    kind = "color"
                    break
                if tol < (r + g + b) / 3 < 255 - tol:
                    kind = kind or "gray"
            if kind == "color":
                break
    except Exception:
        kind = "unknown"
    for r in rows:
        r["actual"] = kind
    return rows


def _ocr_words(path: str, page: int, cfg: dict) -> list[Word]:
    with tempfile.TemporaryDirectory() as td:
        dpi = cfg["dpi"]
        subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page), "-png", path, f"{td}/p"],
                       capture_output=True)
        imgs = sorted(Path(td).glob("p*.png"))
        if not imgs:
            return []
        tsv = subprocess.run(["tesseract", str(imgs[0]), "stdout", "-l", cfg["lang"], "--psm", "11", "tsv"],
                             capture_output=True, text=True).stdout
    scale = 72 / dpi
    words = []
    for line in tsv.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 12 or not f[11].strip():
            continue
        try:
            conf = float(f[10])
        except ValueError:
            continue
        if conf < 50:
            continue
        x, y, w, h = (int(v) for v in f[6:10])
        words.append(Word(f[11].strip(), x * scale, y * scale, (x + w) * scale, (y + h) * scale))
    return words


def read_pdf(path: str, rules: dict) -> PdfData:
    cfg = rules["pdf"]
    label_re = re.compile(rules["figures"]["pdf_label_pattern"])
    ocr_ok = bool(shutil.which("tesseract") and shutil.which("pdftoppm")) and cfg["ocr"].get("enabled", True)
    images = _pdfimages_list(path) if HAVE_POPPLER else []
    reader = PdfReader(path)
    pages: list[PdfPage] = []
    with pdfplumber.open(path) as pdf:
        for i, pg in enumerate(pdf.pages, start=1):
            rp = reader.pages[i - 1]
            box = rp.mediabox
            page = PdfPage(num=i, width_mm=float(box.width) * PT_TO_MM, height_mm=float(box.height) * PT_TO_MM,
                           rotate=int(rp.get("/Rotate", 0) or 0) % 360, has_text=bool(pg.chars))
            # 文字層
            if pg.chars:
                for w in pg.extract_words(extra_attrs=["size"], keep_blank_chars=False):
                    page.words.append(Word(w["text"], w["x0"], w["top"], w["x1"], w["bottom"], w.get("size")))
            elif ocr_ok:
                page.words = _ocr_words(path, i, cfg["ocr"])
                page.ocr = True
            # 圖號（可能拆成「圖」「1」兩個字）
            used = set()
            for j, w in enumerate(page.words):
                cand = w.text
                nxt = page.words[j + 1] if j + 1 < len(page.words) else None
                m = label_re.fullmatch(cand)
                if not m and nxt and abs(nxt.top - w.top) < 3:
                    m = label_re.fullmatch(cand + nxt.text) or label_re.fullmatch(cand + " " + nxt.text)
                    if m:
                        used.add(j + 1)
                        w = Word(cand + nxt.text, w.x0, min(w.top, nxt.top), nxt.x1, max(w.bottom, nxt.bottom), w.size_pt)
                if m:
                    used.add(j)
                    page.labels.append((next(g for g in m.groups() if g).upper(), w))
            for j, w in enumerate(page.words):
                if j not in used and SYMBOL_RE.match(w.text):
                    page.symbols.append(w)
            # 向量圖形色彩
            for obj in pg.chars + pg.lines + pg.rects + pg.curves:
                for key in ("stroking_color", "non_stroking_color"):
                    k = _color_kind(obj.get(key), cfg["gray_tolerance"])
                    if k:
                        page.vector_colors.add(k)
            if not HAVE_POPPLER:
                page.images = _images_fallback(rp, pg, i, cfg["gray_tolerance"])
                page.fonts = _fonts_pypdf(rp)
                pages.append(page)
                continue
            page.images = [im for im in images if im["page"] == i]
            decoded = None
            for im in page.images:
                if im["color"] == "gray" and im["bpc"] == 1:
                    im["actual"] = None
                elif im["color"] == "gray":
                    im["actual"] = "gray"
                else:
                    if decoded is None:  # 同頁影像一次解出
                        decoded = _image_is_color(path, i, cfg["gray_tolerance"]) or "bw"
                    im["actual"] = None if decoded == "bw" else decoded
            page.fonts = _fonts(path, i)
            pages.append(page)
    notes = []
    if not ocr_ok:
        notes.append("未安裝 tesseract 或已停用 OCR：無文字層的頁面無法擷取符號")
    return PdfData(path=path, pages=pages, ocr_available=ocr_ok, notes=notes)
