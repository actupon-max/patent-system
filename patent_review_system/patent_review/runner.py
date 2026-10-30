"""依階段執行各組檢查，回傳 Result。"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import yaml

from . import __version__
from .checks import claims as B
from .checks import drawings as D
from .checks import semantic as E
from .checks import spec_format as A
from .checks import symbols as C
from .model import Result
from .pdf_reader import read_pdf
from .structure import build_spec

DEFAULT_RULES = Path(__file__).resolve().parent.parent / "rules.yaml"

A_GROUPS = {
    "sections": A.check_sections,
    "paragraph_numbers": A.check_paragraph_numbers,
    "typography": A.check_typography,
    "width": A.check_width,
    "units": A.check_units,
    "abstract": A.check_abstract,
    "residue": A.check_residue,
    "conversion": A.check_conversion_risk,
    "fees": A.check_fees,
}


def load_rules(path: str | None = None) -> dict:
    with open(path or DEFAULT_RULES, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _file_info(path: str | None) -> dict | None:
    if not path:
        return None
    data = Path(path).read_bytes()
    return {"name": Path(path).name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def check_case(docx: str, pdf: str | None = None, *, rules: dict | None = None, stage: str | None = None,
               case: str | None = None, use_llm: bool = False, ignore: set[str] | None = None) -> Result:
    rules = copy.deepcopy(rules or load_rules())
    stage = stage or rules.get("default_stage", "final")
    if stage not in rules["stages"]:
        raise ValueError(f"未知的階段：{stage}（可用：{', '.join(rules['stages'])}）")
    groups = set(rules["stages"][stage]["groups"])
    rules["_stage"] = stage
    rules["_enabled"] = {g: g in groups for g in ("antecedent", "support")}

    spec = build_spec(docx, rules)
    res = Result(case=case or Path(docx).stem, stage=stage, tool_version=__version__,
                 rules_version=str(rules.get("rules_version", "")),
                 files={"docx": _file_info(docx), "pdf": _file_info(pdf)})
    res.meta.update({
        "工具版本": f"Patent Review System {__version__}",
        "規則版本": rules.get("rules_version", ""),
        "檢查階段": f"{stage}（{rules['stages'][stage]['label']}）",
        "說明書": f"{Path(docx).name}（sha256 {res.files['docx']['sha256'][:12]}）",
        "圖式": f"{Path(pdf).name}（sha256 {res.files['pdf']['sha256'][:12]}）" if pdf else "未提供",
    })

    for g, fn in A_GROUPS.items():
        if g in groups:
            fn(spec, res)
    if groups & {"claims_core", "antecedent", "support"}:
        B.run(spec, res)

    pdf_data = read_pdf(pdf, rules) if pdf and (groups & {"pdf", "symbols", "figures", "rep_figure"}) else None
    if "symbols" in groups:
        C.check_symbol_table(spec, res, pdf_data)
    figs = C.check_figures(spec, res, pdf_data) if "figures" in groups else []
    if "rep_figure" in groups:
        C.check_rep_figure(spec, res, pdf_data, figs)
    if "pdf" in groups and pdf_data:
        D.run(pdf_data, rules, res)
    if "semantic" in groups:
        E.run(spec, res, use_llm=use_llm or rules["semantic"]["llm"].get("enabled", False))

    if ignore:
        before = len(res.issues)
        res.issues = [i for i in res.issues if i.id not in ignore]
        res.meta["已忽略問題數"] = before - len(res.issues)
    return res
