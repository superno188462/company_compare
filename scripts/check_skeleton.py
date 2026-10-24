"""检查骨架签名、未实现函数体及声明模型与权威 Schema 的映射。

仅验证骨架结构，不是应用行为或真实外部服务的契约测试。
"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
from typing import get_args

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from referencing import Registry, Resource

from company_screening.contracts import generated
from company_screening.contracts.boundary import ValidationMessageKey

ROOT = Path(__file__).resolve().parents[1]

# 用户2026-10-23确认首批测试后，逐函数实现并验证的明确范围。
IMPLEMENTED = {
    # COLLECTION-TEST-1与装配补充确认后逐函数实现；原用例及全部新增用例回归。
    ("src/company_screening/collections.py", "_error"),
    ("src/company_screening/collections.py", "CollectionService.__init__"),
    ("src/company_screening/collections.py", "CollectionService._key"),
    ("src/company_screening/collections.py", "CollectionService._state"),
    ("src/company_screening/collections.py", "CollectionService._forget"),
    ("src/company_screening/collections.py", "CollectionService._pages"),
    ("src/company_screening/collections.py", "CollectionService._fetch"),
    ("src/company_screening/collections.py", "CollectionService.overview"),
    ("src/company_screening/collections.py", "CollectionService.records"),
    ("src/company_screening/collections.py", "CollectionService._category_batch"),
    ("src/company_screening/collections.py", "CollectionService._accept_projection"),
    ("src/company_screening/collections.py", "CollectionService._snapshot_at"),
    ("src/company_screening/collections.py", "CollectionService._start"),
    ("src/company_screening/collections.py", "CollectionService._run"),
    ("src/company_screening/collections.py", "CollectionService.load_page"),
    ("src/company_screening/collections.py", "CollectionService.refresh_tool"),
    ("src/company_screening/collections.py", "CollectionService.operation"),
    ("src/company_screening/collection_clock.py", "utc_now"),
    ("src/company_screening/services.py", "SessionService._begin_collection"),
    ("src/company_screening/services.py", "SessionService._finish_collection"),
    ("src/company_screening/adapters/collection_sqlite.py", "SqliteCollectionStore.__init__"),
    ("src/company_screening/adapters/collection_sqlite.py", "SqliteCollectionStore.latest"),
    ("src/company_screening/adapters/collection_sqlite.py", "SqliteCollectionStore.get_batch"),
    ("src/company_screening/adapters/collection_sqlite.py", "SqliteCollectionStore.get_page"),
    ("src/company_screening/adapters/collection_sqlite.py", "SqliteCollectionStore.commit"),
    ("src/company_screening/adapters/collection_sqlite.py", "SqliteCollectionStore.claim"),
    ("src/company_screening/adapters/collection_sqlite.py", "SqliteCollectionStore.finish"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter.fetch_tool_snapshot"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter.fetch_judicial_page"),
    ("backend/collection_routes.py", "get_collection_service"),
    ("backend/collection_routes.py", "_check_write"),
    ("backend/collection_routes.py", "get_collections"),
    ("backend/collection_routes.py", "get_collection_records"),
    ("backend/collection_routes.py", "load_collection_page"),
    ("backend/collection_routes.py", "refresh_collection_tool"),
    ("backend/collection_routes.py", "get_collection_operation"),
    ("src/company_screening/services.py", "_query_diagnostic"),
    ("src/company_screening/services.py", "SessionService._begin_query_retry"),
    ("src/company_screening/services.py", "SessionService.create"),
    ("src/company_screening/services.py", "SessionService.restore"),
    ("src/company_screening/services.py", "SessionService.activity"),
    ("src/company_screening/services.py", "SessionService.reset"),
    ("src/company_screening/services.py", "SessionService._confirm_subject"),
    ("src/company_screening/services.py", "SessionService._complete_operation"),
    ("src/company_screening/services.py", "SessionService._save_draft"),
    ("src/company_screening/services.py", "SessionService._clear_draft"),
    ("src/company_screening/services.py", "SessionService._accept_submission"),
    ("backend/app.py", "create_app"),
    ("backend/error_handlers.py", "validation_error"),
    ("backend/error_handlers.py", "application_error"),
    ("backend/error_handlers.py", "internal_error"),
    ("backend/error_handlers.py", "sanitize_unhandled"),
    ("src/company_screening/adapters/tianyan_mcp.py", "_provider_error"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter.__init__"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter._call_tool"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter.search"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter.fetch_category"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter._fetch_judicial_window"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter._fetch_paged_tool"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter._extract_page"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter._page_part"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter._registration_records"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter._make_record"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter._clean_value"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter._find_value"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter._reject_warnings"),
    ("src/company_screening/adapters/tianyan_mcp.py", "TianyanMcpAdapter._small_text"),
    ("src/company_screening/services.py", "ScreeningService.__init__"),
    ("src/company_screening/services.py", "ScreeningService.search"),
    ("src/company_screening/services.py", "ScreeningService.confirm"),
    ("src/company_screening/services.py", "ScreeningService.operation"),
    ("src/company_screening/services.py", "ScreeningService._fail_operation"),
    ("src/company_screening/services.py", "ScreeningService._run_query_operation"),
    ("src/company_screening/services.py", "ScreeningService._execute_query_operation"),
    ("src/company_screening/services.py", "ScreeningService.save_draft"),
    ("src/company_screening/services.py", "ScreeningService.clear_draft"),
    ("src/company_screening/services.py", "ScreeningService.submit"),
    ("src/company_screening/services.py", "ScreeningService.retry_queries"),
    ("src/company_screening/services.py", "ScreeningService._run_submission_operation"),
    ("backend/dependencies.py", "get_screening_service"),
    ("backend/dependencies.py", "get_actor"),
    ("backend/dependencies.py", "get_session_service"),
    ("backend/routes.py", "search_companies"),
    ("backend/routes.py", "confirm_subject"),
    ("backend/routes.py", "get_operation"),
    ("backend/routes.py", "save_draft"),
    ("backend/routes.py", "clear_draft"),
    ("backend/routes.py", "submit_evidence"),
    ("backend/routes.py", "retry_queries"),
    ("backend/routes.py", "create_session"),
    ("backend/routes.py", "restore_session"),
    ("backend/routes.py", "notify_activity"),
    ("backend/routes.py", "reset_session"),
}

SERVICE_PARAMETERS = {
    "SessionService.create": ["self", "actor"],
    "SessionService.restore": ["self", "actor", "sid"],
    "SessionService.activity": ["self", "actor", "sid"],
    "SessionService.reset": ["self", "actor", "sid", "key"],
    "ScreeningService.search": ["self", "actor", "sid", "command", "key"],
    "ScreeningService.confirm": ["self", "actor", "sid", "command", "key"],
    "ScreeningService.save_draft": ["self", "actor", "sid", "draft", "key"],
    "ScreeningService.clear_draft": ["self", "actor", "sid", "key"],
    "ScreeningService.submit": ["self", "actor", "sid", "command", "key"],
    "ScreeningService.retry_analysis": ["self", "actor", "sid", "command", "key"],
    "ScreeningService.retry_queries": ["self", "actor", "sid", "command", "key"],
    "ScreeningService.operation": ["self", "actor", "sid", "opid"],
    "ShareService.withdraw": ["self", "actor", "receipt_id", "key"],
}

PORT_PARAMETERS = {
    "CompanyDataPort.search": ["self", "command"],
    "CompanyDataPort.fetch_category": ["self", "subject", "category"],
    "CompanyDataPort.fetch_tool_snapshot": ["self", "subject", "tool_name"],
    "CompanyDataPort.fetch_judicial_page": ["self", "subject", "tool_name"],
    "CollectionStorePort.latest": ["self", "key"],
    "CollectionStorePort.get_batch": ["self", "key", "batch_id"],
    "CollectionStorePort.get_page": ["self", "key", "batch_id", "page_number"],
    "CollectionStorePort.commit": ["self", "batch", "page"],
    "CollectionStorePort.claim": ["self", "request"],
    "CollectionStorePort.finish": ["self", "claim_id"],
    "ReportModelPort.generate": ["self", "input", "system_prompt"],
}

COLLECTION_PARAMETERS = {
    "CollectionService.overview": ["self", "actor", "sid"],
    "CollectionService.records": ["self", "actor", "sid", "tool_name", "batch_id"],
    "CollectionService.load_page": ["self", "actor", "sid", "command", "key"],
    "CollectionService.refresh_tool": ["self", "actor", "sid", "command", "key"],
    "CollectionService.operation": ["self", "actor", "sid", "opid"],
}

COLLECTION_ROUTES = {
    ("GET", "/api/v1/sessions/{sid}/collections"),
    ("GET", "/api/v1/sessions/{sid}/collections/{tool_name}/records"),
    ("POST", "/api/v1/sessions/{sid}/collections/pages"),
    ("POST", "/api/v1/sessions/{sid}/collections/refresh"),
    ("GET", "/api/v1/sessions/{sid}/collection-operations/{opid}"),
}

EXPECTED_ROUTES = {
    ("POST", "/api/v1/sessions"), ("GET", "/api/v1/sessions/{sid}"),
    ("POST", "/api/v1/sessions/{sid}/activity"), ("DELETE", "/api/v1/sessions/{sid}"),
    ("POST", "/api/v1/sessions/{sid}/search"), ("POST", "/api/v1/sessions/{sid}/confirm"),
    ("PUT", "/api/v1/sessions/{sid}/draft"), ("DELETE", "/api/v1/sessions/{sid}/draft"),
    ("POST", "/api/v1/sessions/{sid}/evidence"), ("POST", "/api/v1/sessions/{sid}/analysis/retry"),
    ("POST", "/api/v1/sessions/{sid}/queries/retry"),
    ("GET", "/api/v1/sessions/{sid}/operations/{opid}"),
    ("POST", "/api/v1/shares/{receipt_id}/withdraw"),
}


def check_stub_bodies() -> int:
    """已实现清单之外的函数继续强制占位；不放宽公共签名检查。"""
    count = 0
    seen = set()
    for directory in (ROOT / "src", ROOT / "backend"):
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            qualified = {id(method): f"{cls.name}.{method.name}" for cls in ast.walk(tree)
                         if isinstance(cls, ast.ClassDef) for method in cls.body
                         if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                identity = (path.relative_to(ROOT).as_posix(), qualified.get(id(node), node.name))
                if identity in IMPLEMENTED:
                    assert node.returns is not None, identity
                    seen.add(identity)
                    continue
                body = node.body
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                    body = body[1:]
                assert len(body) == 1 and isinstance(body[0], ast.Raise), (path, node.name)
                error = body[0].exc
                assert isinstance(error, ast.Call) and isinstance(error.func, ast.Name), (path, node.name)
                assert error.func.id == "NotImplementedError" and not error.args and not error.keywords, (path, node.name)
                assert node.returns is not None, (path, node.name)
                count += 1
    assert seen == IMPLEMENTED, (seen, IMPLEMENTED)
    return count


def check_signatures(relative: str, expected: dict[str, list[str]]) -> None:
    """比较 SDD 中明确定义的公共方法名和参数顺序。"""
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    actual = {}
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef):
            for node in cls.body:
                if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                    actual[f"{cls.name}.{node.name}"] = [arg.arg for arg in node.args.args]
                    if relative == "src/company_screening/ports.py" and node.name == "fetch_category":
                        assert [arg.arg for arg in node.args.kwonlyargs] == ["record_limit"]
                        assert len(node.args.kw_defaults) == 1
                        default = node.args.kw_defaults[0]
                        assert isinstance(default, ast.Constant) and default.value == 200
                    if relative == "src/company_screening/ports.py" and node.name == "fetch_judicial_page":
                        assert [arg.arg for arg in node.args.kwonlyargs] == ["page_number", "page_size"]
                        assert node.args.kw_defaults[0] is None
                        assert isinstance(node.args.kw_defaults[1], ast.Constant)
                        assert node.args.kw_defaults[1].value == 20
                    if relative == "src/company_screening/ports.py" and node.name == "commit":
                        assert [arg.arg for arg in node.args.kwonlyargs] == ["claim_id", "expected_revision"]
                        assert node.args.kw_defaults == [None, None]
                    if relative == "src/company_screening/collections.py" and node.name == "records":
                        assert [arg.arg for arg in node.args.kwonlyargs] == ["page"]
                        assert isinstance(node.args.kw_defaults[0], ast.Constant)
                        assert node.args.kw_defaults[0].value == 1
    assert actual == expected, (relative, actual)


def check_shared_models() -> None:
    """核对模型字段/必填性，并验证声明式模型的 JSON 往返。"""
    inputs = json.loads((ROOT / "contracts/input-schema.json").read_text(encoding="utf-8"))
    outputs = json.loads((ROOT / "contracts/output-schema.json").read_text(encoding="utf-8"))
    definitions = {**inputs["$defs"], **outputs["$defs"], "LlmInput": inputs, "WorkflowPayload": outputs}
    for name in ("Subject", "ToolCoverage", "CategoryResults", "QueryCoverage", "QueryDiagnostic", "SnapshotDraft", "WorkflowStatus", "SubmissionReceipt", "LlmInput", "WorkflowPayload"):
        model = getattr(generated, name)
        schema = definitions[name]
        assert set(model.model_fields) == set(schema["properties"]), name
        assert {key for key, field in model.model_fields.items() if field.is_required()} == set(schema["required"]), name
    for name in ("TianyanEvidence", "OtherUserEvidence", "SelfUserEvidence"):
        assert set(getattr(generated, name).model_fields) == set(inputs["$defs"]["Evidence"]["properties"]), name

    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in (inputs, outputs))
    for schema in (inputs, outputs):
        Draft202012Validator.check_schema(schema)
    subject = {"name": "测试企业甲", "credit_code": "91310000MA1ABCDEF0", "registered_region": None, "legal_representative": None, "established_on": None, "confirmed_at": "2026-10-22T12:00:00Z"}
    evidence = {"evidence_id": "E-TEST-01", "subject_credit_code": subject["credit_code"], "category": "basic", "content": "仅用于骨架结构验证的合成材料。", "source": "tianyan", "snapshot_time": "2026-10-22T12:00:00Z", "captured_at": "2026-10-22T12:00:00Z", "event_time": None, "source_url": None, "source_publisher": None, "provider_record_id": None, "origin_id": "synthetic-origin", "derived_from": None, "verification_status": "original_not_verified", "hint_id": "SOURCE_TIANYAN"}
    categories = {name: {"status": "not_requested", "record_count": 0, "queried_at": None, "scope_description": "本次未查询", "error_code": None} for name in ("basic", "abnormal", "penalty", "judicial", "asset")}
    categories["basic"] = {"status": "ok", "record_count": 1, "queried_at": "2026-10-22T12:00:00Z", "scope_description": "合成工商资料", "error_code": None}
    coverage = {"tianyan_status": "ok", "planned_categories": ["basic"], "categories": categories}
    llm_input = {"subject": subject, "evidence_list": [evidence], "api_status": coverage}
    uid = "11111111-1111-4111-8111-111111111111"
    payload = {"subject": subject, "evidence_list": [evidence], "summary_text": "合成结构样例，不是真实报告。", "api_status": {**coverage, "session_id": uid, "session_generation": 1, "operation_id": uid, "result_revision": 1, "evidence_version": 1, "summary_evidence_version": 1, "summary_generated_at": "2026-10-22T12:00:00Z", "llm_status": "success", "snapshot_status": "not_checked", "snapshot_draft": None, "last_submission": None}, "ui_hint_group": ["DISCLOSURE_LIMITED"]}
    for schema, cls, instance in ((inputs, generated.LlmInput, llm_input), (outputs, generated.WorkflowPayload, payload)):
        validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        validator.validate(instance)
        model = cls.model_validate_json(json.dumps(instance, ensure_ascii=False))
        validator.validate(json.loads(model.model_dump_json()))
    for cls, instance in (
        (generated.HttpUrl, "https://www.gsxt.gov.cn/"),
        (generated.CreditCode, "91310000MA1ABCDEF0"),
    ):
        cls.model_validate(instance)
    for cls, value in ((generated.HttpUrl, "javascript:alert(1)"), (generated.CreditCode, "short")):
        try:
            cls.model_validate(value)
        except ValidationError:
            continue
        raise AssertionError(f"Unexpected valid declaration: {cls.__name__}")


def check_collection_declarations() -> None:
    """COLLECTION-TYPE-1：只检查声明映射及Schema往返，不执行采集/存储业务。"""
    from generate_contracts import boundary_projection

    documents = [json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
                 for name in ("input-schema.json", "output-schema.json", "collection-schema.json")]
    registry = Registry().with_resources((doc["$id"], Resource.from_contents(doc)) for doc in documents)
    collection = documents[-1]
    Draft202012Validator.check_schema(collection)
    for name, definition in boundary_projection().items():
        assert collection["$defs"][name] == definition, name
    for name in collection["properties"]:
        schema = collection["$defs"][name]
        model = getattr(generated, name)
        assert set(model.model_fields) == set(schema["properties"]), name
        assert {key for key, value in model.model_fields.items() if value.is_required()} == set(schema["required"]), name
        assert all(value.description for value in model.model_fields.values()), name
    tool_names = list(generated.CollectionToolName)
    assert len(tool_names) == 14
    groups = ("basic", "basic", "abnormal", "penalty", *(["judicial"] * 6), *(["asset"] * 4))
    tools = [dict(tool_name=name.value, category=category, batch_id=None, batch_revision=None,
                  state="not_requested", collected_count=0, total_count=None, has_more=None,
                  next_upstream_page=None, first_fetched_at=None, last_fetched_at=None,
                  obtained_from="none", report_batch_id=None, report_included_count=0,
                  last_error=None, diagnostic=None, total_changed=False)
             for name, category in zip(tool_names, groups, strict=True)]
    uid = "11111111-1111-4111-8111-111111111111"
    instance = dict(session_id=uid, session_generation=1, subject_credit_code="91310000MA1ABCDEF0",
                    collection_revision=1, tools=tools, report_evidence_version=None, report_evidence_count=0)
    schema = {"$ref": collection["$id"] + "#/$defs/CollectionOverview"}
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    validator.validate(instance)
    model = generated.CollectionOverview.model_validate_json(json.dumps(instance))
    validator.validate(json.loads(model.model_dump_json()))
    routes = importlib.import_module("backend.collection_routes").router.routes
    assert {(method, route.path) for route in routes for method in route.methods} == COLLECTION_ROUTES
    dictionary = json.loads((ROOT / "contracts/text-dict.json").read_text(encoding="utf-8"))
    assert set(dictionary["collection"]) == {
        "cache_used", "collected_at", "not_live", "load_more", "read_next", "refresh",
        "browse_only", "refresh_failed", "total_changed",
    }


def check_collection_wiring() -> None:
    """COLLECTION-WIRING-1：已确认装配构造签名，不执行构造或存储业务。"""
    expected = {
        "src/company_screening/collections.py": ("CollectionService", ["self"],
            ["session_service", "company_data", "store", "scope_id", "clock", "task_submitter"]),
        "src/company_screening/adapters/collection_sqlite.py": ("SqliteCollectionStore", ["self", "database_path"], ["clock"]),
    }
    for relative, (class_name, positional, keyword) in expected.items():
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
        init = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
        assert [arg.arg for arg in init.args.args] == positional
        assert [arg.arg for arg in init.args.kwonlyargs] == keyword
    for relative, name in (("src/company_screening/services.py", "__init__"), ("backend/app.py", "create_app")):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                    and node.name == name and any(arg.arg == "collection_service" for arg in node.args.kwonlyargs))
        position = next(i for i, arg in enumerate(node.args.kwonlyargs) if arg.arg == "collection_service")
        default = node.args.kw_defaults[position]
        assert isinstance(default, ast.Constant) and default.value is None


def main() -> None:
    """只执行离线骨架检查，绝不调用占位业务方法。"""
    count = check_stub_bodies()
    check_signatures("src/company_screening/services.py", SERVICE_PARAMETERS)
    check_signatures("src/company_screening/ports.py", PORT_PARAMETERS)
    check_signatures("src/company_screening/collections.py", COLLECTION_PARAMETERS)
    routes = importlib.import_module("backend.routes").router.routes
    actual_routes = {(method, route.path) for route in routes for method in route.methods}
    assert actual_routes == EXPECTED_ROUTES
    check_shared_models()
    check_collection_declarations()
    check_collection_wiring()
    dictionary = json.loads((ROOT / "contracts/text-dict.json").read_text(encoding="utf-8"))
    assert set(get_args(ValidationMessageKey)) == set(dictionary["validation"])
    assert {item.value for item in generated.HintCode} == set(dictionary["hints"])
    diagnostic_copy = dictionary["query_diagnostics"]
    assert {item.value for item in generated.ReasonCode} == set(diagnostic_copy["reasons"])
    assert {item.value for item in generated.Phase} == set(diagnostic_copy["phases"])
    assert {item.value for item in generated.ToolName if item.value is not None} == set(diagnostic_copy["tools"])
    assert {item.value for item in generated.FieldModel if item.value is not None} == set(diagnostic_copy["fields"])
    for module in ("company_screening.contracts.boundary", "company_screening.services", "company_screening.ports", "company_screening.errors", "backend.app", "backend.dependencies", "backend.routes"):
        importlib.import_module(module)
    print(f"Contract structure OK: {len(IMPLEMENTED)} implemented functions/methods; {count} NotImplementedError functions; "
          f"{len(SERVICE_PARAMETERS) + len(COLLECTION_PARAMETERS)} service signatures; {len(PORT_PARAMETERS)} port signatures; "
          f"{len(EXPECTED_ROUTES)} legacy routes + {len(COLLECTION_ROUTES)} collection routes; "
          "shared/collection declaration mappings, Schema round-trips and dictionary keys.")
    print("Structure checks do not prove runtime behavior; see pytest and collection-browser-acceptance.md for verified scope. LLM is not connected.")


if __name__ == "__main__":
    main()
