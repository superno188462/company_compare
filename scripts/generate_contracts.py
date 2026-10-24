"""离线从两个权威 JSON Schema 生成 Python/TypeScript 声明。

这是开发工具，不是应用业务实现。条件约束保留在原 Schema；生成投影
展开来源/分类状态的互斥分支，其他跨字段条件留待实现阶段按 SDD 验证。
不抓取远程 $ref，不修改原 Schema，不产生运行时请求能力。
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def rewrite_refs(value: Any) -> Any:
    """只重写本项目两个文件的引用，拒绝外部 schema 依赖。"""
    if isinstance(value, list):
        return [rewrite_refs(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: rewrite_refs(item) for key, item in value.items()}
    if "$ref" in result:
        ref = result["$ref"]
        for prefix in ("input-schema.json#/$defs/", "#/$defs/"):
            if ref.startswith(prefix):
                result["$ref"] = "#/definitions/" + ref[len(prefix) :]
                break
        else:
            raise ValueError(f"Unexpected schema reference: {ref}")
    return result


def expand_variants(definitions: dict[str, Any], name: str, names: list[str]) -> None:
    """展开现有 if/then 分支，生成同义类型联合，不新增业务字段。"""
    source = definitions[name]
    branches = source["allOf"]
    refs: list[dict[str, str]] = []
    for class_name, branch in zip(names, branches, strict=True):
        variant = copy.deepcopy(source)
        variant.pop("allOf")
        discriminator = branch["if"]["properties"]
        for field_name, rule in discriminator.items():
            variant["properties"][field_name].update(copy.deepcopy(rule))
        for field_name, rule in branch["then"]["properties"].items():
            original = variant["properties"][field_name]
            if "$ref" in rule or rule.get("type") == "null":
                replacement = copy.deepcopy(rule)
                if "description" in original:
                    replacement["description"] = original["description"]
                variant["properties"][field_name] = replacement
            else:
                original.update(copy.deepcopy(rule))
                if rule.get("type") == "string" and "enum" in original:
                    original["enum"] = [value for value in original["enum"] if isinstance(value, str)]
        variant["title"] = class_name
        definitions[class_name] = variant
        refs.append({"$ref": f"#/$defs/{class_name}"})
    definitions[name] = {"title": name, "oneOf": refs}


def build_bundle() -> dict[str, Any]:
    """构造仅供代码生成的本地投影，原 JSON Schema 始终为权威。"""
    source = json.loads((ROOT / "contracts/input-schema.json").read_text(encoding="utf-8"))
    output = json.loads((ROOT / "contracts/output-schema.json").read_text(encoding="utf-8"))
    definitions = copy.deepcopy(source["$defs"])
    definitions.update(copy.deepcopy(output["$defs"]))
    # URI 格式的模型类型会让生成器丢失 HTTP pattern/maxLength；声明投影使用
    # 原有字符串约束，完整 URI 校验仍以原 JSON Schema 为准。
    definitions["HttpUrl"].pop("format")
    expand_variants(definitions, "Evidence", ["TianyanEvidence", "OtherUserEvidence", "SelfUserEvidence"])
    expand_variants(definitions, "CategoryResult", ["OkCategoryResult", "EmptyCategoryResult", "ErrorCategoryResult", "NotRequestedCategoryResult"])
    definitions["SnapshotDraft"]["properties"]["evidence"] = {"$ref": "#/$defs/OtherUserEvidence"}
    # 生成器不应把 if/then 的局部字段误生成为可独立调用的应用模型。
    # 完整条件仍由原 output-schema.json 约束，骨架不实现该校验。
    definitions["WorkflowStatus"].pop("allOf")
    # 仅展开诊断映射的引用，让可选字段的{}默认值保持字典类型。
    # 部分生成器会把 RootModel 引用的默认{}生成为不合法的模型赋值；
    # 展开不改变机器Schema的可选键、白名单、值约束或空对象语义。
    diagnostics_property = definitions["WorkflowStatus"]["properties"].get("query_diagnostics")
    if diagnostics_property is not None:
        definitions["WorkflowStatus"]["properties"]["query_diagnostics"] = {
            **copy.deepcopy(definitions["QueryDiagnostics"]),
            **{key: value for key, value in diagnostics_property.items() if key != "$ref"},
        }
    for name, document in (("LlmInput", source), ("WorkflowPayload", output)):
        model = {key: copy.deepcopy(value) for key, value in document.items() if key not in {"$schema", "$id", "$defs", "allOf"}}
        model["title"] = name
        definitions[name] = model
    bundle = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "GeneratedContractBundle",
        "type": "object",
        "additionalProperties": False,
        "definitions": definitions,
        "properties": {
            "llm_input": {"$ref": "#/$defs/LlmInput"},
            "workflow_payload": {"$ref": "#/$defs/WorkflowPayload"},
        },
        "required": ["llm_input", "workflow_payload"],
    }
    return rewrite_refs(bundle)


def main() -> None:
    """运行已锁定的本地生成工具；不请求任何远程 schema。"""
    python_output = ROOT / "src/company_screening/contracts/generated.py"
    ts_output = ROOT / "frontend/src/contracts/generated.ts"
    python_output.parent.mkdir(parents=True, exist_ok=True)
    ts_output.parent.mkdir(parents=True, exist_ok=True)
    package = ROOT / "frontend/node_modules/json-schema-to-typescript"
    package_metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
    cli = package / package_metadata["bin"]["json2ts"]
    with tempfile.TemporaryDirectory(prefix="company-screening-types-") as directory:
        schema_path = Path(directory) / "contract-bundle.json"
        schema_path.write_text(json.dumps(build_bundle(), ensure_ascii=False, indent=2), encoding="utf-8")
        subprocess.run(
            [sys.executable, "-m", "datamodel_code_generator", "--input", str(schema_path), "--input-file-type", "jsonschema", "--output", str(python_output), "--output-model-type", "pydantic_v2.BaseModel", "--target-python-version", "3.12", "--field-constraints", "--use-annotated", "--use-standard-collections", "--use-union-operator", "--use-schema-description", "--strict-nullable", "--strict-types", "str", "int", "float", "bool", "--extra-fields", "forbid", "--base-class", "company_screening.contracts.base.ContractModel", "--disable-timestamp", "--no-allow-remote-refs", "--formatters", "black", "isort"],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(["node", str(cli), "-i", str(schema_path), "-o", str(ts_output), "--unreachableDefinitions"], cwd=ROOT, check=True)
    print("Generated Python and TypeScript contract declarations from local schemas.")


if __name__ == "__main__":
    main()
