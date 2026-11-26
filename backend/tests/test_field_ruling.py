"""字段裁决链路测试：按字段独立裁决、按轮次生效、建档待办同步、撤回与写入并发。

验收场景：两个窗口在显示名上重叠触发改正和撤销，再单独退回客户号。
"""
from __future__ import annotations

import copy
import threading

import pytest

from app.services.conform_check import ConformCheckService
from app.services.dim_entry import DimEntryService
from app.services.field_ruling import FieldRulingService
from app.store import store

TABLES = ("field_ruling", "dim_entry", "conform_check")


@pytest.fixture(autouse=True)
def restore_tables():
    """每个用例前后快照并还原相关数据表，保证用例互不污染。"""
    snapshot = {name: copy.deepcopy(store.rows(name)) for name in TABLES}
    yield
    for name, rows in snapshot.items():
        store.rows(name)[:] = rows


def _seed_registration(
    dim_code: str = "DIM-T001",
    dim_name: str = "客户维度A",
    biz_key: str = "cust_001",
    check_code: str = "CC-T001",
) -> None:
    """造一份客户维度登记和一条一致性核对条目，模拟两份登记一起核对的场景。"""
    dim_rows = store.rows("dim_entry")
    dim_rows.append({
        "id": max((int(r.get("id", 0)) for r in dim_rows), default=0) + 1,
        "status": "已注册", "pending": False, "abnormal": False,
        "维度编号": dim_code, "维度名称": dim_name, "业务主键": biz_key,
        "自然键来源": "ERP", "维度类型": "SCD2", "所属主题域": "客户",
        "生效标记": "生效", "登记时间": "2026-11-01",
    })
    check_rows = store.rows("conform_check")
    check_rows.append({
        "id": max((int(r.get("id", 0)) for r in check_rows), default=0) + 1,
        "status": "存在偏差", "pending": True, "abnormal": True,
        "核对编号": check_code, "基准维度": dim_name, "对照维度": f"{dim_name}@ERP",
        "核对粒度": "客户级", "匹配键数": "199", "不匹配键数": "1",
        "核对结论": "存在偏差", "核对时间": "2026-11-20",
    })


def _dim(dim_code: str) -> dict:
    for row in store.rows("dim_entry"):
        if row.get("维度编号") == dim_code:
            return row
    raise AssertionError(f"维度建档中不存在 {dim_code}")


def _display_name_ruling() -> dict:
    return {"裁决字段": "显示名", "基准值": "客户维度A",
            "对照值": "客户维度A@ERP", "裁决结论": "采用对照值"}


class TestAdjudicateAndTodoSync:
    def test_adjudicate_syncs_dim_todo(self):
        _seed_registration()
        svc = FieldRulingService()
        ok, msg, created = svc.adjudicate("CC-T001", "DIM-T001", 1, [_display_name_ruling()])
        assert ok, msg
        assert created[0]["status"] == "待签收"
        assert created[0]["目标值"] == "客户维度A@ERP"
        # 核对结论同步到维度建档待办
        assert _dim("DIM-T001")["pending"] is True
        assert _dim("DIM-T001")["核对待办"] == 1
        todos = svc.todos("DIM-T001", 1)
        assert [t["裁决编号"] for t in todos["待办"]] == [created[0]["裁决编号"]]
        # 未签收时没有允许改正的字段
        assert todos["允许改正字段"] == []

    def test_signed_scope_allows_correction(self):
        _seed_registration()
        svc = FieldRulingService()
        _, _, created = svc.adjudicate("CC-T001", "DIM-T001", 1, [_display_name_ruling()])
        rid = created[0]["id"]
        # 未签收不在允许改正范围，写入被拒
        ok, msg = svc.apply_correction(rid)
        assert not ok and "未签收" in msg
        # 签收后进入允许改正范围，可以写入
        ok, msg = svc.sign_ruling(rid)
        assert ok, msg
        assert svc.todos("DIM-T001")["允许改正字段"] == ["显示名"]
        ok, msg = svc.apply_correction(rid)
        assert ok, msg
        assert _dim("DIM-T001")["维度名称"] == "客户维度A@ERP"
        # 待办清零
        assert _dim("DIM-T001")["pending"] is False
        assert svc.todos("DIM-T001")["待办"] == []

    def test_defer_not_in_todo_and_not_signable(self):
        _seed_registration()
        svc = FieldRulingService()
        _, _, created = svc.adjudicate("CC-T001", "DIM-T001", 1, [
            {"裁决字段": "显示名", "基准值": "客户维度A", "对照值": "客户维度A@ERP",
             "裁决结论": "暂缓"},
        ])
        rid = created[0]["id"]
        assert svc.todos("DIM-T001")["待办"] == []
        assert _dim("DIM-T001")["pending"] is False
        ok, msg = svc.sign_ruling(rid)
        assert not ok and "暂缓" in msg

    def test_adjudicate_validation_errors(self):
        _seed_registration()
        svc = FieldRulingService()
        ok, msg, _ = svc.adjudicate("CC-UNKNOWN", "DIM-T001", 1, [_display_name_ruling()])
        assert not ok and "核对编号" in msg
        ok, msg, _ = svc.adjudicate("CC-T001", "DIM-UNKNOWN", 1, [_display_name_ruling()])
        assert not ok and "原登记" in msg
        ok, msg, _ = svc.adjudicate("CC-T001", "DIM-T001", 1, [
            {"裁决字段": "英文名", "基准值": "a", "对照值": "b", "裁决结论": "采用基准值"},
        ])
        assert not ok and "可裁决范围" in msg
        ok, msg, _ = svc.adjudicate("CC-T001", "DIM-T001", 1, [
            {"裁决字段": "显示名", "基准值": "", "对照值": "b", "裁决结论": "采用基准值"},
        ])
        assert not ok and "基准值为空" in msg
        ok, msg, _ = svc.adjudicate("CC-T001", "DIM-T001", 1, [
            {"裁决字段": "显示名", "基准值": "a", "对照值": "b", "裁决结论": "各取一半"},
        ])
        assert not ok and "无效" in msg

    def test_conform_check_entry_point(self):
        _seed_registration()
        cc = ConformCheckService()
        ok, msg, created = cc.submit_field_rulings(
            "CC-T001", "DIM-T001", 1, [_display_name_ruling()],
        )
        assert ok, msg
        assert created[0]["核对编号"] == "CC-T001"
        # 维度建档侧按原登记和核对轮次接收
        todos = DimEntryService().pending_rulings("DIM-T001", 1)
        assert len(todos["待办"]) == 1


class TestFieldIndependenceAndRounds:
    def test_return_customer_no_not_blocking_display_name_sign(self):
        """退回客户号不妨碍签收显示名：同一轮内各字段独立裁决、独立流转。"""
        _seed_registration()
        svc = FieldRulingService()
        ok, _, created = svc.adjudicate("CC-T001", "DIM-T001", 1, [
            _display_name_ruling(),
            {"裁决字段": "客户号", "基准值": "cust_001", "对照值": "cust_erp_001",
             "裁决结论": "退回"},
        ])
        assert ok
        name_ruling, no_ruling = created
        ok, msg = svc.sign_ruling(name_ruling["id"])
        assert ok, msg
        # 客户号仍是待签收，显示名已进入允许改正范围
        todos = svc.todos("DIM-T001", 1)
        assert todos["允许改正字段"] == ["显示名"]
        assert {t["裁决字段"] for t in todos["待办"]} == {"显示名", "客户号"}
        ok, _ = svc.apply_correction(name_ruling["id"])
        assert ok
        assert _dim("DIM-T001")["维度名称"] == "客户维度A@ERP"
        assert _dim("DIM-T001")["业务主键"] == "cust_001"  # 客户号未被波及

    def test_returned_field_requires_corrected_value(self):
        """单独退回客户号：签收后必须提供改正值，落库到业务主键。"""
        _seed_registration()
        svc = FieldRulingService()
        _, _, created = svc.adjudicate("CC-T001", "DIM-T001", 1, [
            {"裁决字段": "客户号", "基准值": "cust_001", "对照值": "cust_erp_001",
             "裁决结论": "退回"},
        ])
        rid = created[0]["id"]
        assert svc.sign_ruling(rid)[0]
        ok, msg = svc.apply_correction(rid)
        assert not ok and "改正值" in msg
        ok, msg = svc.apply_correction(rid, corrected_value="cust_009")
        assert ok, msg
        assert _dim("DIM-T001")["业务主键"] == "cust_009"

    def test_next_round_expires_prior_ruling(self):
        """裁决按登记轮次生效：新一轮下达后旧裁决失效，下一轮编辑不能沿用。"""
        _seed_registration()
        svc = FieldRulingService()
        _, _, created1 = svc.adjudicate("CC-T001", "DIM-T001", 1, [_display_name_ruling()])
        old_id = created1[0]["id"]
        assert svc.sign_ruling(old_id)[0]
        # 第 2 轮重提同一字段：旧裁决失效
        ruling2 = {"裁决字段": "显示名", "基准值": "客户维度A", "对照值": "客户维度A@ERP",
                   "裁决结论": "采用基准值"}
        ok, _, created2 = svc.adjudicate("CC-T001", "DIM-T001", 2, [ruling2])
        assert ok
        old = store.find("field_ruling", old_id)
        assert old["status"] == "已失效"
        # 已失效裁决不能签收、不能落库
        ok, msg = svc.sign_ruling(old_id)
        assert not ok and "已失效" in msg
        ok, msg = svc.apply_correction(old_id)
        assert not ok and "已失效" in msg
        # 新一轮签收后正常落库
        new_id = created2[0]["id"]
        assert svc.sign_ruling(new_id)[0]
        assert svc.apply_correction(new_id)[0]
        assert _dim("DIM-T001")["维度名称"] == "客户维度A"
        # 轮次回退被拒绝
        ok, msg, _ = svc.adjudicate("CC-T001", "DIM-T001", 1, [_display_name_ruling()])
        assert not ok and "轮次" in msg


class TestWithdraw:
    def test_withdraw_before_write(self):
        """建档端已接收改名指令但还未写入时，核对员可撤回；旧指令失去落库资格。"""
        _seed_registration()
        svc = FieldRulingService()
        _, _, created = svc.adjudicate("CC-T001", "DIM-T001", 1, [_display_name_ruling()])
        rid = created[0]["id"]
        assert svc.sign_ruling(rid)[0]
        ok, msg = svc.withdraw_ruling(rid)
        assert ok and "可立即发起下一轮" in msg
        # 旧指令无资格落库
        ok, msg = svc.apply_correction(rid)
        assert not ok and "无资格落库" in msg
        assert _dim("DIM-T001")["维度名称"] == "客户维度A"  # 未改名
        # 核对员可立即发下一轮
        ok, _, created2 = svc.adjudicate("CC-T001", "DIM-T001", 2, [_display_name_ruling()])
        assert ok and created2[0]["status"] == "待签收"

    def test_withdraw_after_write_rejected(self):
        _seed_registration()
        svc = FieldRulingService()
        _, _, created = svc.adjudicate("CC-T001", "DIM-T001", 1, [_display_name_ruling()])
        rid = created[0]["id"]
        svc.sign_ruling(rid)
        assert svc.apply_correction(rid)[0]
        ok, msg = svc.withdraw_ruling(rid)
        assert not ok and "已写入" in msg
        assert _dim("DIM-T001")["维度名称"] == "客户维度A@ERP"


class TestHistory:
    def test_written_names_and_round_opinions_queryable(self):
        """已写入的名字和历轮意见须可按原登记查询。"""
        _seed_registration()
        svc = FieldRulingService()
        # 第 1 轮：显示名采用对照值并落库；客户号退回后撤回
        _, _, created = svc.adjudicate("CC-T001", "DIM-T001", 1, [
            _display_name_ruling(),
            {"裁决字段": "客户号", "基准值": "cust_001", "对照值": "cust_erp_001",
             "裁决结论": "退回"},
        ])
        name_id, no_id = created[0]["id"], created[1]["id"]
        svc.sign_ruling(name_id)
        svc.apply_correction(name_id)
        svc.withdraw_ruling(no_id)
        # 第 2 轮：客户号退回改正落库
        _, _, created2 = svc.adjudicate("CC-T001", "DIM-T001", 2, [
            {"裁决字段": "客户号", "基准值": "cust_001", "对照值": "cust_erp_001",
             "裁决结论": "退回"},
        ])
        svc.sign_ruling(created2[0]["id"])
        svc.apply_correction(created2[0]["id"], corrected_value="cust_009")

        history = svc.history("DIM-T001")
        written = history["已写入"]
        assert {(w["裁决字段"], w["新值"]) for w in written} == {
            ("显示名", "客户维度A@ERP"), ("客户号", "cust_009"),
        }
        assert all(w["旧值"] for w in written)
        rounds = history["历轮意见"]
        assert [r["核对轮次"] for r in rounds] == ["1", "1", "2"]
        by_status = {r["裁决编号"]: r["当前状态"] for r in rounds}
        assert by_status[created[1]["裁决编号"]] == "已撤回"
        # 历轮意见留痕：裁决、签收、落库、撤回都可查
        all_stages = {op["环节"] for r in rounds for op in r["意见记录"]}
        assert {"核对裁决", "建档签收", "改正落库", "核对撤回"} <= all_stages


class TestConcurrency:
    def test_two_windows_apply_vs_withdraw_single_winner(self):
        """验收场景：两个窗口在显示名上重叠触发改正和撤销，只有一笔生效，
        且结论两边都能查到；随后单独退回客户号。"""
        _seed_registration()
        svc = FieldRulingService()
        _, _, created = svc.adjudicate("CC-T001", "DIM-T001", 1, [_display_name_ruling()])
        rid = created[0]["id"]
        # 建档端已接收改名指令（已签收）但还未写入
        assert svc.sign_ruling(rid)[0]

        barrier = threading.Barrier(2)
        results: dict[str, tuple[bool, str]] = {}

        def window_apply() -> None:
            barrier.wait()
            results["apply"] = svc.apply_correction(rid)

        def window_withdraw() -> None:
            barrier.wait()
            results["withdraw"] = svc.withdraw_ruling(rid)

        threads = [threading.Thread(target=window_apply),
                   threading.Thread(target=window_withdraw)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 取消与写入冲突时只有一笔生效
        assert sorted(ok for ok, _ in results.values()) == [False, True]
        row = store.find("field_ruling", rid)
        if results["apply"][0]:
            # 写入抢先生效：撤回不生效，名字已落库
            assert row["status"] == "已写入"
            assert "已写入" in results["withdraw"][1]
            assert _dim("DIM-T001")["维度名称"] == "客户维度A@ERP"
        else:
            # 取消抢先生效：旧指令无资格落库，名字未变
            assert row["status"] == "已撤回"
            assert "无资格落库" in results["apply"][1]
            assert _dim("DIM-T001")["维度名称"] == "客户维度A"
        # 两边都能查到同一个结论
        history = svc.history("DIM-T001")
        final = {r["裁决编号"]: r["当前状态"] for r in history["历轮意见"]}
        assert final[row["裁决编号"]] == row["status"]
        assert svc.todos("DIM-T001")["待办"] == []
        # 旧指令无论输赢都不再有（再次）落库资格
        ok, _ = svc.apply_correction(rid)
        assert not ok
        # 核对员可立即发下一轮
        ok, msg, _ = svc.adjudicate("CC-T001", "DIM-T001", 2, [_display_name_ruling()])
        assert ok, msg

        # 再单独退回客户号：与显示名互不影响
        ok, _, created2 = svc.adjudicate("CC-T001", "DIM-T001", 3, [
            {"裁决字段": "客户号", "基准值": "cust_001", "对照值": "cust_erp_001",
             "裁决结论": "退回"},
        ])
        assert ok
        rid2 = created2[0]["id"]
        assert svc.sign_ruling(rid2)[0]
        assert svc.apply_correction(rid2, corrected_value="cust_009")[0]
        assert _dim("DIM-T001")["业务主键"] == "cust_009"

    def test_rename_withdraw_resubmit_single_effective(self):
        """同一字段的改名、撤回和重提并发时只能有一笔改正生效。"""
        _seed_registration()
        svc = FieldRulingService()
        _, _, created = svc.adjudicate("CC-T001", "DIM-T001", 1, [_display_name_ruling()])
        rid = created[0]["id"]
        assert svc.sign_ruling(rid)[0]

        barrier = threading.Barrier(3)
        results: dict[str, tuple] = {}

        def do_apply() -> None:
            barrier.wait()
            results["apply"] = svc.apply_correction(rid)

        def do_withdraw() -> None:
            barrier.wait()
            results["withdraw"] = svc.withdraw_ruling(rid)

        def do_resubmit() -> None:
            barrier.wait()
            results["resubmit"] = svc.adjudicate(
                "CC-T001", "DIM-T001", 2, [_display_name_ruling()],
            )

        threads = [threading.Thread(target=t)
                   for t in (do_apply, do_withdraw, do_resubmit)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 重提（新一轮）必然受理；旧裁决上的改名与撤回最多一笔生效
        assert results["resubmit"][0]
        assert sum(1 for key in ("apply", "withdraw") if results[key][0]) <= 1
        rows = [r for r in store.rows("field_ruling")
                if r.get("原登记") == "DIM-T001" and r.get("裁决字段") == "显示名"]
        written = [r for r in rows if r["status"] == "已写入"]
        live = [r for r in rows if r["status"] in ("待签收", "已签收")]
        # 只有一笔改正生效，且同一字段最多一条生效中裁决
        assert len(written) <= 1
        assert len(live) == 1
        old = store.find("field_ruling", rid)
        assert old["status"] in ("已写入", "已撤回", "已失效")
        if old["status"] != "已写入":
            # 旧指令未落库则永无落库资格
            assert not svc.apply_correction(rid)[0]
            assert _dim("DIM-T001")["维度名称"] == "客户维度A"
        # 结论两边可查：待办只剩新裁决，历轮意见覆盖新旧两笔裁决
        todos = svc.todos("DIM-T001")
        assert len(todos["待办"]) == 1
        assert todos["待办"][0]["裁决编号"] != old["裁决编号"]
        history = svc.history("DIM-T001")
        assert len(history["历轮意见"]) == 2
        assert {r["当前状态"] for r in history["历轮意见"]} <= {
            "待签收", "已签收", "已写入", "已撤回", "已失效",
        }

    def test_double_write_rejected(self):
        """同一裁决重复写入只有第一笔生效。"""
        _seed_registration()
        svc = FieldRulingService()
        _, _, created = svc.adjudicate("CC-T001", "DIM-T001", 1, [_display_name_ruling()])
        rid = created[0]["id"]
        svc.sign_ruling(rid)

        barrier = threading.Barrier(2)
        results: list[tuple[bool, str]] = []

        def do_apply() -> None:
            barrier.wait()
            results.append(svc.apply_correction(rid))

        threads = [threading.Thread(target=do_apply) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(ok for ok, _ in results) == [False, True]
        assert _dim("DIM-T001")["维度名称"] == "客户维度A@ERP"
