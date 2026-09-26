"""POST /gap 核心查询逻辑单元测试（纯 Python，不依赖 FastAPI）。"""

from __future__ import annotations

import itertools
import random
import unittest

from app.audit import AuditValidationError
from app.gap import gap


def _s(sid: str, youngest: int, oldest: int) -> dict:
    return {"id": sid, "youngest_ma": youngest, "oldest_ma": oldest}


def _r(older: str, younger: str) -> dict:
    return {"older_id": older, "younger_id": younger}


def _check_witness(
    case: unittest.TestCase,
    payload: dict,
    ages: dict,
    expected_gap: int,
    a_id: str,
    b_id: str,
) -> None:
    """见证必须是满足全部区间与关系约束的整数赋值，并达到声称的差值。"""
    strata = {item["id"]: item for item in payload["strata"]}
    case.assertEqual(set(ages), set(strata))
    for sid, age in ages.items():
        case.assertIsInstance(age, int)
        case.assertGreaterEqual(age, strata[sid]["youngest_ma"])
        case.assertLessEqual(age, strata[sid]["oldest_ma"])
    for rel in payload["relations"]:
        case.assertGreaterEqual(
            ages[rel["older_id"]], ages[rel["younger_id"]] + 1
        )
    case.assertEqual(ages[a_id] - ages[b_id], expected_gap)


class GapValueTests(unittest.TestCase):
    def test_relation_forces_positive_minimum(self):
        # a 比 b 古老：a >= b+1。独立区间端点相减会误得 min = 0-10 = -10，
        # 但关系耦合使真实最小差为 1；最大差 10（a=10, b=0）不受影响。
        payload = {
            "strata": [_s("a", 0, 10), _s("b", 0, 10)],
            "relations": [_r("a", "b")],
            "a_id": "a",
            "b_id": "b",
        }
        result = gap(payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["min_gap"], 1)
        self.assertEqual(result["max_gap"], 10)
        _check_witness(self, payload, result["min_ages"], 1, "a", "b")
        _check_witness(self, payload, result["max_ages"], 10, "a", "b")

    def test_no_relations_matches_endpoint_spread(self):
        # 无关系时最值即区间端点的交叉差：max = U_a - L_b，min = L_a - U_b。
        payload = {
            "strata": [_s("a", 2, 8), _s("b", 3, 9)],
            "relations": [],
            "a_id": "a",
            "b_id": "b",
        }
        result = gap(payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["max_gap"], 5)
        self.assertEqual(result["min_gap"], -7)
        _check_witness(self, payload, result["min_ages"], -7, "a", "b")
        _check_witness(self, payload, result["max_ages"], 5, "a", "b")

    def test_upstream_stratum_caps_maximum(self):
        # c(0..3) 比 a 古老、a 比 b 古老：a <= c-1 <= 2，
        # max(a-b) = 2（不能直取 a 的上界 10），min(a-b) = 1。
        payload = {
            "strata": [_s("c", 0, 3), _s("a", 0, 10), _s("b", 0, 10)],
            "relations": [_r("c", "a"), _r("a", "b")],
            "a_id": "a",
            "b_id": "b",
        }
        result = gap(payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["max_gap"], 2)
        self.assertEqual(result["min_gap"], 1)
        _check_witness(self, payload, result["min_ages"], 1, "a", "b")
        _check_witness(self, payload, result["max_ages"], 2, "a", "b")

    def test_same_layer_returns_zero(self):
        payload = {
            "strata": [_s("a", 0, 10), _s("b", 0, 10)],
            "relations": [_r("a", "b")],
            "a_id": "a",
            "b_id": "a",
        }
        result = gap(payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["min_gap"], 0)
        self.assertEqual(result["max_gap"], 0)
        _check_witness(self, payload, result["min_ages"], 0, "a", "a")
        _check_witness(self, payload, result["max_ages"], 0, "a", "a")

    def test_disconnected_components_are_supported(self):
        # 两条互不连通的链：a->b 与 c->d；跨分量查询 c - a。
        # 注意分量内部的关系会收紧端点：L(a) 被 b 顶到 1、L(c) 被 d 顶到 1。
        payload = {
            "strata": [_s(s, 0, 100) for s in ("a", "b", "c", "d")],
            "relations": [_r("a", "b"), _r("c", "d")],
            "a_id": "c",
            "b_id": "a",
        }
        result = gap(payload)
        self.assertEqual(result["status"], "ok")
        # 无跨分量约束：max = U_c - L_a = 99，min = L_c - U_a = -99。
        self.assertEqual(result["max_gap"], 99)
        self.assertEqual(result["min_gap"], -99)
        _check_witness(self, payload, result["min_ages"], -99, "c", "a")
        _check_witness(self, payload, result["max_ages"], 99, "c", "a")

    def test_negative_ages(self):
        payload = {
            "strata": [_s("a", -10, -5), _s("b", -3, 0)],
            "relations": [],
            "a_id": "a",
            "b_id": "b",
        }
        result = gap(payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["max_gap"], -5 - (-3))
        self.assertEqual(result["min_gap"], -10 - 0)
        _check_witness(self, payload, result["min_ages"], -10, "a", "b")
        _check_witness(self, payload, result["max_ages"], -2, "a", "b")

    def test_large_magnitudes_without_enumeration(self):
        # 10^12 量级值域：链式约束使差值被钉死，求解不得逐年代枚举。
        big = 10**12
        payload = {
            "strata": [_s("a", -big, big), _s("b", -big, big)],
            "relations": [_r("a", "b")],
            "a_id": "a",
            "b_id": "b",
        }
        result = gap(payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["min_gap"], 1)
        self.assertEqual(result["max_gap"], 2 * big)
        _check_witness(self, payload, result["min_ages"], 1, "a", "b")
        _check_witness(self, payload, result["max_ages"], 2 * big, "a", "b")

    def test_chain_of_two_hundred_strata(self):
        # 200 层长链 s000 最古老：min = 199（逐层恰好相差 1），
        # max = 10^6（s000 取上界、s199 取下界）。
        n = 200
        ids = [f"s{i:03d}" for i in range(n)]
        payload = {
            "strata": [_s(sid, 0, 10**6) for sid in ids],
            "relations": [_r(ids[i], ids[i + 1]) for i in range(n - 1)],
            "a_id": ids[0],
            "b_id": ids[-1],
        }
        result = gap(payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["min_gap"], n - 1)
        self.assertEqual(result["max_gap"], 10**6)
        _check_witness(self, payload, result["min_ages"], n - 1, ids[0], ids[-1])
        _check_witness(self, payload, result["max_ages"], 10**6, ids[0], ids[-1])

    def test_dense_dag_with_thousand_relations(self):
        # 200 层、1000 条关系的稠密 DAG（边均指向更小编号，保证无环）。
        # 关系仅覆盖 s000..s045：s000 经 s044->s045 的全序链被压到 >= 45。
        n = 200
        ids = [f"s{i:03d}" for i in range(n)]
        relations = []
        for i in range(n):
            for j in range(i - 1, -1, -1):
                if len(relations) >= 1000:
                    break
                relations.append(_r(ids[j], ids[i]))
            if len(relations) >= 1000:
                break
        self.assertEqual(len(relations), 1000)
        payload = {
            "strata": [_s(sid, 0, 10**6) for sid in ids],
            "relations": relations,
            "a_id": ids[0],
            "b_id": ids[45],
        }
        result = gap(payload)
        self.assertEqual(result["status"], "ok")
        # 链 s000->...->s044->s045 共 45 步：min = 45；
        # max = U(s000) - L(s045) = 10^6。
        self.assertEqual(result["min_gap"], 45)
        self.assertEqual(result["max_gap"], 10**6)
        _check_witness(self, payload, result["min_ages"], 45, ids[0], ids[45])
        _check_witness(
            self, payload, result["max_ages"], 10**6, ids[0], ids[45]
        )


class PassthroughTests(unittest.TestCase):
    def test_cycle_result_matches_audit_shape(self):
        result = gap(
            {
                "strata": [_s(s, 0, 100) for s in ("a", "b", "c")],
                "relations": [_r("a", "b"), _r("b", "c"), _r("c", "a")],
                "a_id": "a",
                "b_id": "b",
            }
        )
        self.assertEqual(result["status"], "cycle")
        path = result["cycle_path"]
        self.assertEqual(path[0], path[-1])
        self.assertEqual(set(result.keys()), {"status", "cycle_path"})

    def test_conflict_result_matches_audit_shape(self):
        result = gap(
            {
                "strata": [
                    _s("a", 50, 50),
                    _s("b", 0, 100),
                    _s("c", 50, 50),
                ],
                "relations": [_r("a", "b"), _r("b", "c")],
                "a_id": "a",
                "b_id": "c",
            }
        )
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["conflicting_strata"], ["a", "b", "c"])
        self.assertEqual(
            result["tight_intervals"]["b"],
            {"youngest_ma": 51, "oldest_ma": 49},
        )


class QueryValidationTests(unittest.TestCase):
    def _errors(self, data: dict) -> list[str]:
        try:
            gap(data)
        except AuditValidationError as exc:
            return exc.errors
        self.fail("应当抛出 AuditValidationError")

    def test_unknown_a_id_is_rejected(self):
        errors = self._errors(
            {
                "strata": [_s("a", 0, 10)],
                "relations": [],
                "a_id": "ghost",
                "b_id": "a",
            }
        )
        self.assertTrue(any("未提交" in e and "a_id" in e for e in errors))

    def test_unknown_b_id_is_rejected(self):
        errors = self._errors(
            {
                "strata": [_s("a", 0, 10)],
                "relations": [],
                "a_id": "a",
                "b_id": "ghost",
            }
        )
        self.assertTrue(any("未提交" in e and "b_id" in e for e in errors))

    def test_both_unknown_collected_together(self):
        errors = self._errors(
            {
                "strata": [_s("a", 0, 10)],
                "relations": [],
                "a_id": "x",
                "b_id": "y",
            }
        )
        self.assertEqual(len(errors), 2)

    def test_strata_validation_still_applies(self):
        errors = self._errors(
            {
                "strata": [_s("a", 10, 5)],
                "relations": [],
                "a_id": "a",
                "b_id": "a",
            }
        )
        self.assertTrue(any("非法" in e for e in errors))


class BruteForceCrossCheckTests(unittest.TestCase):
    """小规模随机用例与暴力枚举对照（最小/最大差值 + 见证合法性）。"""

    def test_against_brute_force(self):
        rng = random.Random(20260926)
        for _ in range(120):
            n = rng.randint(1, 4)
            ids = [f"s{i}" for i in range(n)]
            strata = []
            for sid in ids:
                lo = rng.randint(-4, 4)
                hi = lo + rng.randint(0, 4)
                strata.append(_s(sid, lo, hi))
            # 仅沿随机排列的先后连边，保证无环。
            order = ids[:]
            rng.shuffle(order)
            relations = []
            for i in range(n):
                for j in range(i + 1, n):
                    if rng.random() < 0.4:
                        relations.append(_r(order[i], order[j]))
            a_id = rng.choice(ids)
            b_id = rng.choice(ids)
            payload = {
                "strata": strata,
                "relations": relations,
                "a_id": a_id,
                "b_id": b_id,
            }
            expected = _brute_force(payload, a_id, b_id)
            result = gap(payload)
            if expected is None:
                self.assertEqual(result["status"], "conflict", payload)
                continue
            exp_min, exp_max = expected
            self.assertEqual(result["status"], "ok", payload)
            self.assertEqual(result["min_gap"], exp_min, payload)
            self.assertEqual(result["max_gap"], exp_max, payload)
            _check_witness(
                self, payload, result["min_ages"], exp_min, a_id, b_id
            )
            _check_witness(
                self, payload, result["max_ages"], exp_max, a_id, b_id
            )


def _brute_force(
    payload: dict, a_id: str, b_id: str
) -> tuple[int, int] | None:
    """暴力枚举全部整数年代，返回 (最小差, 最大差)；无可行赋值返回 None。"""
    strata = {item["id"]: item for item in payload["strata"]}
    ids = sorted(strata)
    domains = [
        range(strata[sid]["youngest_ma"], strata[sid]["oldest_ma"] + 1)
        for sid in ids
    ]
    best_min: int | None = None
    best_max: int | None = None
    for combo in itertools.product(*domains):
        age = dict(zip(ids, combo))
        if any(
            age[rel["older_id"]] < age[rel["younger_id"]] + 1
            for rel in payload["relations"]
        ):
            continue
        diff = age[a_id] - age[b_id]
        best_min = diff if best_min is None else min(best_min, diff)
        best_max = diff if best_max is None else max(best_max, diff)
    if best_min is None:
        return None
    return best_min, best_max


if __name__ == "__main__":
    unittest.main()
