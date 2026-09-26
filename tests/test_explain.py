"""POST /explain 核心解释逻辑单元测试（纯 Python，不依赖 FastAPI）。"""

from __future__ import annotations

import random
import unittest

from app.audit import AuditValidationError, audit
from app.explain import explain


def _s(sid: str, youngest: int, oldest: int) -> dict:
    return {"id": sid, "youngest_ma": youngest, "oldest_ma": oldest}


def _r(older: str, younger: str) -> dict:
    return {"older_id": older, "younger_id": younger}


def _audit_subset(payload: dict, indices: list[int]) -> dict:
    """用 /audit 复核只保留给定序号（1 起）的关系子集时的结论。"""
    return audit(
        {
            "strata": payload["strata"],
            "relations": [payload["relations"][i - 1] for i in indices],
        }
    )


def _check_minimal_infeasible_group(
    case: unittest.TestCase, payload: dict, result: dict
) -> None:
    """解释结果必须是不可行且极小的关系组：移去组内任一条后即可行。"""
    case.assertEqual(result["status"], "infeasible")
    indices = result["relation_indices"]
    case.assertTrue(indices, "不可行时解释组不能为空")
    # 序号从 1 开始、升序、不重复、不越界。
    case.assertEqual(indices, sorted(indices))
    case.assertEqual(len(indices), len(set(indices)))
    case.assertGreaterEqual(indices[0], 1)
    case.assertLessEqual(indices[-1], len(payload["relations"]))

    # 组自身保持不可行，且类型与 /audit 对该组的判定一致。
    group = _audit_subset(payload, indices)
    case.assertIn(group["status"], ("cycle", "conflict"))
    case.assertEqual(result["type"], group["status"])

    # 极小性：移去组内任一条关系后可行。
    for drop in indices:
        rest = [i for i in indices if i != drop]
        outcome = _audit_subset(payload, rest)
        case.assertEqual(
            outcome["status"],
            "feasible",
            f"移除第 {drop} 条关系后应当可行，实际为 {outcome}",
        )


class FeasibleTests(unittest.TestCase):
    def test_feasible_result_matches_audit_exactly(self):
        payload = {
            "strata": [_s(s, 100, 110) for s in ("a", "b", "c")],
            "relations": [_r("a", "b"), _r("b", "c")],
        }
        self.assertEqual(explain(payload), audit(payload))
        self.assertEqual(explain(payload)["status"], "feasible")

    def test_no_relations_is_feasible(self):
        result = explain({"strata": [_s("a", 0, 10)], "relations": []})
        self.assertEqual(result["status"], "feasible")
        self.assertEqual(result["oldest_to_youngest"], ["a"])


class CycleGroupTests(unittest.TestCase):
    def test_simple_cycle_group(self):
        payload = {
            "strata": [_s(s, 0, 100) for s in ("a", "b", "c")],
            "relations": [_r("a", "b"), _r("b", "c"), _r("c", "a")],
        }
        result = explain(payload)
        self.assertEqual(result["type"], "cycle")
        self.assertEqual(result["relation_indices"], [1, 2, 3])
        _check_minimal_infeasible_group(self, payload, result)

    def test_unrelated_relation_is_excluded(self):
        # 第 1 条与环无关，不应出现在解释组中。
        payload = {
            "strata": [_s(s, 0, 100) for s in ("a", "b", "z")],
            "relations": [_r("z", "a"), _r("a", "b"), _r("b", "a")],
        }
        result = explain(payload)
        self.assertEqual(result["type"], "cycle")
        self.assertEqual(result["relation_indices"], [2, 3])
        _check_minimal_infeasible_group(self, payload, result)

    def test_duplicate_cycle_relations_numbered_by_position(self):
        # 同一对关系各出现两次：最小组取位置靠后的一对（升序扫描的
        # 确定结果），序号仍按输入位置给出。
        payload = {
            "strata": [_s("a", 0, 100), _s("b", 0, 100)],
            "relations": [_r("a", "b"), _r("b", "a"), _r("a", "b"), _r("b", "a")],
        }
        result = explain(payload)
        self.assertEqual(result["type"], "cycle")
        self.assertEqual(result["relation_indices"], [3, 4])
        _check_minimal_infeasible_group(self, payload, result)


class ConflictGroupTests(unittest.TestCase):
    def test_single_relation_conflict(self):
        # 两层都钉在 5，a 比 b 古老至少需要相差 1。
        payload = {
            "strata": [_s("a", 5, 5), _s("b", 5, 5)],
            "relations": [_r("a", "b")],
        }
        result = explain(payload)
        self.assertEqual(result["type"], "conflict")
        self.assertEqual(result["relation_indices"], [1])
        _check_minimal_infeasible_group(self, payload, result)

    def test_two_relation_squeeze(self):
        # a 钉在 5 迫使 b <= 4，c 钉在 5 迫使 b >= 6：两条缺一不可。
        payload = {
            "strata": [_s("a", 5, 5), _s("b", 0, 100), _s("c", 5, 5)],
            "relations": [_r("a", "b"), _r("b", "c")],
        }
        result = explain(payload)
        self.assertEqual(result["type"], "conflict")
        self.assertEqual(result["relation_indices"], [1, 2])
        _check_minimal_infeasible_group(self, payload, result)

    def test_duplicate_conflict_relation_collapses_to_one(self):
        # 重复关系各自独立编号；一条已足够造成冲突，最小组只留一条。
        payload = {
            "strata": [_s("a", 5, 5), _s("b", 5, 5)],
            "relations": [_r("a", "b"), _r("a", "b")],
        }
        result = explain(payload)
        self.assertEqual(result["type"], "conflict")
        self.assertEqual(result["relation_indices"], [2])
        _check_minimal_infeasible_group(self, payload, result)

    def test_chain_conflict_excludes_unrelated_tail(self):
        # 前三条构成 a->b->c 的压空冲突；第 4 条与冲突无关。
        payload = {
            "strata": [
                _s("a", 50, 50),
                _s("b", 0, 100),
                _s("c", 50, 50),
                _s("d", 0, 100),
            ],
            "relations": [_r("a", "b"), _r("b", "c"), _r("b", "d")],
        }
        result = explain(payload)
        self.assertEqual(result["type"], "conflict")
        self.assertEqual(result["relation_indices"], [1, 2])
        _check_minimal_infeasible_group(self, payload, result)


class MixedTests(unittest.TestCase):
    def test_cycle_and_conflict_yields_single_minimal_group(self):
        # 第 1、2 条成环，第 3 条独立造成区间压空；升序扫描下环的两条
        # 先后被移除，最终留下极小的冲突组 [3]。
        payload = {
            "strata": [
                _s("a", 0, 100),
                _s("b", 0, 100),
                _s("c", 5, 5),
                _s("d", 5, 5),
            ],
            "relations": [_r("a", "b"), _r("b", "a"), _r("c", "d")],
        }
        result = explain(payload)
        self.assertEqual(result["type"], "conflict")
        self.assertEqual(result["relation_indices"], [3])
        _check_minimal_infeasible_group(self, payload, result)


class ValidationTests(unittest.TestCase):
    def test_basic_validation_is_reused(self):
        with self.assertRaises(AuditValidationError):
            explain(
                {
                    "strata": [_s("a", 0, 10)],
                    "relations": [_r("a", "a")],
                }
            )
        with self.assertRaises(AuditValidationError):
            explain(
                {
                    "strata": [_s("a", 0, 10)],
                    "relations": [_r("a", "ghost")],
                }
            )


class RandomizedCrossCheckTests(unittest.TestCase):
    def test_random_cases_against_audit(self):
        rng = random.Random(20260926)
        for _ in range(300):
            n = rng.randint(1, 6)
            ids = [f"s{i}" for i in range(n)]
            strata = []
            for sid in ids:
                lo = rng.randint(0, 6)
                strata.append(_s(sid, lo, rng.randint(lo, 8)))
            # 允许重复关系；自环属 422 基本校验，不在解释范围内。
            relations = [
                _r(rng.choice(ids), rng.choice(ids))
                for _ in range(rng.randint(0, 8))
            ]
            relations = [
                r for r in relations if r["older_id"] != r["younger_id"]
            ]
            payload = {"strata": strata, "relations": relations}

            result = explain(payload)
            reference = audit(payload)
            if reference["status"] == "feasible":
                self.assertEqual(result, reference)
            else:
                _check_minimal_infeasible_group(self, payload, result)


if __name__ == "__main__":
    unittest.main()
