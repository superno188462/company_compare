"""CONTRACT-1.0，SDD BE-DATA-01 / DATA-01～03。

这些用例只验证已确认的机器契约，不把 Schema 通过等同于业务规则满足。
"""
import pytest
from jsonschema import ValidationError


def test_valid_input_and_output(validators, evidence_input, payload):
    """BE-DATA-01：最小有效证据输入和完整输出可离线校验。"""
    validators[0].validate(evidence_input)
    validators[1].validate(payload)
    assert set(payload) == {"subject", "evidence_list", "summary_text", "api_status", "ui_hint_group"}


@pytest.mark.parametrize("field", ["question", "system_prompt", "tools", "actor_id", "draft"])
def test_model_input_rejects_unapproved_top_level_fields(validators, evidence_input, field):
    """DATA-03 / BE-IF-05：模型不接收提问、提示词覆盖、工具、身份或草稿。"""
    evidence_input[field] = "不应进入模型"
    with pytest.raises(ValidationError):
        validators[0].validate(evidence_input)


@pytest.mark.parametrize("size,accepted", [(0, False), (1, True), (200, True), (201, False)])
def test_evidence_count_boundary(validators, evidence_input, size, accepted):
    """DATA-03：输入1～200条；编号唯一性另由业务测试负责。"""
    evidence = evidence_input["evidence_list"][0]
    evidence_input["evidence_list"] = [{**evidence, "evidence_id": f"E-T-{i}"} for i in range(size)]
    errors = list(validators[0].iter_errors(evidence_input))
    assert (not errors) is accepted


@pytest.mark.parametrize("length,accepted", [(0, False), (1, True), (4000, True), (4001, False)])
def test_content_length_boundary(validators, evidence_input, length, accepted):
    """BE-DATA-01 / DATA-03：正文长度不能为0或超过4000字符；纯空白另测。"""
    evidence_input["evidence_list"][0]["content"] = "字" * length
    assert (not list(validators[0].iter_errors(evidence_input))) is accepted


@pytest.mark.parametrize("source,hint,needs_url", [
    ("tianyan", "SOURCE_TIANYAN", False),
    ("user_other", "SOURCE_USER_OTHER", True),
    ("user_self", "SOURCE_USER_SELF", False),
])
def test_source_and_hint_must_agree(validators, evidence_input, source, hint, needs_url):
    """DATA-01：三类来源提示一一对应；用户不能被描述为官方核验。"""
    evidence = evidence_input["evidence_list"][0]
    evidence.update(source=source, hint_id=hint)
    if needs_url:
        evidence["source_url"] = "https://example.invalid/public-record"
    validators[0].validate(evidence_input)
    evidence["hint_id"] = "SOURCE_USER_SELF" if hint != "SOURCE_USER_SELF" else "SOURCE_TIANYAN"
    with pytest.raises(ValidationError):
        validators[0].validate(evidence_input)


@pytest.mark.parametrize("field,value", [
    ("verification_status", "official_verified"), ("source", "official"),
    ("source_url", "javascript:alert(1)"), ("source_url", "file:///private"),
    ("snapshot_time", "2026-10-23T08:00:00"),
    ("subject_credit_code", "short"),
])
def test_evidence_rejects_false_verification_and_bad_formats(validators, evidence_input, field, value):
    """DATA-01：禁止伪核验来源，时间需时区，链接和代码需合法格式。"""
    evidence_input["evidence_list"][0][field] = value
    with pytest.raises(ValidationError):
        validators[0].validate(evidence_input)


@pytest.mark.parametrize("source,field", [("user_other", "source_url"), ("user_other", "snapshot_time"), ("tianyan", "snapshot_time")])
def test_required_source_metadata_cannot_be_null(validators, evidence_input, source, field):
    """DATA-01/04：他人材料需链接与原时间，平台记录需取得时间。"""
    evidence_input["evidence_list"][0].update(source=source, hint_id={
        "user_other": "SOURCE_USER_OTHER", "tianyan": "SOURCE_TIANYAN"}[source],
        source_url="https://example.invalid/record")
    evidence_input["evidence_list"][0][field] = None
    with pytest.raises(ValidationError):
        validators[0].validate(evidence_input)


@pytest.mark.parametrize("status,count,error", [
    ("ok", 0, None), ("empty", 1, None), ("error", 1, "UPSTREAM_TIMEOUT"),
    ("error", 0, None), ("not_requested", 0, "UPSTREAM_TIMEOUT"),
])
def test_category_status_must_match_count_and_error(validators, evidence_input, status, count, error):
    """DATA-02：查询失败与无返回记录的结构语义不能混用。"""
    item = evidence_input["api_status"]["categories"]["basic"]
    item.update(status=status, record_count=count, error_code=error)
    if status == "not_requested":
        item["queried_at"] = None
    with pytest.raises(ValidationError):
        validators[0].validate(evidence_input)


@pytest.mark.parametrize("field,value", [("summary_evidence_version", None), ("summary_generated_at", None)])
def test_success_requires_report_version_and_timestamp(validators, payload, field, value):
    """DATA-03：成功报告必须带实际证据版本与时间。"""
    payload["api_status"][field] = value
    with pytest.raises(ValidationError):
        validators[1].validate(payload)


def test_skipped_report_has_no_evidence_or_old_report(validators, payload):
    """DATA-03：无证据跳过时，不能携带伪成功或旧报告。"""
    payload["evidence_list"] = []
    payload["summary_text"] = ""
    payload["api_status"].update(llm_status="skipped_no_evidence", summary_evidence_version=None,
                                 summary_generated_at=None)
    validators[1].validate(payload)
    payload["summary_text"] = "企业没有风险"
    with pytest.raises(ValidationError):
        validators[1].validate(payload)
