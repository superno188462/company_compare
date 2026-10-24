"""BE-ERR-01 / BE-IF-07：异常类型声明，不实现错误映射。"""

from .contracts.boundary import ErrorInfo, ModelFailureCode, ProviderFailureCode
from .contracts.generated import QueryDiagnostic


class ApplicationError(Exception):
    """应用错误；HTTP 层仅可传播脱敏的 info。"""

    info: ErrorInfo


class ProviderError(Exception):
    """外部查询失败，不代表空记录。"""

    code: ProviderFailureCode
    retryable: bool
    diagnostic: QueryDiagnostic | None = None


class ModelError(Exception):
    """模型端口失败，不自动重试。"""

    code: ModelFailureCode
