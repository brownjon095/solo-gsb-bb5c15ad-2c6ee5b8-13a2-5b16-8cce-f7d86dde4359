"""请求与响应模型。

年代单位为百万年（Ma），整数，数值越大越古老。
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class Stratum(BaseModel):
    """一个地层及其允许的整数年代区间 [youngest_ma, oldest_ma]。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="地层唯一编号")
    youngest_ma: StrictInt = Field(
        ..., description="允许的最年轻年代（Ma，下界）"
    )
    oldest_ma: StrictInt = Field(
        ..., description="允许的最古老年代（Ma，上界）"
    )


class OlderRelation(BaseModel):
    """观测关系：older_id 比 younger_id 古老。

    服务将其转换为约束 age(older_id) >= age(younger_id) + 1。
    """

    model_config = ConfigDict(extra="forbid")

    older_id: str = Field(..., min_length=1, description="较古老的地层编号（甲）")
    younger_id: str = Field(..., min_length=1, description="较年轻的地层编号（乙）")


class AuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strata: list[Stratum] = Field(..., min_length=1, description="提交的地层列表")
    relations: list[OlderRelation] = Field(
        default_factory=list, description="“甲比乙古老”的观测关系列表"
    )


class IntervalOut(BaseModel):
    youngest_ma: int
    oldest_ma: int


class CycleResponse(BaseModel):
    status: Literal["cycle"]
    cycle_path: list[str] = Field(
        ..., description="成环的地层编号路径，首尾编号相同"
    )


class ConflictResponse(BaseModel):
    status: Literal["conflict"]
    conflicting_strata: list[str] = Field(
        ..., description="收紧后可行区间被压空的地层编号"
    )
    tight_intervals: dict[str, IntervalOut] = Field(
        ..., description="沿关系图传播收紧后的各层年代区间"
    )


class FeasibleResponse(BaseModel):
    status: Literal["feasible"]
    tight_intervals: dict[str, IntervalOut] = Field(
        ..., description="沿关系图传播收紧后的各层年代区间"
    )
    oldest_to_youngest: list[str] = Field(
        ..., description="古老 -> 年轻方向上编号字典序最小的合法顺序"
    )


AuditResponse = Annotated[
    Union[CycleResponse, ConflictResponse, FeasibleResponse],
    Field(discriminator="status"),
]


# ---- POST /fit：偏好拟合 -------------------------------------------------

#: /explain、/fit 与 /gap 支持的最大地层数
MAX_STRATA = 200
#: /explain、/fit 与 /gap 支持的最大关系数
MAX_RELATIONS = 1000
#: 年代与参考年代允许的绝对值上限
MAX_ABS_MA = 10**12
#: 偏好权重上限（正整数）
MAX_WEIGHT = 10**6


class FitStratum(BaseModel):
    """/fit 与 /gap 的地层：区间端点绝对值不得超过 10^12。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="地层唯一编号")
    youngest_ma: StrictInt = Field(
        ...,
        ge=-MAX_ABS_MA,
        le=MAX_ABS_MA,
        description="允许的最年轻年代（Ma，下界，绝对值 ≤ 10^12）",
    )
    oldest_ma: StrictInt = Field(
        ...,
        ge=-MAX_ABS_MA,
        le=MAX_ABS_MA,
        description="允许的最古老年代（Ma，上界，绝对值 ≤ 10^12）",
    )


class Preference(BaseModel):
    """单层的拟合偏好：参考年代 target_ma 与正整数权重 weight。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ..., min_length=1, description="地层编号（须已提交，每层恰好一项）"
    )
    target_ma: StrictInt = Field(
        ...,
        ge=-MAX_ABS_MA,
        le=MAX_ABS_MA,
        description="参考年代（Ma，整数，绝对值 ≤ 10^12）",
    )
    weight: StrictInt = Field(
        ..., ge=1, le=MAX_WEIGHT, description="偏差权重（正整数，≤ 10^6）"
    )


class FitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strata: list[FitStratum] = Field(
        ..., min_length=1, max_length=MAX_STRATA, description="提交的地层列表"
    )
    relations: list[OlderRelation] = Field(
        default_factory=list,
        max_length=MAX_RELATIONS,
        description="“甲比乙古老”的观测关系列表",
    )
    preferences: list[Preference] = Field(
        ...,
        max_length=MAX_STRATA,
        description="每层的拟合偏好（恰好一项：缺漏、重复或未知编号返回 422）",
    )


class OptimalResponse(BaseModel):
    status: Literal["optimal"]
    optimal_value: int = Field(
        ..., description="最优值：最小的 max(weight × |age − target_ma|)"
    )
    ages: dict[str, int] = Field(
        ...,
        description=(
            "各地层的最优整数年代；多解时取按编号升序排列的年代向量中"
            "字典序最小者"
        ),
    )


FitResponse = Annotated[
    Union[CycleResponse, ConflictResponse, OptimalResponse],
    Field(discriminator="status"),
]


# ---- POST /gap：年代差极值查询 --------------------------------------------


class GapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strata: list[FitStratum] = Field(
        ..., min_length=1, max_length=MAX_STRATA, description="提交的地层列表"
    )
    relations: list[OlderRelation] = Field(
        default_factory=list,
        max_length=MAX_RELATIONS,
        description="“甲比乙古老”的观测关系列表",
    )
    a_id: str = Field(
        ..., min_length=1, description="被减地层编号（须已提交）"
    )
    b_id: str = Field(
        ..., min_length=1, description="减数地层编号（须已提交）"
    )


class GapOkResponse(BaseModel):
    status: Literal["ok"]
    a_id: str = Field(..., description="被减地层编号（回显）")
    b_id: str = Field(..., description="减数地层编号（回显）")
    min_gap: int = Field(
        ..., description="全部合法赋值中 age(a_id) − age(b_id) 的最小值"
    )
    max_gap: int = Field(
        ..., description="全部合法赋值中 age(a_id) − age(b_id) 的最大值"
    )
    min_ages: dict[str, int] = Field(
        ..., description="达到最小值的一组合法整数年代映射（见证，任一即可）"
    )
    max_ages: dict[str, int] = Field(
        ..., description="达到最大值的一组合法整数年代映射（见证，任一即可）"
    )


GapResponse = Annotated[
    Union[CycleResponse, ConflictResponse, GapOkResponse],
    Field(discriminator="status"),
]


# ---- POST /explain：最小不可行关系定位 -----------------------------------


class ExplainRequest(BaseModel):
    """请求形态与 /audit 相同：地层区间（整数年代）+ 观测关系。

    规模上限（越界返回 422）：最多 200 层、1000 条关系；
    其余基本校验（重复编号、非法区间、自比古老、未知引用）沿用 /audit。
    """

    model_config = ConfigDict(extra="forbid")

    strata: list[Stratum] = Field(
        ..., min_length=1, max_length=MAX_STRATA, description="提交的地层列表"
    )
    relations: list[OlderRelation] = Field(
        default_factory=list,
        max_length=MAX_RELATIONS,
        description="“甲比乙古老”的观测关系列表（重复关系按输入位置各自编号）",
    )


class ExplainFeasibleResponse(BaseModel):
    status: Literal["feasible"]


class ExplainCycleResponse(BaseModel):
    status: Literal["cycle"]
    relation_indices: list[int] = Field(
        ...,
        description=(
            "最小不可行关系在原请求 relations 中的序号（从 1 开始、升序）；"
            "该组关系成环，移去其中任一条后约束可行"
        ),
    )


class ExplainConflictResponse(BaseModel):
    status: Literal["conflict"]
    relation_indices: list[int] = Field(
        ...,
        description=(
            "最小不可行关系在原请求 relations 中的序号（从 1 开始、升序）；"
            "该组关系使整数年代区间被压空，移去其中任一条后约束可行"
        ),
    )


ExplainResponse = Annotated[
    Union[ExplainFeasibleResponse, ExplainCycleResponse, ExplainConflictResponse],
    Field(discriminator="status"),
]
