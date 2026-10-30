"""本機小服務（patent-review serve）：來源限制、CORS、路徑檢查與檢查結果。"""
import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from patent_review import server

PID = "11111111-1111-1111-1111-111111111111"
PLATFORM = "https://gdip-platform.vercel.app"


@pytest.fixture(scope="module")
def svc(samples, tmp_path_factory):
    d = samples / "case1_like"
    store = {f"{PID}/final_draft/v1_1.docx": next(d.glob("*.docx")),
             f"{PID}/final_draft/v1_2.pdf": next(d.glob("*.pdf"))}
    cfg = server.Config(server.DEFAULT_SUPABASE, server.DEFAULT_ORIGINS, tmp_path_factory.mktemp("rep"), None)
    orig = server.download

    def fake_download(c, path):
        if not server.PATH_RE.match(path or ""):
            raise ValueError(f"不接受的檔案路徑：{path}")
        return store[path].read_bytes()
    server.download = fake_download
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(cfg))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", store, cfg
    httpd.shutdown()
    server.download = orig


def req(url, method="GET", body=None, origin=PLATFORM):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                               headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as x:
            return x.status, dict(x.headers), json.loads(x.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, dict(e.headers), json.loads(raw) if raw else None


def test_health_reports_versions(svc):
    url, _, _ = svc
    code, h, body = req(url + "/health")
    assert code == 200 and body["version"] and body["rules_version"]
    assert h["Access-Control-Allow-Origin"] == PLATFORM


def test_preflight_allows_private_network(svc):
    url, _, _ = svc
    code, h, _ = req(url + "/check", method="OPTIONS")
    assert code == 204
    assert h["Access-Control-Allow-Private-Network"] == "true"


def test_other_origins_rejected(svc):
    url, _, _ = svc
    body = {"docx_path": f"{PID}/final_draft/v1_1.docx", "stage": "final"}
    assert req(url + "/check", "POST", body, origin="https://evil.example.com")[0] == 403
    assert req(url + "/check", "POST", body, origin=None)[0] == 403
    assert req(url + "/health", origin="https://evil.example.com")[0] == 403


def test_bad_path_rejected(svc):
    url, _, _ = svc
    code, _, body = req(url + "/check", "POST", {"docx_path": "../../etc/passwd.docx", "stage": "final"})
    assert code == 400 and "不接受" in body["error"]


def test_check_returns_verifiable_report(svc):
    url, store, cfg = svc
    code, _, rep = req(url + "/check", "POST", {"docx_path": f"{PID}/final_draft/v1_1.docx",
                                                "pdf_path": f"{PID}/final_draft/v1_2.pdf",
                                                "stage": "final", "case": "TW20260101",
                                                "names": {"docx": "說明書.docx", "pdf": "圖式.pdf"}})
    assert code == 200
    assert rep["format"] == "patent-review-report/1" and rep["stage"] == "final"
    assert rep["counts"]["必改"] == 2
    sha = hashlib.sha256(store[f"{PID}/final_draft/v1_1.docx"].read_bytes()).hexdigest()
    assert rep["files"]["docx"]["sha256"] == sha
    assert rep["local_report"].endswith("_檢查報告.xlsx")
    assert list(cfg.out_dir.glob("*.xlsx"))
