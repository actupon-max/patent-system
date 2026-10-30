"""真實案件驗收：需設定 PATENT_SAMPLES_DIR，未設定時自動略過。"""
import os
from pathlib import Path

import pytest
import yaml

from patent_review.runner import check_case

HERE = Path(__file__).resolve().parent
SAMPLES = os.environ.get("PATENT_SAMPLES_DIR")
SPEC = yaml.safe_load((HERE / "expected_issues.yaml").read_text(encoding="utf-8"))

pytestmark = pytest.mark.skipif(not SAMPLES, reason="未設定 PATENT_SAMPLES_DIR（真實樣本只在本機）")


def _match(issue, exp):
    return issue.rule == exp.get("rule", issue.rule) and exp.get("location", "") in issue.location \
        and exp.get("message", "") in issue.message


@pytest.mark.parametrize("case", SPEC["cases"], ids=lambda c: c["name"])
def test_real_case(case, rules):
    d = Path(SAMPLES).expanduser() / case["folder"]
    docx = next(x for x in d.glob("*.docx") if not x.name.startswith("~$"))
    pdf = next(d.glob("*.pdf"), None)
    res = check_case(str(docx), str(pdf) if pdf else None, rules=rules, stage=case.get("stage"), case=case["name"])

    missing = [e for e in case["must_find"] if not any(_match(i, e) for i in res.issues)]
    in_scope = [e for e in case.get("review_sheet", []) if e.get("scope") == "程式"]
    hit = [e for e in in_scope if any(_match(i, e) for i in res.issues)]
    print(f"\n{case['name']}：必改 {res.count('必改')}、建議 {res.count('建議')}、需人工確認 {res.count('需人工確認')}")
    if in_scope:
        print(f"  審查意見表召回率（程式範圍）：{len(hit)}/{len(in_scope)}")
        for e in in_scope:
            if e not in hit:
                print(f"  未抓到：{e}")
    assert not missing, f"未抓到驗收門檻問題：{missing}"
