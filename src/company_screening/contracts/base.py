"""声明式模型基础配置；不实现跨字段业务校验。"""

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """拒绝未声明字段；业务与授权约束仍由权威 Schema/SDD 定义。"""

    model_config = ConfigDict(extra="forbid", validate_default=True)
