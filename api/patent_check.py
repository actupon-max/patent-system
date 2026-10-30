"""Vercel Python 函式：/api/patent_check

平台送來 Supabase Storage 內的檔案路徑，這裡下載後執行 Patent Review System，回傳檢查結果。
檔案只在記憶體與暫存目錄中處理，函式結束即刪除，不會另外保存。

POST JSON:
  {"docx_path": "<patent_id>/final_draft/v3_xxx.docx",
   "pdf_path":  "<patent_id>/final_draft/v2_xxx.pdf",   # 選填
   "stage": "claims" | "draft" | "final",
   "case": "TW20260101"}
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "patent_review_system"))

from patent_review import __version__  # noqa: E402
from patent_review.service import run_check_bytes  # noqa: E402

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://fcqjdkndpywbynrkfmur.supabase.co").rstrip("/")
BUCKET = "patent-files"
# 只接受平台上傳時產生的路徑格式：<uuid>/<分類>/<檔名>
PATH_RE = re.compile(r"^[0-9a-fA-F-]{36}/(claim|final_draft|search_report|oa)/[\w.\-]+$")
MAX_BYTES = 40 * 1024 * 1024
STAGES = {"claims", "draft", "final"}


def fetch(path: str) -> bytes:
    if not PATH_RE.match(path):
        raise ValueError(f"不接受的檔案路徑：{path}")
    url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{urllib.parse.quote(path)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("檔案超過 40MB")
    return data


def handle(body: dict) -> tuple[int, dict]:
    docx_path = body.get("docx_path", "")
    pdf_path = body.get("pdf_path") or None
    stage = body.get("stage", "final")
    if stage not in STAGES:
        return 400, {"error": f"stage 必須是 {', '.join(sorted(STAGES))}"}
    if not docx_path.lower().endswith(".docx"):
        return 400, {"error": "說明書必須是 .docx（舊版 .doc 請先另存為 .docx）"}
    if pdf_path and not pdf_path.lower().endswith(".pdf"):
        return 400, {"error": "圖式必須是 .pdf"}
    try:
        docx = fetch(docx_path)
        pdf = fetch(pdf_path) if pdf_path else None
    except ValueError as e:
        return 400, {"error": str(e)}
    except Exception as e:  # 下載失敗
        return 502, {"error": f"無法從檔案庫讀取檔案：{e}"}
    try:
        out = run_check_bytes(docx, pdf, stage=stage, case=str(body.get("case") or "案件")[:40],
                              docx_name=Path(docx_path).name, pdf_name=Path(pdf_path).name if pdf_path else "圖式.pdf")
    except Exception as e:
        return 422, {"error": f"檢查失敗（檔案可能損毀或格式不支援）：{type(e).__name__}: {e}"}
    out["tool_version"] = __version__
    return 200, out


class handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"service": "Patent Review System", "version": __version__})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"error": "請求格式錯誤"})
            return
        code, payload = handle(body)
        self._send(code, payload)
