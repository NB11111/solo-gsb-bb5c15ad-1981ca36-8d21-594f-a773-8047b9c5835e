"""2PL IRT 核心计算：作答概率、Fisher 信息量与一次 Newton 更新。

2PL 模型
--------
对题 j（区分度 a_j、难度 b_j）、考生能力 theta：

    P_j(theta) = sigmoid(D * a_j * (theta - b_j))

取 D = 1.0（logistic 度量）。信息量：

    I_j(theta) = a_j^2 * P_j(theta) * (1 - P_j(theta))

能力的极大似然估计（MLE），用当前能力作为初值只做一次 Newton 迭代：

    g(theta) = D * Σ a_j (u_j - P_j)
    h(theta) = D^2 * Σ a_j^2 P_j (1 - P_j)
    theta_new = theta_0 + g / h

每提交一次答案，服务端在「此前全部作答历史」上执行这一次更新
（warm-started one-step Newton），并把结果截断在 [-BOUND, BOUND]。
当 h 过小（全对/全错初期等）时梯度步不可靠，保持原能力不变。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

D = 1.0
_SENTINEL_CUTOFF = 30.0


def sigmoid(x: float) -> float:
    if x >= _SENTINEL_CUTOFF:
        return 1.0
    if x <= -_SENTINEL_CUTOFF:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def probability(a: float, b: float, theta: float) -> float:
    """2PL 正确作答概率 P_j(theta)。"""
    return sigmoid(D * a * (theta - b))


def information(a: float, b: float, theta: float) -> float:
    """题项在能力 theta 处的 Fisher 信息量 I_j(theta)。"""
    p = probability(a, b, theta)
    return a * a * p * (1.0 - p)


@dataclass
class NewtonResult:
    theta: float
    score: int
    probability: float
    gradient: float
    hessian: float


def newton_update(
    history: list[tuple[float, float, int]],
    theta0: float,
    bound: float = 4.0,
) -> NewtonResult:
    """在完整作答历史上做一次 Newton 更新。

    history: [(a, b, score), ...]，包含本次刚提交的答案。
    theta0:   上一次估计的能力值（本题提交前）。
    """
    gradient = 0.0
    hessian = 0.0
    p_last = 0.0
    score_last = 0

    for idx, (a, b, score) in enumerate(history):
        p = probability(a, b, theta0)
        if idx == len(history) - 1:
            p_last, score_last = p, score
        gradient += D * a * (score - p)
        hessian += (D * D) * (a * a) * p * (1.0 - p)

    if hessian < 1e-10:
        # 信息量趋零（典型：全对/全错），梯度步不数值稳定，保持原估计。
        new_theta = theta0
    else:
        new_theta = max(-bound, min(bound, theta0 + gradient / hessian))

    return NewtonResult(
        theta=new_theta,
        score=score_last,
        probability=p_last,
        gradient=gradient,
        hessian=hessian,
    )


def choose(
    candidates: list[tuple[str, float, float]],
    theta: float,
) -> str:
    """从候选题中选信息量最大的题；信息量相同取稳定且最小的 item_id。

    candidates: [(item_id, a, b), ...]
    """
    best_id: str | None = None
    best_info = -1.0
    for item_id, a, b in candidates:
        info = information(a, b, theta)
        if info > best_info + 1e-15:
            best_info, best_id = info, item_id
        elif abs(info - best_info) <= 1e-15 and best_id is not None and item_id < best_id:
            best_id = item_id
    assert best_id is not None
    return best_id
