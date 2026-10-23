"""BE-ERR-01 / TEXT-1.1：用户确认通用文案后补充的HTTP错误验收。"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.dependencies import get_actor
from company_screening.contracts.boundary import ActorContext, ErrorEnvelope, ErrorInfo
from company_screening.contracts.generated import HintCode
from company_screening.errors import ApplicationError


@pytest.mark.parametrize("body,field,key", [
    ({"query": ""}, "query", "company_name_required"),
    ({"query": "字" * 201}, "query", "company_name_length"),
    ({"query": "测试企业甲", "page_size": True}, "page_size", "input_invalid"),
    ({"query": "测试企业甲", "tools": ["private-value"]}, "tools", "input_invalid"),
])
def test_validation_uses_specific_or_generic_dictionary_key(body, field, key):
    app = create_app()
    app.dependency_overrides[get_actor] = lambda: ActorContext(actor_id=uuid4())
    with TestClient(app) as client:
        response = client.post(f"/api/v1/sessions/{uuid4()}/search", json=body,
                               headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 422
    result = ErrorEnvelope.model_validate(response.json())
    assert result.error.code == "INPUT_INVALID"
    assert any(item.field == field and item.message_key == key for item in result.error.fields)
    assert "private-value" not in response.text
    assert "detail" not in response.json()


@pytest.mark.parametrize("code,hint,status", [
    ("RESOURCE_NOT_FOUND", HintCode.INTERNAL_ERROR, 404),
    ("SESSION_EXPIRED", HintCode.SESSION_EXPIRED, 410),
    ("OPERATION_CONFLICT", HintCode.OPERATION_CONFLICT, 409),
])
def test_application_error_status_and_body(code, hint, status):
    app = create_app()

    def fail():
        error = ApplicationError("private internal detail")
        error.info = ErrorInfo(code=code, hint_id=hint, fields=[], retryable=False)
        raise error

    app.add_api_route("/__test__/application-error", fail)
    with TestClient(app) as client:
        response = client.get("/__test__/application-error")
    assert response.status_code == status
    assert ErrorEnvelope.model_validate(response.json()).error.code == code
    assert "private internal detail" not in response.text


def test_unexpected_error_is_sanitized():
    app = create_app()

    def fail():
        raise RuntimeError("secret-company-record-and-token")

    app.add_api_route("/__test__/unexpected-error", fail)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__test__/unexpected-error")
    assert response.status_code == 500
    result = ErrorEnvelope.model_validate(response.json())
    assert result.error.code == "INTERNAL_ERROR"
    assert "secret-company-record-and-token" not in response.text


def test_api_schema_registers_existing_routes():
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/sessions" in paths
    assert "/api/v1/sessions/{sid}/confirm" in paths
    assert "/api/v1/shares/{receipt_id}/withdraw" in paths
