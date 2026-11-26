"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class RulingItemPayload(BaseModel):
    """单条字段裁决：核对员对某字段采用某边的值、退回或暂缓。"""
    裁决字段: str
    基准值: str = ""
    对照值: str = ""
    裁决结论: str


class AdjudicatePayload(BaseModel):
    """核对员按原登记和核对轮次批量下达字段裁决。"""
    核对编号: str
    原登记: str
    核对轮次: int
    操作者: str = "核对员"
    rulings: list[RulingItemPayload] = Field(default_factory=list)
