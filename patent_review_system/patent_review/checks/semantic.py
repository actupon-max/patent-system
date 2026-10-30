"""E. 語意層：固定字串檢查（不需 LLM）＋選用的 LLM 檢查。

所有結果都標「需人工確認」；LLM 回傳的引句必須能在原文逐字找到，找不到就丟棄。
"""
from __future__ import annotations

import json
import os
import re
import unicodedata

from ..model import Issue, Result
from ..structure import Spec

F = "說明書"


def _norm(s: str) -> str:
    """比對用正規化：全形半形統一、去空白。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def locate(spec: Spec, quote: str) -> str | None:
    """引句逐字出現在哪一段；找不到回傳 None。"""
    nq = _norm(quote)
    if len(nq) < 2:
        return None
    for p in spec.paras:
        if p.section and nq in _norm(p.body):
            return _loc(spec, p)
    return None


def _loc(spec: Spec, p) -> str:
    if p.section == "claims":
        num = None
        for c in spec.claims:
            if c.para_idx <= p.idx:
                num = c.num
        if num:
            return f"請求項{num}"
    return p.loc()


def run(spec: Spec, res: Result, use_llm: bool = False) -> None:
    cfg = spec.rules["semantic"]
    for p in spec.paras:
        if not p.section or p.is_heading:
            continue
        for phrase in cfg.get("strategic_phrases", []):
            i = p.body.find(phrase)
            if i >= 0:
                quote = p.body[max(0, i - 10): i + len(phrase) + 10]
                res.add(Issue(F, _loc(spec, p), "E01", f"策略性字句「{phrase}」", actual=quote,
                              expected="確認是否保留", severity=cfg["strategic_severity"],
                              basis="事務所檢查清單", quote=quote))
    if use_llm:
        run_llm(spec, res)


PROMPT = """你是台灣專利說明書的校對員。以下是一份發明專利申請文件的一部分（每段前有位置標記）。
請只找出下列類別的問題：{cats}。
規則：
1. 每個問題都必須附上「原文引句」，引句必須逐字複製自下方文字（不可改寫、不可省略字），長度 4 到 40 字。
2. 沒有把握或找不到可引用的原文，就不要列出。
3. 不要評論格式、標點全半形、段號，那些由其他程式檢查。
只輸出 JSON 陣列，不要任何其他文字。每個元素格式：
{{"category": "類別", "quote": "原文引句", "problem": "問題說明", "suggestion": "建議修改"}}
若沒有問題，輸出 []。

---
{text}"""


def run_llm(spec: Spec, res: Result) -> None:
    cfg = spec.rules["semantic"]["llm"]
    try:
        import anthropic
    except ImportError:
        res.add(Issue(F, "全文", "E00", "未安裝 anthropic 套件，略過 LLM 語意檢查", severity="資訊"))
        return
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        res.add(Issue(F, "全文", "E00", "未設定 ANTHROPIC_API_KEY，略過 LLM 語意檢查", severity="資訊"))
        return
    client = anthropic.Anthropic()
    chunks, cur = [], ""
    for p in spec.paras:
        if not p.section or p.is_heading or not p.body:
            continue
        line = f"[{_loc(spec, p)}] {p.body}\n"
        if len(cur) + len(line) > cfg["max_chunk_chars"] and cur:
            chunks.append(cur)
            cur = ""
        cur += line
    if cur:
        chunks.append(cur)

    kept = dropped = 0
    for chunk in chunks:
        try:
            with client.beta.messages.stream(
                model=cfg["model"],
                max_tokens=16000,
                thinking={"type": "adaptive"},
                output_config={"effort": cfg.get("effort", "high")},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": PROMPT.format(cats="、".join(cfg["categories"]), text=chunk)}],
            ) as stream:
                msg = stream.get_final_message()
        except anthropic.APIConnectionError as e:
            res.add(Issue(F, "全文", "E00", f"LLM 連線失敗，略過其餘語意檢查：{e}", severity="資訊"))
            break
        except anthropic.APIStatusError as e:
            res.add(Issue(F, "全文", "E00", f"LLM 呼叫失敗（HTTP {e.status_code}），略過其餘語意檢查", severity="資訊"))
            break
        if msg.stop_reason == "refusal":
            continue
        text = "".join(b.text for b in msg.content if b.type == "text")
        m = re.search(r"\[.*\]", text, re.S)
        try:
            items = json.loads(m.group()) if m else []
        except json.JSONDecodeError:
            items = []
        for it in items:
            quote = str(it.get("quote", "")).strip()
            loc = locate(spec, quote)
            if not loc:
                dropped += 1    # 引句在原文找不到 → 視為不可信，丟棄
                continue
            kept += 1
            res.add(Issue(F, loc, "E02", f"[{it.get('category', '語意')}] {it.get('problem', '')}",
                          actual=quote, expected=str(it.get("suggestion", "")), severity="需人工確認",
                          basis=f"LLM 語意檢查（{cfg['model']}）", quote=quote))
    res.meta["LLM 採用／丟棄（引句不符）"] = f"{kept}／{dropped}"
