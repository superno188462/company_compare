"""COLLECTION-TEST-1，COLLECTION-1.0：COL-DATA-01..04、RULE-01的声明契约。"""

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

from company_screening.contracts import generated
from collection_support import CASE, CATEGORIES, CODE, STAMP, TOOLS, dump, record

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = [json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
             for name in ("input-schema.json", "output-schema.json", "collection-schema.json")]
REGISTRY = Registry().with_resources((doc["$id"], Resource.from_contents(doc)) for doc in DOCUMENTS)


def validate(name, value):
    ref = DOCUMENTS[-1]["$id"] + "#/$defs/" + name
    Draft202012Validator({"$ref": ref}, registry=REGISTRY, format_checker=FormatChecker()).validate(value)


def tool(name=CASE):
    return dict(tool_name=name, category=CATEGORIES[TOOLS.index(name)], batch_id=str(uuid4()),
                batch_revision=1, state="partial", collected_count=20, total_count=65,
                has_more=True, next_upstream_page=2, first_fetched_at=STAMP.isoformat(),
                last_fetched_at=STAMP.isoformat(), obtained_from="cache", report_batch_id=None,
                report_included_count=0, last_error=None, diagnostic=None, total_changed=False)


def overview_data():
    tools = []
    for name, category in zip(TOOLS, CATEGORIES, strict=True):
        item = tool(name)
        item.update(category=category, state="not_requested", batch_id=None, batch_revision=None,
                    collected_count=0, total_count=None, has_more=None, next_upstream_page=None,
                    first_fetched_at=None, last_fetched_at=None, obtained_from="none")
        tools.append(item)
    return dict(session_id=str(uuid4()), session_generation=1, subject_credit_code=CODE,
                collection_revision=1, tools=tools, report_evidence_version=None, report_evidence_count=0)


@pytest.mark.parametrize("tool_name", TOOLS)
def test_refresh_allows_exactly_the_fourteen_planned_tools(tool_name):
    """COL-DATA-01/04：固定14项允许单工具更新，不开放任意代理。"""
    value = dict(expected_generation=1, expected_collection_revision=1, tool_name=tool_name, expected_batch_id=None)
    validate("RefreshCollectionToolCommand", value)
    assert dump(generated.RefreshCollectionToolCommand(**value)) == value


@pytest.mark.parametrize("changes", [
    {"tool_name": "get_unknown"}, {"expected_generation": 0}, {"expected_generation": True},
    {"expected_collection_revision": -1}, {"expected_batch_id": "invalid"},
    {"credit_code": CODE}, {"scope_id": "client-selected"}, {"authorization": "FAKE_SECRET"},
])
def test_refresh_rejects_invalid_fields_or_client_scope(changes):
    """COL-DATA-01/04：严格格式及额外字段拒绝，不接受客户端数据源/凭据。"""
    value = dict(expected_generation=1, expected_collection_revision=1, tool_name=CASE, expected_batch_id=None)
    value.update(changes)
    with pytest.raises(ValidationError):
        validate("RefreshCollectionToolCommand", value)


@pytest.mark.parametrize("changes", [
    {"tool_name": "get_shareholder_info"}, {"page_number": 1}, {"page_number": True},
    {"batch_id": None}, {"page_size": 100}, {"expected_collection_revision": 0},
])
def test_load_page_only_accepts_judicial_continuation_command(changes):
    """COL-DATA-04：只开放司法>=2页；页大小由服务器固定。"""
    value = dict(expected_generation=1, expected_collection_revision=1, tool_name=CASE,
                 batch_id=str(uuid4()), page_number=2)
    value.update(changes)
    with pytest.raises(ValidationError):
        validate("LoadCollectionPageCommand", value)


@pytest.mark.parametrize("field", ["total_count", "has_more", "last_error", "diagnostic", "report_batch_id"])
def test_nullable_fields_are_still_required(field):
    """COL-DATA-03：未知为明确null，省略不是同一语义。"""
    value = tool()
    validate("CollectionToolView", value)
    del value[field]
    with pytest.raises(ValidationError):
        validate("CollectionToolView", value)


@pytest.mark.parametrize("changes", [
    {"category": "asset"}, {"state": "empty"}, {"state": "complete", "has_more": True},
    {"batch_id": None}, {"report_included_count": 201}, {"collected_count": True},
    {"last_fetched_at": "2026-10-24T12:00:00"}, {"expires_at": STAMP.isoformat()},
])
def test_tool_coverage_rejects_contradictory_or_fabricated_state(changes):
    """COL-DATA-01/03：类别/工具、完整性、时间、报告预算与无TTL声明。"""
    value = tool()
    value.update(changes)
    with pytest.raises(ValidationError):
        validate("CollectionToolView", value)


def test_browser_count_over_200_and_unknown_total_are_valid():
    """COL-DATA-03/IF-03：浏览数量可超过200；未知总数不改成0。"""
    value = tool()
    value.update(collected_count=5000, total_count=None, has_more=None)
    validate("CollectionToolView", value)
    assert dump(generated.CollectionToolView(**value))["total_count"] is None


@pytest.mark.parametrize("count", [13, 15])
def test_overview_requires_all_fourteen_planned_tools(count):
    """COL-DATA-03：不能用省略失败项缩小计划覆盖。"""
    value = overview_data()
    value["tools"] = (value["tools"] + [deepcopy(value["tools"][0])])[:count]
    with pytest.raises(ValidationError):
        validate("CollectionOverview", value)


@pytest.mark.parametrize("state, result, error, valid", [
    ("queued", None, None, True), ("running", None, None, True),
    ("succeeded", "overview", None, True), ("failed", None, "error", True),
    ("succeeded", None, None, False), ("failed", None, None, False),
    ("running", "overview", None, False), ("failed", "overview", "error", False),
])
def test_collection_operation_terminal_contract(state, result, error, valid):
    """COL-DATA-04：独立浏览任务的成功、失败和非终态结构。"""
    value = dict(operation_id=str(uuid4()), session_id=str(uuid4()), session_generation=1,
                 kind="load_page", state=state, result=overview_data() if result else None,
                 error=dict(code="UPSTREAM_AUTH", hint_id="QUERY_ERROR", fields=[], retryable=False) if error else None)
    if valid:
        validate("CollectionOperationView", value)
    else:
        with pytest.raises(ValidationError):
            validate("CollectionOperationView", value)


@pytest.mark.parametrize("field,value", [("source", "user_self"), ("verification_status", "official_verified"),
                                         ("content", "字" * 4001), ("source_url", "javascript:alert(1)")])
def test_collected_record_preserves_source_content_and_url_rules(field, value):
    """COL-DATA-02/RULE-01：缓存不升级来源或裁剪正文。"""
    item = dump(record())
    item.update(record_key="synthetic-record", subject_credit_code=CODE, category="judicial",
                 tool_name=CASE, source="tianyan", snapshot_time=STAMP.isoformat(),
                 verification_status="original_not_verified")
    item[field] = value
    with pytest.raises(ValidationError):
        validate("CollectedRecord", item)


def test_all_declared_public_models_match_types_and_preserve_nullable_values():
    """COL-DATA-01..04：新增声明字段及必填对齐，不补造null字段。"""
    for name in DOCUMENTS[-1]["properties"]:
        schema = DOCUMENTS[-1]["$defs"][name]
        fields = getattr(generated,name).model_fields
        assert set(fields) == set(schema["properties"])
        assert {key for key,value in fields.items() if value.is_required()} == set(schema["required"])
    value = overview_data()
    assert dump(generated.CollectionOverview(**value)) == value


@pytest.mark.parametrize("size", [0,21])
def test_stored_browser_response_has_exactly_twenty_item_capacity(size):
    """COL-DATA-03/NFR-03：空页合法，本地单页不能一次返回全部材料。"""
    base = overview_data()
    value = {key:base[key] for key in ("session_id","session_generation","subject_credit_code","collection_revision")}
    value.update(tool_name=CASE,batch_id=str(uuid4()),batch_revision=1,page=1,page_size=20,items=[],next_page=None)
    item = dump(record())
    item.update(record_key="record",subject_credit_code=CODE,category="judicial",tool_name=CASE,
                 source="tianyan",snapshot_time=STAMP.isoformat(),verification_status="original_not_verified")
    value["items"] = [deepcopy(item) for _ in range(size)]
    if size==0:
        validate("CollectionRecordsPage",value)
    else:
        with pytest.raises(ValidationError):
            validate("CollectionRecordsPage",value)
