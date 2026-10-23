"""CONTRACT-1.0：合成材料与离线校验器；不导入骨架检查脚本充当测试。"""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def validators():
    documents = [json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
                 for name in ("input-schema.json", "output-schema.json")]
    registry = Registry().with_resources((doc["$id"], Resource.from_contents(doc)) for doc in documents)
    return tuple(Draft202012Validator(doc, registry=registry, format_checker=FormatChecker())
                 for doc in documents)


@pytest.fixture
def evidence_input():
    """完全虚构，代码只满足格式，不代表已登记或适合真实提供方查询。"""
    stamp = "2026-10-23T00:00:00Z"
    code = "91310000MA1ABCDEF0"
    subject = dict(name="测试企业甲", credit_code=code, registered_region=None,
                   legal_representative=None, established_on=None, confirmed_at=stamp)
    evidence = dict(evidence_id="E-TEST-01", subject_credit_code=code, category="basic",
                    content="合成材料：认缴资本不代表账上现金。", source="tianyan",
                    snapshot_time=stamp, captured_at=stamp, event_time=None, source_url=None,
                    source_publisher=None, provider_record_id=None, origin_id="test-origin",
                    derived_from=None, verification_status="original_not_verified", hint_id="SOURCE_TIANYAN")
    categories = {category: dict(status="not_requested", record_count=0, queried_at=None,
                                 scope_description="未查询", error_code=None)
                  for category in ("basic", "abnormal", "penalty", "judicial", "asset")}
    categories["basic"] = dict(status="ok", record_count=1, queried_at=stamp,
                               scope_description="仅合成工商记录", error_code=None)
    return dict(subject=subject, evidence_list=[evidence], api_status=dict(
        tianyan_status="ok", planned_categories=["basic"], categories=categories))


@pytest.fixture
def payload(evidence_input):
    from copy import deepcopy
    result = deepcopy(evidence_input)
    uid = "11111111-1111-4111-8111-111111111111"
    result["summary_text"] = "仅用于结构测试，非模型质量验收报告。"
    result["api_status"].update(session_id=uid, session_generation=1, operation_id=uid,
        result_revision=1, evidence_version=1, summary_evidence_version=1,
        summary_generated_at="2026-10-23T00:00:00Z", llm_status="success",
        snapshot_status="not_checked", snapshot_draft=None, last_submission=None)
    result["ui_hint_group"] = ["DISCLOSURE_LIMITED"]
    return result
