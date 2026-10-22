"""BE-IF-07：可替换外部协作者，禁止在导入时创建实际客户端。"""

from typing import Protocol

from .contracts.boundary import ProviderCategoryBatch, ProviderSearchPage, SearchCommand
from .contracts.generated import Category, LlmInput, Subject


class CompanyDataPort(Protocol):
    """仅企业授权接口能力，无任意网页访问能力。"""

    def search(self, command: SearchCommand) -> ProviderSearchPage:
        """搜索候选；不得代用户选择。"""
        raise NotImplementedError()

    def fetch_category(self, subject: Subject, category: Category) -> ProviderCategoryBatch:
        """返回完整分类批次；不完整取得应抛 ProviderError。"""
        raise NotImplementedError()


class ReportModelPort(Protocol):
    """只读固定输入的文本分析节点，无工具调用。"""

    def generate(self, input: LlmInput, system_prompt: str) -> str:
        """返回报告原文；超时或接入错误抛 ModelError。"""
        raise NotImplementedError()
