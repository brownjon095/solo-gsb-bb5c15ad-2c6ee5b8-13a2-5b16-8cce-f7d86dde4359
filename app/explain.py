"""不可行关系定位：从提交的观测关系中找出一组“最小不可行关系”。

与 /audit 共用同一套约束（整数年代区间 + ``age(older) >= age(younger) + 1``）
与同一套基本校验（重复编号、非法区间、自比古老、引用未知编号）。整体约束
可行时仅返回 ``{"status": "feasible"}``；不可行时返回一组关系在**原请求
``relations`` 中的序号**（从 1 开始、升序），满足：

* 该组关系本身与地层区间一起**仍然不可行**；
* 移去其中**任一条**后，剩余关系即变为可行（最小不可行子集，MUS）。

算法（删除法，复用 :mod:`app.audit` 的成环检测与区间传播）
-------------------------------------------------------
自全部关系开始，按序号**从大到小**逐条试探：删除该关系后若仍不可行，则
永久删除；若变为可行，则恢复并保留（该关系不可或缺）。试探结束后剩下的
关系集即一个最小不可行子集——不变式为“当前集合始终不可行”，而每条被
保留的关系都被验证过不可或缺。

* 重复关系按输入位置各自编号；从最大序号开始试探使**首次出现**的位置
  优先保留（结果确定，不依赖哈希顺序）。
* 类型判定：该子集关系图含环即为 ``cycle``（成环本身已不可行），
  无环时不可行只能来自区间被压空，即为 ``conflict``。

单次可行性判定为 O(层数 + 关系数 × log 层数)，整体
``O(关系数 × (层数 + 关系数 log 层数))``；1000 条关系规模下为
百万次基本运算量级，与年代值域大小无关。
"""

from __future__ import annotations

from typing import Any

from .audit import (
    find_cycle,
    lexicographic_topo,
    tighten_bounds,
    validate_and_build,
)


def explain(data: dict[str, Any]) -> dict[str, Any]:
    """定位最小不可行关系组，返回可直接序列化的结果字典。

    可行时返回 ``{"status": "feasible"}``；不可行时返回
    ``{"status": "cycle" | "conflict", "relation_indices": [...]}``，
    序号从 1 开始、升序排列，且该组满足最小不可行性。
    """
    raw_strata: list[dict[str, Any]] = list(data.get("strata") or [])
    raw_relations: list[dict[str, Any]] = list(data.get("relations") or [])

    # ---- 1. 基本校验（与 /audit 完全一致），同时取得编号与原始区间 ------
    ids, bounds, _ = validate_and_build(raw_strata, raw_relations)

    # 关系按输入位置保存；基本校验已保证无自环、无未知引用，故可直接建图。
    edges: list[tuple[str, str]] = [
        (rel["older_id"], rel["younger_id"]) for rel in raw_relations
    ]
    kept: set[int] = set(range(len(edges)))

    # ---- 2. 整体可行即直接返回 ------------------------------------------
    if _is_feasible(ids, bounds, edges, kept):
        return {"status": "feasible"}

    # ---- 3. 删除法提取最小不可行子集 ------------------------------------
    # 从最大序号向小试探：删除后仍不可行则永久删除，否则恢复保留。
    # 重复关系因此优先保留首次出现的位置。
    for index in range(len(edges) - 1, -1, -1):
        kept.remove(index)
        if not _is_feasible(ids, bounds, edges, kept):
            continue  # 删除后仍不可行：该关系可省，保持删除
        kept.add(index)  # 删除后可行：该关系不可或缺，恢复

    # ---- 4. 序号与类型 ---------------------------------------------------
    relation_indices = sorted(index + 1 for index in kept)
    adjacency = _build_adjacency(ids, edges, kept)
    kind = "cycle" if find_cycle(ids, adjacency) is not None else "conflict"
    return {"status": kind, "relation_indices": relation_indices}


def _build_adjacency(
    ids: list[str], edges: list[tuple[str, str]], kept: set[int]
) -> dict[str, set[str]]:
    """按保留的关系位置子集建图（``older -> younger``，重复边自动去重）。"""
    adjacency: dict[str, set[str]] = {sid: set() for sid in ids}
    for index in kept:
        older, younger = edges[index]
        adjacency[older].add(younger)
    return adjacency


def _is_feasible(
    ids: list[str],
    bounds: dict[str, tuple[int, int]],
    edges: list[tuple[str, str]],
    kept: set[int],
) -> bool:
    """判定仅保留 ``kept`` 位置的关系时约束是否可行。

    直接复用 /audit 的判定链：成环即不可行；无环时在 DAG 上双向传播
    收紧区间，任一层 ``L > U`` 即区间冲突，否则可行。
    """
    adjacency = _build_adjacency(ids, edges, kept)
    if find_cycle(ids, adjacency) is not None:
        return False
    topo = lexicographic_topo(ids, adjacency)
    lower = {sid: bounds[sid][0] for sid in ids}
    upper = {sid: bounds[sid][1] for sid in ids}
    tighten_bounds(topo, adjacency, lower, upper)
    return all(lower[sid] <= upper[sid] for sid in ids)
