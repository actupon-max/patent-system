"""共用資料結構：問題(Issue)與檢查結果(Result)。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict

SEVERITY_ORDER = {"必改": 0, "建議": 1, "需人工確認": 2, "資訊": 3}


@dataclass
class Issue:
    file: str          # 說明書 / 圖式
    location: str      # 【0012】 / 請求項8 / 圖4 / 第3頁
    rule: str          # 規則編號，例如 B04
    message: str       # 問題描述
    actual: str = ""   # 實際值
    expected: str = ""  # 期望值
    severity: str = "必改"
    basis: str = ""    # 依據
    quote: str = ""    # 原文引句

    @property
    def id(self) -> str:
        """穩定 ID：同一問題重跑時 ID 不變，可用於 ignore 清單。"""
        key = f"{self.rule}|{self.location}|{self.actual}|{self.message}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d


@dataclass
class Result:
    case: str
    issues: list[Issue] = field(default_factory=list)
    tables: dict[str, list[dict]] = field(default_factory=dict)  # 附表：符號對照、依附關係等
    meta: dict = field(default_factory=dict)
    stage: str = ""
    files: dict = field(default_factory=dict)   # {"docx": {name, sha256, size}, "pdf": {...} 或 None}
    tool_version: str = ""
    rules_version: str = ""

    def add(self, issue: Issue) -> None:
        self.issues.append(issue)

    def sorted_issues(self) -> list[Issue]:
        return sorted(self.issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.rule))

    def count(self, severity: str) -> int:
        return sum(1 for i in self.issues if i.severity == severity)
