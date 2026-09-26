"""年代差极值查询：在满足审计约束的全部赋值中，求 age(a) − age(b) 的最值。

与 /audit 共用同一套约束（整数年代区间 + ``age(older) >= age(younger) + 1``），
另接收两个查询编号 ``a_id``、``b_id``，在**所有**满足原整数区间与古老关系
的赋值上，计算 ``age(a_id) - age(b_id)`` 的最小值与最大值，并分别给出一组
达到边界的全体地层年代映射（见证，任意合法者均可）。

算法（差分约束 + 最短路，不逐年代枚举）
--------------------------------------
把所有约束写成 ``x_v <= x_u + w`` 的形式并建图（含虚拟源点 ``s``）：

* 上界 ``x_i <= U_i``：边 ``s -> i``，权 ``U_i``；
* 下界 ``x_i >= L_i``：边 ``i -> s``，权 ``-L_i``；
* 关系 ``age(u) >= age(v) + 1``：边 ``u -> v``，权 ``-1``。

沿任意 ``b -> a`` 路径把不等式相加得 ``x_a - x_b <= 路径权和``，故

* ``max(age(a) - age(b)) = d(b, a)``（b 到 a 的最短路）；
* ``min(age(a) - age(b)) = -d(a, b)``。

约束可行（无负环）时该边界必能取到：``z_v = d(b, v) - d(b, s)`` 即一组达到
最大值的合法赋值——最短路满足全部差分约束，平移使 ``z_s = 0`` 后区间界
随之生效；最小值见证同理（改从 a 出发求最短路）。

各层区间经关系相互耦合（例如 ``a >= b + 1`` 时 a 的下界与 b 的上界不能
同时取到），因此最值必须沿关系图传播求解，**不能**直接相减各层独立可行
区间的端点。Bellman-Ford 单次 O(层数 × 边数)，200 层 / 1000 条关系仅约
十万次松弛，与年代值域大小无关。

特殊情形
--------
* 同层查询（``a_id == b_id``）：``d(a, a) = 0``，最小最大值自然都为零；
* 互不连通的地层：两者之间只存在经过源点的路径，最值退化为
  ``U_a - L_b`` / ``L_a - U_b``，与各自独立取端点的直觉一致。
"""

from __future__ import annotations

from typing import Any, Hashable

from .audit import (
    AuditValidationError,
    find_cycle,
    lexicographic_topo,
    tighten_bounds,
    validate_and_build,
)

#: 差分约束图中的虚拟源点。地层编号均为非空字符串，不会与 None 冲突。
_SOURCE: None = None

_INF = float("inf")


def gap(data: dict[str, Any]) -> dict[str, Any]:
    """执行年代差极值查询，返回可直接序列化的结果字典。

    结果形态与 /audit 对齐：约束成环/压空时原样返回 cycle/conflict；
    否则返回 ``{"status": "ok", "min_gap": ..., "max_gap": ...,
    "min_ages": {...}, "max_ages": {...}}``。
    """
    raw_strata: list[dict[str, Any]] = list(data.get("strata") or [])
    raw_relations: list[dict[str, Any]] = list(data.get("relations") or [])
    a_id: str = data["a_id"]
    b_id: str = data["b_id"]

    # ---- 1. 基本校验（与 /audit 完全一致的约束语义） --------------------
    ids, bounds, adjacency = validate_and_build(raw_strata, raw_relations)
    _validate_query_ids(ids, a_id, b_id)

    # ---- 2. 原约束无解时沿用现有 cycle/conflict 结果 --------------------
    cycle = find_cycle(ids, adjacency)
    if cycle is not None:
        return {"status": "cycle", "cycle_path": cycle}

    topo = lexicographic_topo(ids, adjacency)
    lower = {sid: bounds[sid][0] for sid in ids}
    upper = {sid: bounds[sid][1] for sid in ids}
    tighten_bounds(topo, adjacency, lower, upper)

    conflicts = sorted(sid for sid in ids if lower[sid] > upper[sid])
    if conflicts:
        return {
            "status": "conflict",
            "conflicting_strata": conflicts,
            "tight_intervals": {
                sid: {
                    "youngest_ma": lower[sid],
                    "oldest_ma": upper[sid],
                }
                for sid in ids
            },
        }

    # ---- 3. 差分约束图上两次 Bellman-Ford，求最值与见证 -----------------
    # 收紧后的区间与原区间描述同一可行域，直接用作图上界/下界边。
    edges = _build_edges(ids, adjacency, lower, upper)
    dist_from_b = _shortest_paths(ids, edges, b_id)
    dist_from_a = _shortest_paths(ids, edges, a_id)

    max_gap = dist_from_b[a_id]
    min_gap = -dist_from_a[b_id]
    # 见证：z_v = d(src, v) - d(src, s)，平移使源点取 0 后区间界生效。
    max_ages = {sid: dist_from_b[sid] - dist_from_b[_SOURCE] for sid in ids}
    min_ages = {sid: dist_from_a[sid] - dist_from_a[_SOURCE] for sid in ids}

    return {
        "status": "ok",
        "a_id": a_id,
        "b_id": b_id,
        "min_gap": min_gap,
        "max_gap": max_gap,
        "min_ages": min_ages,
        "max_ages": max_ages,
    }


def _validate_query_ids(ids: list[str], a_id: str, b_id: str) -> None:
    """查询编号须已提交，否则抛 :class:`AuditValidationError`（HTTP 422）。"""
    known = set(ids)
    errors = [
        f"查询引用了未提交的地层编号：{name}={value!r}"
        for name, value in (("a_id", a_id), ("b_id", b_id))
        if value not in known
    ]
    if errors:
        raise AuditValidationError(errors)


def _build_edges(
    ids: list[str],
    adjacency: dict[str, set[str]],
    lower: dict[str, int],
    upper: dict[str, int],
) -> list[tuple[Hashable, Hashable, int]]:
    """把约束系统转成 ``x_v <= x_u + w`` 的边列表 ``(u, v, w)``。"""
    edges: list[tuple[Hashable, Hashable, int]] = []
    for sid in ids:
        edges.append((_SOURCE, sid, upper[sid]))  # x_i <= x_s + U_i
        edges.append((sid, _SOURCE, -lower[sid]))  # x_s <= x_i - L_i
    for older in ids:
        for younger in adjacency[older]:
            # age(older) >= age(younger) + 1  =>  x_younger <= x_older - 1
            edges.append((older, younger, -1))
    return edges


def _shortest_paths(
    ids: list[str],
    edges: list[tuple[Hashable, Hashable, int]],
    source: str,
) -> dict[Hashable, int | float]:
    """Bellman-Ford 求 ``source`` 到各地层与虚拟源点的最短路。

    调用前需保证约束可行（无负环）。每层都有到源点的边、源点也有到每层
    的边，故从任意地层出发所有距离均为有限整数。
    """
    nodes: list[Hashable] = [_SOURCE, *ids]
    dist: dict[Hashable, int | float] = {node: _INF for node in nodes}
    dist[source] = 0
    for _ in range(len(nodes) - 1):
        changed = False
        for u, v, w in edges:
            du = dist[u]
            if du is _INF:
                continue
            candidate = du + w
            if candidate < dist[v]:
                dist[v] = candidate
                changed = True
        if not changed:
            break
    return dist
