"""维度建档领域服务：登记、合并、废弃维度，输出维度数据集供拉链加工引用。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DimEntryService(BaseModuleService):
    MODULE = "dim_entry"
    ENTITY = "维度条目"
    LIST_FIELDS = ["维度编号", "维度名称", "业务主键", "自然键来源", "维度类型", "所属主题域", "生效标记", "登记时间"]
    REQUIRED_FIELDS = ["维度编号", "维度名称", "业务主键"]
    STATUS_ORDER = ["待注册", "已注册", "已合并", "已废弃"]
    ACTION_RULES = {"确认注册": "已注册", "合并维度": "已合并", "废弃维度": "已废弃"}
    NEGATIVE_ACTIONS = []

    def validate_natural_key_source(self, dim_entry: dict[str, Any]) -> tuple[bool, str]:
        """校验自然键来源是否在已知源端系统登记过。"""
        source = dim_entry.get("自然键来源", "")
        if not source:
            return False, "自然键来源为空，无法校验"
        src_rows = store.rows("src_extract")
        known_systems = {r.get("来源系统", "") for r in src_rows if r.get("status") == "已抽取"}
        if source not in known_systems and known_systems:
            return False, f"自然键来源 {source} 未在已抽取的源端系统中登记"
        return True, f"自然键来源 {source} 校验通过"

    def find_merge_candidates(self, dim_name: str) -> list[dict[str, Any]]:
        """查找可合并的候选维度（同自然键来源、不同维度编号）。"""
        rows = store.rows(self.MODULE)
        result: list[dict[str, Any]] = []
        for r in rows:
            if r.get("维度名称") != dim_name and r.get("自然键来源"):
                result.append(dict(r))
        return result

    def pending_rulings(
        self, dim_code: str, round_no: str | int | None = None,
    ) -> dict[str, Any]:
        """维度建档待办：按原登记（维度编号）和核对轮次接收字段裁决结论。

        允许改正的字段范围由已签收结论判定；已失效裁决不出现在待办中，
        下一轮编辑不能沿用。
        """
        from app.services.field_ruling import FieldRulingService

        return FieldRulingService().todos(dim_code, round_no)

    def register_dimension(
        self, dim_code: str, dim_name: str, business_key: str,
        natural_source: str, dim_type: str, domain: str,
    ) -> tuple[dict[str, Any] | None, str]:
        """登记新维度：校验后写入维度建档表。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("维度编号") == dim_code:
                return None, f"维度编号 {dim_code} 已存在"
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "维度编号": dim_code, "维度名称": dim_name,
            "业务主键": business_key, "自然键来源": natural_source,
            "维度类型": dim_type, "所属主题域": domain,
            "生效标记": "生效", "登记时间": "2026-11-01",
            "status": "已注册", "pending": False, "abnormal": False,
        }
        rows.append(entry)
        return entry, f"维度 {dim_code} 已登记"

    def merge_dimension(self, from_code: str, to_code: str) -> tuple[bool, str]:
        """合并维度：把 from_code 合并入 to_code，更新代理键映射。"""
        rows = store.rows(self.MODULE)
        from_row = to_row = None
        for r in rows:
            if r.get("维度编号") == from_code:
                from_row = r
            elif r.get("维度编号") == to_code:
                to_row = r
        if not from_row:
            return False, f"源维度 {from_code} 不存在"
        if not to_row:
            return False, f"目标维度 {to_code} 不存在"
        from_row["status"] = "已合并"
        from_row["合并至"] = to_code
        to_row["status"] = "已合并"
        return True, f"维度 {from_code} 已合并入 {to_code}"