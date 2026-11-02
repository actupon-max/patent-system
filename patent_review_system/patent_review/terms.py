"""從符號說明與內文擷取「名稱＋符號」，供 B（前置基礎）與 C（符號對照）共用。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .structure import Spec

CJK_CHAR = re.compile(r"[㐀-鿿]")


@dataclass
class SymbolEntry:
    symbol: str
    name: str
    loc: str
    source: str   # 符號說明 / 代表圖符號 / 內文
    group: int = 1  # 同一行列出的符號數（「12a,12b:第一、第二端」為 2）


def norm_symbol(s: str) -> str:
    return s.replace("′", "'").replace("’", "'").replace("＇", "'").strip()


def parse_symbol_list(spec: Spec, section: str) -> list[SymbolEntry]:
    pat = re.compile(spec.rules["symbols"]["list_line"])
    out = []
    for p in spec.section_paras(section):
        for chunk in re.split(r"[；;\t\n]|\s{2,}", p.body):
            m = pat.match(chunk.strip())
            if not m:
                continue
            name = m.group(2).strip().rstrip("。.")
            syms = [s for s in re.split(r"\s*[、,，]\s*", m.group(1)) if s]
            for sym in syms:
                out.append(SymbolEntry(norm_symbol(sym), name, p.loc(),
                                       "符號說明" if section == "symbols" else "代表圖符號", len(syms)))
    return out


def find_body_symbols(spec: Spec, text: str, names: list[str]) -> list[tuple[str, str | None, int]]:
    """在文字中找出「名稱＋符號」。回傳 (符號, 對應到的名稱或 None, 位置)。

    名稱只用已知名稱清單做尾端比對；比對不到的仍回傳符號（名稱為 None），
    供「內文有但符號說明沒列」使用。
    """
    cfg = spec.rules["symbols"]
    pat = re.compile(cfg["body_symbol"])
    bad_pre = sorted(cfg["not_symbol_prefix"], key=len, reverse=True)
    bad_suf = sorted(cfg["not_symbol_suffix"], key=len, reverse=True)
    names_sorted = sorted(set(names), key=len, reverse=True)
    out = []
    for m in pat.finditer(text):
        sym = norm_symbol(m.group(1))
        before = text[: m.start()]
        after = text[m.end():]
        # 符號必須緊接在中文名稱之後（允許一個半形或全形空白）
        stripped = before.rstrip(" 　")
        if not stripped or not CJK_CHAR.match(stripped[-1]):
            continue
        if any(stripped.endswith(x) for x in bad_pre):
            continue
        if any(after.startswith(x) for x in bad_suf):
            continue
        # 小數、範圍的一部分
        if re.match(r"\s*[~～\-－至到]\s*\d", after):
            continue
        name = next((n for n in names_sorted if stripped.endswith(n)), None)
        out.append((sym, name, m.start()))
    return out
