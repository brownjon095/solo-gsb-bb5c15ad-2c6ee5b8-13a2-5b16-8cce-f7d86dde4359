"""不可行约束的最小解释：定位一组“缺一不可”的观测关系。

与 /audit 共用同一套约束（整数年代区间 + ``age(older) >= age(younger) + 1``）
与基本校验。全量约束可行时返回与 /audit 相同的结果；不可行时在**关系**
层面给出一个最小不可行组：

* 该组关系（连同全部地层区间）**保持不可行**；
* **移去组内任一条关系后即可行**（极小性，缺一不可）；
* 组内关系按原请求序号（从 1 开始）升序返回，重复关系按输入位置
  独立编号；
* 组的不可行类型为 ``cycle``（关系成环）或 ``conflict``（区间压空）。

算法（删除式极小化）
------------------
基本校验保证每层区间各自合法（``youngest_ma <= oldest_ma``），单看区间
必可行，故不可行一定由关系引起。对关系序号做一次升序扫描：若移除第 i
条后系统仍不可行，则真正移除之。扫描结束后，对留在组内的任一序号 i，
它被测试时的当前集合是最终集合的超集，而当时“移除 i 即可行”；由可行
性的单调性（可行系统的任意子集仍可行），最终集合移除 i 后同样可行——
极小性成立。组本身在扫描全程保持不可行。单次判定复用
:func:`app.audit.find_cycle` 与 :func:`app.audit.tighten_bounds`，
整体复杂度 O(关系数 × (层数 + 关系数))，1000 条关系 / 200 层约百万次
基本操作。

组的不可行类型
--------------
最小不可行组若含环，则必恰为一个简单环（环外任一条被移除后环仍在，与
极小性矛盾），类型为 ``cycle``；否则为 DAG 上区间被压空，类型为
``conflict``。判定顺序与 /audit 相同：先查环，再传播查压空。
"""

from __future__ import annotations

from typing import Any, Iterable

from .audit import (
    find_cycle,
    lexicographic_topo,
    tighten_bounds,
    validate_and_build,
)


def explain(data: dict[str, Any]) -> dict[str, Any]:
    """对一次提交给出可行性结论或最小不可行关系组。

    可行时返回与 /audit 相同的 ``feasible`` 结果（收紧区间 + 字典序最小
    合法顺序）；不可行时返回::

        {"status": "infeasible",
         "type": "cycle" | "conflict",
         "relation_indices": [...]}   # 原请求序号，从 1 开始、升序
    """
    raw_strata: list[dict[str, Any]] = list(data.get("strata") or [])
    raw_relations: list[dict[str, Any]] = list(data.get("relations") or [])

    # ---- 1. 基本校验（与 /audit 完全一致的约束语义） --------------------
    ids, bounds, _ = validate_and_build(raw_strata, raw_relations)
    # 关系按输入位置（0 起）保留，不去重：重复关系按位置独立编号。
    edges = [(rel["older_id"], rel["younger_id"]) for rel in raw_relations]

    # ---- 2. 全量关系可行则直接返回（结果形态与 /audit 相同） ------------
    status, topo, lower, upper = _classify(ids, bounds, edges, range(len(edges)))
    if status == "feasible":
        assert topo is not None and lower is not None and upper is not None
        return {
            "status": "feasible",
            "tight_intervals": {
                sid: {"youngest_ma": lower[sid], "oldest_ma": upper[sid]}
                for sid in ids
            },
            "oldest_to_youngest": topo,
        }

    # ---- 3. 删除式极小化：升序扫描，移除后仍不可行则真正移除 ------------
    kept = list(range(len(edges)))
    for index in range(len(edges)):
        if index not in kept:
            continue  # 已在更早的迭代中被移除
        trial = [j for j in kept if j != index]
        trial_status, _, _, _ = _classify(ids, bounds, edges, trial)
        if trial_status != "feasible":
            kept = trial

    # ---- 4. 最小不可行组的类型（含环为 cycle，否则为 conflict） ---------
    group_status, _, _, _ = _classify(ids, bounds, edges, kept)
    assert group_status in ("cycle", "conflict")  # 极小化全程保持不可行
    return {
        "status": "infeasible",
        "type": group_status,
        "relation_indices": [index + 1 for index in kept],
    }


def _classify(
    ids: list[str],
    bounds: dict[str, tuple[int, int]],
    edges: list[tuple[str, str]],
    keep: Iterable[int],
) -> tuple[
    str,
    list[str] | None,
    dict[str, int] | None,
    dict[str, int] | None,
]:
    """判定只保留 ``keep`` 指定的关系（0 起序号）时的可行性。

    返回 ``(status, topo, lower, upper)``；``status`` 为 ``"feasible"``
    时后三项有效（与 /audit 的收紧区间、字典序最小拓扑序一致），为
    ``"cycle"`` / ``"conflict"`` 时后三项为 None。判定顺序与 /audit
    相同：先查环，再在 DAG 上双向传播查区间压空。
    """
    adjacency: dict[str, set[str]] = {sid: set() for sid in ids}
    for index in keep:
        older, younger = edges[index]
        adjacency[older].add(younger)

    if find_cycle(ids, adjacency) is not None:
        return "cycle", None, None, None

    topo = lexicographic_topo(ids, adjacency)
    lower = {sid: bounds[sid][0] for sid in ids}
    upper = {sid: bounds[sid][1] for sid in ids}
    tighten_bounds(topo, adjacency, lower, upper)

    for sid in ids:
        if lower[sid] > upper[sid]:
            return "conflict", None, None, None
    return "feasible", topo, lower, upper
