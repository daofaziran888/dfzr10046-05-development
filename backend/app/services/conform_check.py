"""一致性核对领域服务：跨主题域核对维度一致的校验，不匹配键数不为零时阻断事实装配，产出核对条目数据集。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class ConformCheckService(BaseModuleService):
    MODULE = "conform_check"
    ENTITY = "核对条目"
    LIST_FIELDS = ["核对编号", "基准维度", "对照维度", "核对粒度", "匹配键数", "不匹配键数", "核对结论", "核对时间"]
    REQUIRED_FIELDS = ["核对编号", "基准维度", "对照维度"]
    STATUS_ORDER = ["待核对", "核对中", "已一致", "存在偏差"]
    ACTION_RULES = {"启动核对": "核对中", "确认一致": "已一致", "登记偏差": "存在偏差"}
    NEGATIVE_ACTIONS = []

    def check_conformity(
        self, base_dim: str, ref_dim: str, granularity: str,
    ) -> tuple[bool, str, dict[str, Any]]:
        """核对跨主题域的共用维度是否一致。不匹配键数不为零时相关事实表不得直接装配。"""
        dim_rows = store.rows("dim_entry")
        base_keys = {r.get("业务主键") for r in dim_rows if r.get("维度名称") == base_dim}
        ref_keys = {r.get("业务主键") for r in dim_rows if r.get("维度名称") == ref_dim}
        matched = base_keys & ref_keys
        unmatched = len(base_keys - ref_keys) + len(ref_keys - base_keys)

        if unmatched > 0:
            return False, (
                f"维度 {base_dim} 与 {ref_dim} 在粒度 {granularity} 存在偏差："
                f"匹配 {len(matched)} 键，不匹配 {unmatched} 键"
            ), {
                "ok": False, "matched": len(matched), "unmatched": unmatched,
                "conclusion": "存在偏差",
            }
        return True, (
            f"维度 {base_dim} 与 {ref_dim} 一致性核对通过：{len(matched)} 键全部匹配"
        ), {
            "ok": True, "matched": len(matched), "unmatched": 0,
            "conclusion": "已一致",
        }

    def block_fact_assembly(self, dimension: str) -> tuple[bool, str]:
        """检查是否应阻断该维度的事实表装配。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if (r.get("基准维度") == dimension or r.get("对照维度") == dimension) \
                    and r.get("status") == "存在偏差":
                return True, f"维度 {dimension} 存在一致性偏差，阻断事实装配"
        return False, f"维度 {dimension} 核对一致，允许装配"

    def submit_field_rulings(
        self, check_code: str, registration: str, round_no: int,
        rulings: list[dict[str, Any]], operator: str = "核对员",
    ) -> tuple[bool, str, list[dict[str, Any]]]:
        """核对员入口：把核对结论按字段独立裁决（采用某边的值/退回/暂缓）。

        两份客户维度登记不再只能一起通过或退回；裁决按登记轮次生效，
        结论同步到维度建档待办，由建档员按原登记和核对轮次改正。
        """
        from app.services.field_ruling import FieldRulingService

        return FieldRulingService().adjudicate(
            check_code, registration, round_no, rulings, operator,
        )