"""本機小服務：patent-review serve

讓群淵 GDIP 平台在瀏覽器按「執行檢查」時，由這台電腦上的檢查器下載平台檔案、檢查並回傳報告。
只監聽 127.0.0.1，只接受允許來源（平台網址）的請求，只從平台的 Supabase 檔案庫下載。
"""
from __future__ import annotations

import json
import re
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .report import report_dict, write_case_xlsx
from .runner import check_case, load_rules

DEFAULT_PORT = 8765
DEFAULT_SUPABASE = "https://fcqjdkndpywbynrkfmur.supabase.co"
BUCKET = "patent-files"
# 平台上傳時產生的路徑：<uuid>/<分類>/<檔名>
PATH_RE = re.compile(r"^[0-9a-fA-F-]{36}/(claim|final_draft)/[\w.\-]+$")
MAX_BYTES = 80 * 1024 * 1024
# 預設允許：Vercel 網址與本機開發；自有網域用 --allow-origin 加入
DEFAULT_ORIGINS = [r"https://[\w.-]+\.vercel\.app", r"http://(localhost|127\.0\.0\.1)(:\d+)?"]


class Config:
    def __init__(self, supabase: str, origins: list[str], out_dir: Path, rules_path: str | None):
        self.supabase = supabase.rstrip("/")
        self.origins = [re.compile(o) for o in origins]
        self.out_dir = out_dir
        self.rules_path = rules_path

    def origin_ok(self, origin: str | None) -> bool:
        return bool(origin) and any(p.fullmatch(origin) for p in self.origins)


def download(cfg: Config, path: str) -> bytes:
    if not PATH_RE.match(path or ""):
        raise ValueError(f"不接受的檔案路徑：{path}")
    url = f"{cfg.supabase}/storage/v1/object/public/{BUCKET}/{urllib.parse.quote(path)}"
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("檔案超過 80MB")
    return data


def run_check(cfg: Config, body: dict) -> tuple[int, dict]:
    rules = load_rules(cfg.rules_path)
    stage = body.get("stage")
    if stage not in rules["stages"]:
        return 400, {"error": f"未知的階段：{stage}"}
    docx_path, pdf_path = body.get("docx_path", ""), body.get("pdf_path") or None
    if not docx_path.lower().endswith(".docx"):
        return 400, {"error": "說明書必須是 .docx（舊版 .doc 請先另存為 .docx）"}
    if pdf_path and not pdf_path.lower().endswith(".pdf"):
        return 400, {"error": "圖式必須是 .pdf"}
    try:
        docx = download(cfg, docx_path)
        pdf = download(cfg, pdf_path) if pdf_path else None
    except ValueError as e:
        return 400, {"error": str(e)}
    except Exception as e:
        return 502, {"error": f"無法從平台下載檔案：{e}"}

    case = re.sub(r"[^\w\-]", "_", str(body.get("case") or "案件"))[:40]
    names = body.get("names") or {}
    with tempfile.TemporaryDirectory() as td:
        dp = Path(td) / _safe_name(names.get("docx"), "說明書.docx")
        dp.write_bytes(docx)
        pp = None
        if pdf:
            pp = Path(td) / _safe_name(names.get("pdf"), "圖式.pdf")
            pp.write_bytes(pdf)
        try:
            res = check_case(str(dp), str(pp) if pp else None, rules=rules, stage=stage, case=case)
        except Exception as e:
            return 422, {"error": f"檢查失敗（檔案可能損毀或格式不支援）：{type(e).__name__}: {e}"}
    rep = report_dict(res)
    # Excel 報告留在本機
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    xlsx = cfg.out_dir / f"{case}_{stage}_{stamp}_檢查報告.xlsx"
    write_case_xlsx(res, xlsx)
    rep["local_report"] = str(xlsx)
    return 200, rep


def _safe_name(name: str | None, default: str) -> str:
    n = Path(str(name or "")).name
    return n if re.fullmatch(r"[\w.\-㐀-鿿 ()（）]+", n or "") else default


def make_handler(cfg: Config):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"PatentReview/{__version__}"

        def log_message(self, fmt, *args):  # 終端只印簡短紀錄
            print(f"[{datetime.now():%H:%M:%S}] {self.command} {self.path} {args[1] if len(args) > 1 else ''}")

        def _cors(self) -> None:
            origin = self.headers.get("Origin")
            if cfg.origin_ok(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                # Chrome 私有網路存取（公開網站連到本機）需要此標頭
                self.send_header("Access-Control-Allow-Private-Network", "true")

        def _send(self, code: int, payload: dict) -> None:
            origin = self.headers.get("Origin")
            if origin and not cfg.origin_ok(origin):
                code, payload = 403, {"error": f"來源 {origin} 不在允許清單（請用 --allow-origin 加入平台網址）"}
            data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.send_response(204 if cfg.origin_ok(self.headers.get("Origin")) else 403)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            if self.path.rstrip("/") not in ("", "/health"):
                return self._send(404, {"error": "not found"})
            rules = load_rules(cfg.rules_path)
            self._send(200, {"service": "Patent Review System", "version": __version__,
                             "rules_version": str(rules.get("rules_version", "")),
                             "stages": list(rules["stages"]), "reports_dir": str(cfg.out_dir)})

        def do_POST(self):
            if self.path.rstrip("/") != "/check":
                return self._send(404, {"error": "not found"})
            if not cfg.origin_ok(self.headers.get("Origin")):
                return self._send(403, {"error": "只接受平台網頁的請求（請用 --allow-origin 加入平台網址）"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"error": "請求格式錯誤"})
            code, payload = run_check(cfg, body)
            self._send(code, payload)

    return Handler


def serve(port: int = DEFAULT_PORT, supabase: str = DEFAULT_SUPABASE, origins: list[str] | None = None,
          out_dir: str = "~/PatentReview報告", rules_path: str | None = None) -> None:
    cfg = Config(supabase, DEFAULT_ORIGINS + [re.escape(o.rstrip("/")) for o in (origins or [])],
                 Path(out_dir).expanduser(), rules_path)
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg))
    print(f"Patent Review System {__version__} 本機服務已啟動：http://127.0.0.1:{port}")
    print(f"Excel 報告存放於：{cfg.out_dir}")
    print("請保持此視窗開啟；在平台按「執行檢查」即可。按 Ctrl+C 結束。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已結束")
