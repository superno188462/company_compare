"""CONTRACT-1.0：BE-DATA-02、BE-ERR-01；真实路由参数解析与错误包。

仅替换已批准的身份依赖，不替换路由、服务或数据校验。此 harness 不证明生产鉴权已实现。
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.dependencies import get_actor
from backend.app import create_app
from company_screening.contracts.boundary import ActorContext, ConfirmSubjectCommand, ErrorEnvelope, SearchCommand


@pytest.mark.parametrize("body", [{"query": ""}, {"query": "名" * 201}, {"query": 123},
    {"query": "测试企业甲", "page_size": 0}, {"query": "测试企业甲", "page_size": 21},
    {"query": "测试企业甲", "page_size": True}, {"query": "测试企业甲", "tools": []}])
def test_search_rejects_invalid_declarations(body):
    """BE-DATA-02：名称长度、严格数值及额外字段。"""
    with pytest.raises(ValidationError):
        SearchCommand.model_validate(body)


def test_confirmation_requires_real_booleans():
    """BE-DATA-02：字符串false不能冒充用户确认选择。"""
    with pytest.raises(ValidationError):
        ConfirmSubjectCommand(search_id=uuid4(), candidate_id=uuid4(),
                              expected_generation=0, discard_draft="false")


@pytest.mark.parametrize("body", [{"query": ""}, {"query": "测试企业甲", "page_size": True}])
def test_http_invalid_search_uses_contract_error_envelope(body):
    """BE-ERR-01：422必须是脱敏ErrorEnvelope，不能泄漏原始输入。"""
    app = create_app()
    app.dependency_overrides[get_actor] = lambda: ActorContext(actor_id=uuid4())
    with TestClient(app) as client:
        response = client.post(f"/api/v1/sessions/{uuid4()}/search", json=body,
                               headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 422
    envelope = ErrorEnvelope.model_validate(response.json())
    assert envelope.error.code == "INPUT_INVALID"
    assert envelope.error.fields
    assert set(response.json()) == {"error", "operation_id"}
