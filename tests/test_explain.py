"""POST /explain 最小不可行关系定位的单元测试（纯 Python，不依赖 FastAPI）。"""

from __future__ import annotations

import itertools
import random
import unittest

from app.audit import AuditValidationError, find_cycle
from app.explain import explain


def _s(sid: str, youngest: int, oldest: int) -> dict:
    return {"id": sid, "youngest_ma": youngest, "oldest_ma": oldest}


def _r(older: str, younger: str) -> dict:
    return {"older_id": older, "younger_id": younger}


def _brute_feasible(payload: dict, positions) -> bool:
    """在极小整数年代域上暴力判定给定位置子集的关系是否可行。"""
    strata = {item["id"]: item for item in payload["strata"]}
    ids = sorted(strata)
    domains = [
        range(strata[sid]["youngest_ma"], strata[sid]["oldest_ma"] + 1)
        for sid in ids
    ]
    relations = [payload["relations"][i] for i in positions]
    for combo in itertools.product(*domains):
        age = dict(zip(ids, combo))
        if all(
            age[rel["older_id"]] >= age[rel["younger_id"]] + 1
            for rel in relations
        ):
            return True
    return False


def _has_cycle(ids, relations) -> bool:
    adjacency: dict[str, set[str]] = {sid: set() for sid in ids}
    for rel in relations:
        adjacency[rel["older_id"]].add(rel["younger_id"])
    return find_cycle(ids, adjacency) is not None


class FeasibleTests(unittest.TestCase):
    def test_no_relations_is_feasible(self):
        result = explain(
            {"strata": [_s("a", 0, 10), _s("b", 0, 10)], "relations": []}
        )
        self.assertEqual(result, {"status": "feasible"})

    def test_satisfiable_chain_is_feasible(self):
        result = explain(
            {
                "strata": [_s(s, 0, 100) for s in ("a", "b", "c")],
                "relations": [_r("a", "b"), _r("b", "c")],
            }
        )
        self.assertEqual(result, {"status": "feasible"})


class CycleTests(unittest.TestCase):
    def test_simple_three_cycle(self):
        result = explain(
            {
                "strata": [_s(s, 0, 100) for s in ("a", "b", "c")],
                "relations": [_r("a", "b"), _r("b", "c"), _r("c", "a")],
            }
        )
        self.assertEqual(result["status"], "cycle")
        self.assertEqual(result["relation_indices"], [1, 2, 3])

    def test_cycle_with_redundant_relations_keeps_only_cycle(self):
        # 关系 1..3 构成 a->b->c->a；关系 4、5 是与不可行性无关的多余边，
        # 最小不可行组应当只保留环上三条。
        result = explain(
            {
                "strata": [_s(s, 0, 100) for s in ("a", "b", "c", "z", "d")],
                "relations": [
                    _r("a", "b"),
                    _r("b", "c"),
                    _r("c", "a"),
                    _r("z", "a"),
                    _r("a", "d"),
                ],
            }
        )
        self.assertEqual(result["status"], "cycle")
        self.assertEqual(result["relation_indices"], [1, 2, 3])

    def test_cycle_edges_at_interleaved_positions(self):
        # 成环关系在位置 2、4、5，其余位置为多余关系；序号必须按原输入位置。
        result = explain(
            {
                "strata": [_s(s, 0, 100) for s in ("a", "b", "c", "x", "y", "z")],
                "relations": [
                    _r("x", "y"),
                    _r("a", "b"),
                    _r("z", "x"),
                    _r("b", "c"),
                    _r("c", "a"),
                ],
            }
        )
        self.assertEqual(result["status"], "cycle")
        self.assertEqual(result["relation_indices"], [2, 4, 5])

    def test_self_loop_is_validation_error_not_explanation(self):
        with self.assertRaises(AuditValidationError):
            explain(
                {
                    "strata": [_s("a", 0, 10)],
                    "relations": [_r("a", "a")],
                }
            )


class ConflictTests(unittest.TestCase):
    def test_single_relation_conflicts_on_point_intervals(self):
        # a、b 均固定为 5，a >= b + 1 不可能。
        result = explain(
            {
                "strata": [_s("a", 5, 5), _s("b", 5, 5)],
                "relations": [_r("a", "b")],
            }
        )
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["relation_indices"], [1])

    def test_chain_too_long_for_narrow_band(self):
        # 四层只能容纳三层的跨度，三条关系缺一即可行。
        result = explain(
            {
                "strata": [_s(s, 10, 12) for s in ("a", "b", "c", "d")],
                "relations": [_r("a", "b"), _r("b", "c"), _r("c", "d")],
            }
        )
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["relation_indices"], [1, 2, 3])

    def test_middle_layer_squeeze_needs_both_relations(self):
        # a、c 固定 50，b 夹在中间：a->b 与 b->c 缺一即可行。
        result = explain(
            {
                "strata": [
                    _s("a", 50, 50),
                    _s("b", 0, 100),
                    _s("c", 50, 50),
                ],
                "relations": [_r("a", "b"), _r("b", "c")],
            }
        )
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["relation_indices"], [1, 2])

    def test_redundant_conflict_edges_reduced_to_singleton(self):
        # 每层都固定为 5 时，任意一条 a->x 关系本身就冲突；
        # 删除法最终只保留最早一条不可或缺的关系。
        result = explain(
            {
                "strata": [_s(s, 5, 5) for s in ("a", "b", "c")],
                "relations": [_r("a", "b"), _r("b", "c"), _r("a", "c")],
            }
        )
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["relation_indices"], [1])

    def test_duplicate_relations_numbered_by_position_and_earliest_kept(self):
        # 同一条关系出现两次（位置 1、2），重复关系仍各自编号；
        # 从大到小试探使首次出现的位置 1 被保留。
        result = explain(
            {
                "strata": [_s("a", 5, 5), _s("b", 5, 5)],
                "relations": [_r("a", "b"), _r("a", "b")],
            }
        )
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["relation_indices"], [1])

    def test_independent_cycle_and_conflict_break_deterministically(self):
        # 位置 1、2 是宽区间上的环 c->d->c；位置 3 本身就是点区间冲突 a->b。
        # 两个不可行来源互相独立：自高位删除时冲突边先被移除（环仍在），
        # 最终保留环。结果确定即可，这里记录删除顺序决定的 tie-break 行为。
        result = explain(
            {
                "strata": [
                    _s("a", 5, 5),
                    _s("b", 5, 5),
                    _s("c", 0, 100),
                    _s("d", 0, 100),
                ],
                "relations": [_r("c", "d"), _r("d", "c"), _r("a", "b")],
            }
        )
        self.assertEqual(result["status"], "cycle")
        self.assertEqual(result["relation_indices"], [1, 2])

    def test_conflict_first_then_cycle_keeps_conflict(self):
        # 与上例相反的位置顺序：点冲突在前、环在后；自高位删除时先拆掉环
        # （冲突仍在），最终保留冲突关系。
        result = explain(
            {
                "strata": [
                    _s("a", 5, 5),
                    _s("b", 5, 5),
                    _s("c", 0, 100),
                    _s("d", 0, 100),
                ],
                "relations": [_r("a", "b"), _r("c", "d"), _r("d", "c")],
            }
        )
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["relation_indices"], [1])


class MinimalityBruteForceTests(unittest.TestCase):
    """随机小例对照暴力枚举：返回的关系组必须保持不可行且逐条最小。"""

    def test_returned_sets_are_minimal_unsatisfiable_subsets(self):
        rng = random.Random(20260926)
        for _ in range(150):
            n = rng.randint(1, 4)
            ids = [f"s{i}" for i in range(n)]
            strata = []
            for sid in ids:
                lo = rng.randint(-2, 2)
                hi = lo + rng.randint(0, 3)
                strata.append(_s(sid, lo, hi))
            relations = []
            pairs = [(i, j) for i in ids for j in ids if i != j]
            for _ in range(rng.randint(0, min(6, len(pairs)))):
                older, younger = rng.choice(pairs)
                relations.append(_r(older, younger))  # 允许重复与成环
            payload = {"strata": strata, "relations": relations}

            all_positions = list(range(len(relations)))
            result = explain(payload)
            if _brute_feasible(payload, all_positions):
                self.assertEqual(result["status"], "feasible", payload)
                continue

            self.assertIn(result["status"], ("cycle", "conflict"), payload)
            indices = result["relation_indices"]
            # 序号从 1 开始、严格升序、且均为合法位置。
            self.assertEqual(indices, sorted(set(indices)), payload)
            self.assertTrue(all(1 <= k <= len(relations) for k in indices), payload)
            positions = [k - 1 for k in indices]

            # 该组本身必须不可行。
            self.assertFalse(_brute_feasible(payload, positions), payload)
            # 移去其中任一条后必须可行（最小不可行）。
            for pos in positions:
                rest = [p for p in positions if p != pos]
                self.assertTrue(_brute_feasible(payload, rest), (payload, pos))

            # 类型与子集关系图是否含环一致（独立于 explain 模块复核）。
            self.assertEqual(
                result["status"] == "cycle",
                _has_cycle(ids, [relations[p] for p in positions]),
                payload,
            )

    def test_result_is_deterministic(self):
        payload = {
            "strata": [_s(s, 5, 5) for s in ("a", "b", "c")],
            "relations": [
                _r("a", "b"),
                _r("b", "c"),
                _r("a", "c"),
                _r("b", "a"),
            ],
        }
        self.assertEqual(explain(payload), explain(payload))


class MaxScaleTests(unittest.TestCase):
    def test_max_limits_accepted(self):
        # 200 层、1000 条关系的稠密 DAG：整体可行，应直接返回 feasible。
        n = 200
        ids = [f"s{i:03d}" for i in range(n)]
        relations = []
        for i in range(n):
            for j in range(i + 1, n):
                relations.append(_r(ids[i], ids[j]))
                if len(relations) == 1000:
                    break
            if len(relations) == 1000:
                break
        self.assertEqual(len(relations), 1000)
        result = explain(
            {
                "strata": [_s(sid, 0, 10**6) for sid in ids],
                "relations": relations,
            }
        )
        self.assertEqual(result, {"status": "feasible"})

    def test_max_scale_infeasible_returns_minimal_set(self):
        # 全部固定为同一值，200 个节点上 200 条边闭环（s000->...->s199->s000）：
        # 既是环又处处区间冲突；删除法拆掉环后冲突迅速消解，最小组为单条。
        n = 200
        ids = [f"s{i:03d}" for i in range(n)]
        relations = [_r(ids[i], ids[(i + 1) % n]) for i in range(n)]
        result = explain(
            {
                "strata": [_s(sid, 5, 5) for sid in ids],
                "relations": relations,
            }
        )
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["relation_indices"], [1])


class ValidationTests(unittest.TestCase):
    def _errors(self, data: dict) -> list[str]:
        try:
            explain(data)
        except AuditValidationError as exc:
            return exc.errors
        self.fail("应当抛出 AuditValidationError")

    def test_unknown_reference_is_rejected(self):
        errors = self._errors(
            {
                "strata": [_s("a", 0, 10)],
                "relations": [_r("a", "x")],
            }
        )
        self.assertTrue(any("未提交" in e for e in errors))

    def test_bad_interval_is_rejected(self):
        errors = self._errors(
            {"strata": [_s("a", 10, 5)], "relations": []}
        )
        self.assertTrue(any("非法" in e for e in errors))

    def test_duplicate_stratum_ids_rejected(self):
        errors = self._errors(
            {
                "strata": [_s("a", 0, 10), _s("a", 0, 10)],
                "relations": [],
            }
        )
        self.assertTrue(any("重复" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
