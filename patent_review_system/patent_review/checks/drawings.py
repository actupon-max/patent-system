"""D. 圖式 PDF：尺寸、方向、旋轉、字型嵌入、文字層、色彩、解析度、標號字高、圖號。"""
from __future__ import annotations

from ..model import Issue, Result
from ..pdf_reader import PdfData

F = "圖式"


def run(pdf: PdfData, rules: dict, res: Result) -> None:
    cfg = rules["pdf"]
    basis = cfg["basis"]
    size = cfg["page_size_mm"]
    orients = set()
    for pg in pdf.pages:
        loc = f"第{pg.num}頁"
        w, h = pg.width_mm, pg.height_mm
        if pg.rotate in (90, 270):
            w, h = h, w
        ok = (abs(w - size["width"]) <= size["tolerance"] and abs(h - size["height"]) <= size["tolerance"]) or \
             (abs(h - size["width"]) <= size["tolerance"] and abs(w - size["height"]) <= size["tolerance"])
        if not ok:
            res.add(Issue(F, loc, "D01", "頁面尺寸不是 A4", actual=f"{w:.0f}×{h:.0f}mm",
                          expected=f"{size['width']}×{size['height']}mm", severity="必改", basis=basis))
        orients.add("直式" if h >= w else "橫式")
        if cfg.get("require_portrait") and w > h:
            res.add(Issue(F, loc, "D01", "頁面為橫式", actual="橫式", expected="直式", severity="必改", basis=basis))
        if pg.rotate:
            res.add(Issue(F, loc, "D02", "頁面設有 /Rotate 旋轉", actual=f"{pg.rotate}°", expected="0°",
                          severity=cfg["rotate_severity"], basis=basis))
        for name, emb in pg.fonts:
            if not emb:
                res.add(Issue(F, loc, "D03", "字型未嵌入", actual=name, expected="嵌入字型",
                              severity=cfg["font_embedded_severity"], basis=basis))
        if not pg.has_text:
            msg = "無文字層（點陣圖），已以 OCR 擷取符號，請人工核對" if pg.ocr else \
                "無文字層（點陣圖），未安裝 OCR，圖中符號無法自動擷取"
            res.add(Issue(F, loc, "D04", msg, actual="無文字層", expected="有文字層或 OCR 結果",
                          severity=cfg["no_text_layer_severity"], basis=basis))
        # 色彩
        if "color" in pg.vector_colors or any(im.get("actual") == "color" for im in pg.images):
            res.add(Issue(F, loc, "D05", "圖式含彩色", actual="彩色", expected="黑白",
                          severity=cfg["color_severity"], basis=basis))
        elif "gray" in pg.vector_colors or any(im.get("actual") == "gray" for im in pg.images):
            res.add(Issue(F, loc, "D05", "圖式含灰階／網底", actual="灰階", expected="純黑白線條",
                          severity=cfg["gray_severity"], basis=basis))
        for im in pg.images:
            dpi = min(im["x_ppi"], im["y_ppi"])
            if dpi < cfg["min_dpi"]:
                res.add(Issue(F, loc, "D06", "影像解析度不足", actual=f"{dpi} dpi（{im['width']}×{im['height']}）",
                              expected=f"≥ {cfg['min_dpi']} dpi", severity="必改", basis=basis))
        # 標號字高
        marks = pg.symbols + [w for _, w in pg.labels]
        if marks:
            low = min(marks, key=lambda w: w.height_mm(cfg["cap_height_ratio"]))
            hmm = low.height_mm(cfg["cap_height_ratio"])
            if hmm + 1e-6 < cfg["min_label_height_mm"]:
                n = sum(1 for w in marks if w.height_mm(cfg["cap_height_ratio"]) + 1e-6 < cfg["min_label_height_mm"])
                res.add(Issue(F, loc, "D07", f"標號字高不足（{n} 個）", actual=f"最小 {hmm:.1f}mm（{low.text}）",
                              expected=f"≥ {cfg['min_label_height_mm']}mm",
                              severity="必改" if not pg.ocr else "需人工確認", basis=basis))
        # 圖號
        if (pg.words or pg.has_text) and not pg.labels:
            res.add(Issue(F, loc, "D08", "此頁找不到圖號（圖n）", actual="無", expected="例如「圖1」",
                          severity="必改" if pg.has_text else "需人工確認", basis=basis))
        for f, lw in pg.labels:
            others = [w for w in pg.words if w is not lw and not (w.x0 >= lw.x0 - 0.1 and w.x1 <= lw.x1 + 0.1
                                                                  and abs(w.top - lw.top) < 1)]
            near = [w for w in others if lw.gap_mm(w) < cfg["label_min_gap_mm"]]
            if near:
                res.add(Issue(F, f"{loc} 圖{f}", "D09", "圖號與其他標號距離過近",
                              actual=f"與「{near[0].text}」相距 {lw.gap_mm(near[0]):.1f}mm",
                              expected=f"≥ {cfg['label_min_gap_mm']}mm", severity="建議", basis=basis))
    if len(orients) > 1:
        res.add(Issue(F, "全部圖式", "D01", "頁面方向不一致", actual="、".join(sorted(orients)), expected="一致",
                      severity="必改", basis=basis))
    for n in pdf.notes:
        res.add(Issue(F, "全部圖式", "D00", n, severity="資訊", basis=basis))
