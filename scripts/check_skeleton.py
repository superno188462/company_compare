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
    "ReportModelPort.generate": ["self", "input", "system_prompt"],
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
    """应用函数只能保留文档字符串和无参数 NotImplementedError。"""
    count = 0
    for directory in (ROOT / "src", ROOT / "backend"):
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
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
    return count


def check_signatures(relative: str, expected: dict[str, list[str]]) -> None:
    """比较 SDD 中明确定义的公共方法名和参数顺序。"""
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    actual = {}
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef):
            for node in cls.body:
                if isinstance(node, ast.FunctionDef):
                    actual[f"{cls.name}.{node.name}"] = [arg.arg for arg in node.args.args]
    assert actual == expected, (relative, actual)


def check_shared_models() -> None:
    """核对模型字段/必填性，并验证声明式模型的 JSON 往返。"""
    inputs = json.loads((ROOT / "input-schema.json").read_text(encoding="utf-8"))
    outputs = json.loads((ROOT / "output-schema.json").read_text(encoding="utf-8"))
    definitions = {**inputs["$defs"], **outputs["$defs"], "LlmInput": inputs, "WorkflowPayload": outputs}
    for name in ("Subject", "CategoryResults", "QueryCoverage", "SnapshotDraft", "WorkflowStatus", "SubmissionReceipt", "LlmInput", "WorkflowPayload"):
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


def main() -> None:
    """只执行离线骨架检查，绝不调用占位业务方法。"""
    count = check_stub_bodies()
    check_signatures("src/company_screening/services.py", SERVICE_PARAMETERS)
    check_signatures("src/company_screening/ports.py", PORT_PARAMETERS)
    routes = importlib.import_module("backend.routes").router.routes
    actual_routes = {(method, route.path) for route in routes for method in route.methods}
    assert actual_routes == EXPECTED_ROUTES
    check_shared_models()
    dictionary = json.loads((ROOT / "text-dict.json").read_text(encoding="utf-8"))
    assert set(get_args(ValidationMessageKey)) == set(dictionary["validation"])
    assert {item.value for item in generated.HintCode} == set(dictionary["hints"])
    for module in ("company_screening.contracts.boundary", "company_screening.services", "company_screening.ports", "company_screening.errors", "backend.app", "backend.dependencies", "backend.routes"):
        importlib.import_module(module)
    print(f"Skeleton OK: {count} NotImplementedError functions; 13 service signatures; 3 port signatures; 13 routes; shared model/Schema round-trips and dictionary keys.")
    print("Business behavior, real providers, LLM and browser integration remain unimplemented/unverified.")


if __name__ == "__main__":
    main()
