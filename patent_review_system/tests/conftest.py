import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from patent_review.runner import check_case, load_rules  # noqa: E402


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    import make_samples
    out = tmp_path_factory.mktemp("synthetic")
    make_samples.main(str(out))
    return out


@pytest.fixture(scope="session")
def rules():
    return load_rules()


@pytest.fixture(scope="session")
def run(samples, rules):
    cache = {}

    def _run(name, stage=None):
        key = (name, stage)
        if key not in cache:
            d = samples / name
            docx = next(d.glob("*.docx"))
            pdf = next(d.glob("*.pdf"), None)
            cache[key] = check_case(str(docx), str(pdf) if pdf else None, rules=rules, stage=stage, case=name)
        return cache[key]
    return _run


def find(res, rule, **kw):
    out = []
    for i in res.issues:
        if i.rule != rule:
            continue
        if all(v in getattr(i, k) for k, v in kw.items()):
            out.append(i)
    return out
