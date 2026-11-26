"""字段裁决专用接口：核对员按字段下达裁决、维度建档按原登记和核对轮次接收待办、
已写入的名字和历轮意见按原登记查询。

通用资源路由（/api/{module}/...）仍负责字段裁决数据集的列表、登记、导出和动作，
这里只承载通用路由表达不了的跨模块入口。路由必须先于通用资源路由注册，
否则 /api/field_ruling/todos 这类路径会被 /api/{module}/{entry_id} 抢先匹配。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, AdjudicatePayload
from app.services import service_for
from app.services.field_ruling import FieldRulingService

router = APIRouter(prefix="/api/field_ruling", tags=["字段裁决"])


def _ruling_service() -> FieldRulingService:
    service = service_for("field_ruling")
    if not isinstance(service, FieldRulingService):
        raise HTTPException(status_code=404, detail="字段裁决模块未登记")
    return service


@router.post("/adjudicate", response_model=ActionResult)
def adjudicate(payload: AdjudicatePayload) -> ActionResult:
    """核对员入口：对一份原登记按字段下达一轮裁决，结论同步到维度建档待办。"""
    service = _ruling_service()
    ok, message, created = service.adjudicate(
        payload.核对编号,
        payload.原登记,
        payload.核对轮次,
        [item.model_dump() for item in payload.rulings],
        operator=payload.操作者,
    )
    return ActionResult(
        ok=ok, message=message,
        entry={"items": created} if ok else None,
    )


@router.get("/todos")
def ruling_todos(
    registration: str = Query(alias="原登记"),
    round_no: str | None = Query(default=None, alias="核对轮次"),
) -> dict[str, Any]:
    """维度建档待办：按原登记和核对轮次接收的字段裁决，含允许改正的字段范围。"""
    return _ruling_service().todos(registration, round_no)


@router.get("/history")
def ruling_history(registration: str = Query(alias="原登记")) -> dict[str, Any]:
    """按原登记查询已写入的名字和历轮意见。"""
    return _ruling_service().history(registration)
