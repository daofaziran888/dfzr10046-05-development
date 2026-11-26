"""字段裁决领域服务：一致性核对结论按字段独立裁决，裁决按登记轮次生效并同步为维度建档待办。

核对员按字段选择采用某边的值、退回或暂缓；维度建档按原登记和核对轮次接收待办，
建档员签收后改正落库；核对员可在写入前撤回。改名写入与撤回并发时由同一把锁
保证「检查状态 → 迁移状态」原子完成，同一字段只有一笔改正生效；已写入的名字
和历轮意见都可按原登记查询。
"""
from __future__ import annotations

import threading
from datetime import date
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 可裁决字段 → 维度建档落库列
ADJUDICABLE_FIELDS = {"显示名": "维度名称", "客户号": "业务主键"}
# 核对员可选的字段裁决结论
DECISIONS = {"采用基准值", "采用对照值", "退回", "暂缓"}
ADOPT_DECISIONS = {"采用基准值", "采用对照值"}
LIVE_STATUSES = {"待签收", "已签收"}

# 内存仓库被多个请求线程共享。裁决状态机的所有迁移都在这把锁下完成，
# 保证改名、撤回、重提并发时只有一笔改正生效，且两边都能查到同一个结论。
RULING_LOCK = threading.RLock()


def _today() -> str:
    return date.today().isoformat()


class FieldRulingService(BaseModuleService):
    MODULE = "field_ruling"
    ENTITY = "字段裁决"
    LIST_FIELDS = ["裁决编号", "核对编号", "原登记", "核对轮次", "裁决字段",
                   "基准值", "对照值", "裁决结论", "裁决时间"]
    REQUIRED_FIELDS = ["裁决编号", "核对编号", "原登记", "核对轮次", "裁决字段", "裁决结论"]
    STATUS_ORDER = ["待签收", "已签收", "已写入", "已撤回", "已失效"]
    ACTION_RULES = {"签收裁决": "已签收", "写入改正": "已写入", "撤回裁决": "已撤回"}
    NEGATIVE_ACTIONS = ["撤回裁决"]

    # ------------------------------------------------------------------
    # 核对员入口：按字段裁决，结论同步到维度建档待办
    # ------------------------------------------------------------------
    def adjudicate(
        self,
        check_code: str,
        registration: str,
        round_no: int,
        rulings: list[dict[str, Any]],
        operator: str = "核对员",
        ruling_code: str | None = None,
        today: str | None = None,
    ) -> tuple[bool, str, list[dict[str, Any]]]:
        """核对员对一份原登记按字段下达裁决（采用某边的值/退回/暂缓）。

        裁决按登记轮次生效：同一字段只保留一条生效中裁决，新裁决会让旧裁决失效；
        非暂缓裁决同步为维度建档待办。
        """
        today = today or _today()
        with RULING_LOCK:
            ok, message = self._validate_adjudicate(check_code, registration, round_no, rulings)
            if not ok:
                return False, message, []

            created: list[dict[str, Any]] = []
            for item in rulings:
                code = ruling_code if ruling_code and len(rulings) == 1 else self._next_code()
                self._expire_prior(registration, item["裁决字段"], round_no, code, today)
                row = self._new_ruling_row(
                    code, check_code, registration, round_no, item, operator, today,
                )
                store.rows(self.MODULE).append(row)
                created.append(row)
            self._sync_dim_todo(registration)

        fields_desc = "、".join(f"{r['裁决字段']}:{r['裁决结论']}" for r in created)
        return True, (
            f"第{round_no}轮字段裁决已下达（{fields_desc}），"
            f"核对结论已同步到维度建档{registration}待办"
        ), created

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """通用登记入口：按单条字段裁决处理，走与核对员提交相同的状态机。"""
        missing = [
            field for field in self.REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing
        try:
            round_no = int(str(values.get("核对轮次")).strip())
        except ValueError:
            return None, ["核对轮次必须为整数"]
        ok, message, created = self.adjudicate(
            str(values["核对编号"]).strip(),
            str(values["原登记"]).strip(),
            round_no,
            [{
                "裁决字段": str(values.get("裁决字段") or "").strip(),
                "基准值": str(values.get("基准值") or "").strip(),
                "对照值": str(values.get("对照值") or "").strip(),
                "裁决结论": str(values.get("裁决结论") or "").strip(),
            }],
            operator=str(values.get("操作者") or "核对员"),
            ruling_code=str(values["裁决编号"]).strip(),
        )
        if not ok:
            return None, [message]
        return created[0], []

    # ------------------------------------------------------------------
    # 建档员入口：签收、改正落库
    # ------------------------------------------------------------------
    def sign_ruling(self, ruling_id: int, operator: str = "建档员") -> tuple[bool, str]:
        """建档员签收裁决：已签收结论决定允许改正的字段范围。暂缓与已失效裁决不可签收。"""
        with RULING_LOCK:
            row = store.find(self.MODULE, ruling_id)
            if row is None:
                return False, f"字段裁决 {ruling_id} 不存在或已归档"
            if row.get("裁决结论") == "暂缓":
                return False, f"裁决 {row['裁决编号']} 为暂缓，不参与签收，待下一轮重新裁决"
            status = row.get("status")
            if status == "已失效":
                return False, f"裁决 {row['裁决编号']} 已失效，下一轮编辑不能沿用，需按新一轮裁决签收"
            if status != "待签收":
                return False, f"裁决 {row['裁决编号']} 当前为{status}，不能签收"
            row["status"] = "已签收"
            row["签收时间"] = _today()
            self._append_opinion(row, operator, "建档签收",
                                 f"已签收第{row['核对轮次']}轮{row['裁决字段']}裁决，进入允许改正范围")
        return True, f"裁决 {row['裁决编号']} 已签收，字段「{row['裁决字段']}」进入允许改正范围"

    def apply_correction(
        self, ruling_id: int, operator: str = "建档员", corrected_value: str | None = None,
    ) -> tuple[bool, str]:
        """建档员按已签收裁决把改正写入维度建档。

        采用类裁决写入裁决目标值；退回裁决必须由建档员提供改正值。
        与撤回并发时只有一笔生效：本方法在锁内完成状态检查与落库。
        """
        with RULING_LOCK:
            row = store.find(self.MODULE, ruling_id)
            if row is None:
                return False, f"字段裁决 {ruling_id} 不存在或已归档"
            status = row.get("status")
            if status == "已撤回":
                return False, f"裁决 {row['裁决编号']} 已被核对员撤回，旧指令无资格落库"
            if status == "已失效":
                return False, f"裁决 {row['裁决编号']} 已失效，不能沿用，需按新一轮裁决签收"
            if status == "已写入":
                return False, f"裁决 {row['裁决编号']} 已写入，重复落库被拒绝"
            if status != "已签收":
                return False, f"裁决 {row['裁决编号']} 未签收，不在允许改正的字段范围内"

            decision = row.get("裁决结论")
            if decision in ADOPT_DECISIONS:
                value = str(row.get("目标值") or "")
            elif decision == "退回":
                value = (corrected_value or "").strip()
                if not value:
                    return False, f"裁决 {row['裁决编号']} 已退回字段，需建档员提供改正值"
            else:
                return False, f"裁决 {row['裁决编号']} 为暂缓，不可落库"

            dim_row = self._find_dim(row["原登记"])
            if dim_row is None:
                return False, f"原登记 {row['原登记']} 在维度建档中不存在"
            column = ADJUDICABLE_FIELDS[row["裁决字段"]]
            old_value = str(dim_row.get(column, ""))
            dim_row[column] = value

            row["status"] = "已写入"
            row["pending"] = False
            row["旧值"] = old_value
            row["写入值"] = value
            row["写入时间"] = _today()
            self._append_opinion(
                row, operator, "改正落库",
                f"按第{row['核对轮次']}轮裁决将{row['原登记']}的{row['裁决字段']}"
                f"由「{old_value}」改正为「{value}」",
            )
            self._sync_dim_todo(row["原登记"])
        return True, (
            f"裁决 {row['裁决编号']} 已落库：{row['原登记']}的{row['裁决字段']}"
            f"由「{old_value}」改正为「{value}」"
        )

    # ------------------------------------------------------------------
    # 核对员撤回：建档端已接收改名指令但还未写入时可撤回
    # ------------------------------------------------------------------
    def withdraw_ruling(self, ruling_id: int, operator: str = "核对员") -> tuple[bool, str]:
        """核对员撤回未写入的裁决。已写入的裁决不可撤回，只能发起下一轮。

        与改名写入并发时只有一笔生效：撤回赢则旧指令失去落库资格、核对员可立即
        发下一轮；写入赢则撤回不生效，结论两边都可按原登记查到。
        """
        with RULING_LOCK:
            row = store.find(self.MODULE, ruling_id)
            if row is None:
                return False, f"字段裁决 {ruling_id} 不存在或已归档"
            status = row.get("status")
            if status == "已写入":
                return False, (
                    f"裁决 {row['裁决编号']} 已写入落库，撤回未生效；"
                    f"如需变更请发起第{int(row['核对轮次']) + 1}轮裁决"
                )
            if status in ("已撤回", "已失效"):
                return False, f"裁决 {row['裁决编号']} 已{status}，无需撤回"
            row["status"] = "已撤回"
            row["pending"] = False
            row["撤回时间"] = _today()
            self._append_opinion(row, operator, "核对撤回",
                                 "核对员撤回裁决，旧指令失去落库资格，可立即发起下一轮")
            self._sync_dim_todo(row["原登记"])
        return True, f"裁决 {row['裁决编号']} 已撤回，旧指令失去落库资格，可立即发起下一轮"

    # ------------------------------------------------------------------
    # 通用动作入口：签收裁决 / 写入改正 / 撤回裁决
    # ------------------------------------------------------------------
    def run_action(
        self, entry_id: int, action: str, remark: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        if action == "签收裁决":
            ok, message = self.sign_ruling(entry_id)
        elif action == "写入改正":
            ok, message = self.apply_correction(entry_id, corrected_value=remark)
        elif action == "撤回裁决":
            ok, message = self.withdraw_ruling(entry_id)
        else:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围"
        if not ok:
            return None, message
        return store.find(self.MODULE, entry_id), message

    # ------------------------------------------------------------------
    # 维度建档待办与历程查询
    # ------------------------------------------------------------------
    def todos(
        self, registration: str, round_no: str | int | None = None,
    ) -> dict[str, Any]:
        """维度建档按原登记和核对轮次接收的待办；允许改正的字段范围由已签收结论判定。"""
        with RULING_LOCK:
            rows = [
                dict(r) for r in store.rows(self.MODULE)
                if r.get("原登记") == registration
                and r.get("status") in LIVE_STATUSES
                and r.get("裁决结论") != "暂缓"
                and (round_no is None or str(r.get("核对轮次")) == str(round_no))
            ]
            rows.sort(key=lambda r: (str(r.get("核对轮次")), int(r.get("id", 0))))
            allowed = sorted({r["裁决字段"] for r in rows if r.get("status") == "已签收"})
        return {
            "原登记": registration,
            "核对轮次": None if round_no is None else str(round_no),
            "待办": rows,
            "允许改正字段": allowed,
        }

    def history(self, registration: str) -> dict[str, Any]:
        """按原登记查询已写入的名字和历轮意见。"""
        with RULING_LOCK:
            rows = [
                dict(r) for r in store.rows(self.MODULE)
                if r.get("原登记") == registration
            ]
            rows.sort(key=lambda r: (int(r.get("核对轮次") or 0), int(r.get("id", 0))))
        written = [
            {
                "裁决编号": r["裁决编号"],
                "裁决字段": r["裁决字段"],
                "旧值": r.get("旧值", ""),
                "新值": r.get("写入值", ""),
                "核对轮次": r["核对轮次"],
                "写入时间": r.get("写入时间", ""),
            }
            for r in rows if r.get("status") == "已写入"
        ]
        rounds = [
            {
                "裁决编号": r["裁决编号"],
                "核对轮次": r["核对轮次"],
                "裁决字段": r["裁决字段"],
                "裁决结论": r["裁决结论"],
                "当前状态": r["status"],
                "意见记录": list(r.get("意见记录", [])),
            }
            for r in rows
        ]
        return {"原登记": registration, "已写入": written, "历轮意见": rounds}

    # ------------------------------------------------------------------
    # 内部：校验、失效、落库辅助（调用方必须已持有 RULING_LOCK）
    # ------------------------------------------------------------------
    def _validate_adjudicate(
        self, check_code: str, registration: str, round_no: int, rulings: list[dict[str, Any]],
    ) -> tuple[bool, str]:
        if not rulings:
            return False, "字段裁决不能为空"
        checks = store.rows("conform_check")
        if not any(r.get("核对编号") == check_code for r in checks):
            return False, f"核对编号 {check_code} 不存在，无法下达字段裁决"
        if self._find_dim(registration) is None:
            return False, f"原登记 {registration} 在维度建档中不存在"
        if round_no < 1:
            return False, "核对轮次必须为正整数"
        existing_rounds = [
            int(r.get("核对轮次") or 0) for r in store.rows(self.MODULE)
            if r.get("原登记") == registration
        ]
        if existing_rounds and round_no < max(existing_rounds):
            return False, (
                f"核对轮次 {round_no} 已失效，{registration} 当前有效轮次为 "
                f"{max(existing_rounds)}，下一轮编辑不能沿用旧轮次"
            )
        seen_fields: set[str] = set()
        for item in rulings:
            field = str(item.get("裁决字段") or "").strip()
            decision = str(item.get("裁决结论") or "").strip()
            if field not in ADJUDICABLE_FIELDS:
                return False, f"字段「{field}」不在可裁决范围（{'、'.join(sorted(ADJUDICABLE_FIELDS))}）"
            if field in seen_fields:
                return False, f"字段「{field}」在同一轮重复裁决"
            seen_fields.add(field)
            if decision not in DECISIONS:
                return False, f"裁决结论「{decision}」无效，可选：{'、'.join(sorted(DECISIONS))}"
            if decision == "采用基准值" and not str(item.get("基准值") or "").strip():
                return False, f"字段「{field}」采用基准值但基准值为空"
            if decision == "采用对照值" and not str(item.get("对照值") or "").strip():
                return False, f"字段「{field}」采用对照值但对照值为空"
        return True, "校验通过"

    def _new_ruling_row(
        self, code: str, check_code: str, registration: str, round_no: int,
        item: dict[str, Any], operator: str, today: str,
    ) -> dict[str, Any]:
        decision = str(item["裁决结论"]).strip()
        base_value = str(item.get("基准值") or "").strip()
        ref_value = str(item.get("对照值") or "").strip()
        target = ""
        if decision == "采用基准值":
            target = base_value
        elif decision == "采用对照值":
            target = ref_value
        rows = store.rows(self.MODULE)
        row: dict[str, Any] = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "裁决编号": code,
            "核对编号": check_code,
            "原登记": registration,
            "核对轮次": str(round_no),
            "裁决字段": str(item["裁决字段"]).strip(),
            "基准值": base_value,
            "对照值": ref_value,
            "裁决结论": decision,
            "裁决时间": today,
            "目标值": target,
            "status": "待签收",
            "pending": decision != "暂缓",
            "abnormal": False,
            "意见记录": [],
        }
        opinion = f"第{round_no}轮核对裁决：{decision}"
        if target:
            opinion += f"，目标值「{target}」"
        if decision == "暂缓":
            opinion += "，暂不生成建档待办"
        self._append_opinion(row, operator, "核对裁决", opinion, today)
        return row

    def _expire_prior(
        self, registration: str, field: str, round_no: int, new_code: str, today: str,
    ) -> None:
        """同一字段只保留一条生效中裁决：新裁决下达后旧的未写入裁决失效。"""
        for r in store.rows(self.MODULE):
            if (
                r.get("原登记") == registration
                and r.get("裁决字段") == field
                and r.get("status") in LIVE_STATUSES
            ):
                r["status"] = "已失效"
                r["pending"] = False
                r["失效时间"] = today
                self._append_opinion(
                    r, "系统", "裁决失效",
                    f"被第{round_no}轮裁决 {new_code} 取代，已失效；下一轮编辑不得沿用",
                    today,
                )

    def _sync_dim_todo(self, registration: str) -> None:
        """把核对结论同步为维度建档待办：存在生效中裁决时原登记挂起待办。"""
        dim_row = self._find_dim(registration)
        if dim_row is None:
            return
        live = [
            r for r in store.rows(self.MODULE)
            if r.get("原登记") == registration
            and r.get("status") in LIVE_STATUSES
            and r.get("裁决结论") != "暂缓"
        ]
        dim_row["核对待办"] = len(live)
        dim_row["pending"] = bool(live) or dim_row.get("status") == "待注册"

    def _find_dim(self, registration: str) -> dict[str, Any] | None:
        for r in store.rows("dim_entry"):
            if r.get("维度编号") == registration:
                return r
        return None

    def _next_code(self) -> str:
        rows = store.rows(self.MODULE)
        return f"FR-{max((int(r.get('id', 0)) for r in rows), default=0) + 1:04d}"

    @staticmethod
    def _append_opinion(
        row: dict[str, Any], operator: str, stage: str, opinion: str,
        today: str | None = None,
    ) -> None:
        row.setdefault("意见记录", []).append({
            "时间": today or _today(),
            "操作者": operator,
            "环节": stage,
            "意见": opinion,
        })
