"""IRT 数值单元测试。"""
from __future__ import annotations

import math

from app import irt


def test_probability_extremes_and_midpoint() -> None:
    assert irt.probability(1.0, 0.0, 0.0) == 0.5
    assert irt.probability(1.0, -100.0, 0.0) == 1.0
    assert irt.probability(1.0, 100.0, 0.0) == 0.0


def test_information_symmetric_and_nonnegative() -> None:
    # 在 b 处 P=0.5，信息量最大；关于 (theta-b) 符号对称。
    peak = irt.information(1.2, 0.5, theta=0.5)
    assert math.isclose(peak, 1.2**2 * 0.25, rel_tol=1e-12)
    assert math.isclose(
        irt.information(1.2, 0.0, 1.0), irt.information(1.2, 0.0, -1.0), rel_tol=1e-12
    )
    assert irt.information(1.0, 0.0, 100.0) <= 1e-12


def test_newton_correct_answer_moves_theta_up() -> None:
    # 答对一道难度 1.0 的题，theta 应上升。
    res = irt.newton_update([(1.0, 1.0, 1)], theta0=0.0)
    assert res.theta > 0.0


def test_newton_wrong_answer_moves_theta_down() -> None:
    res = irt.newton_update([(1.0, -1.0, 0)], theta0=0.0)
    assert res.theta < 0.0


def test_newton_degenerate_all_easy_correct_keeps_theta() -> None:
    # 极容易题全对：h≈0，数值不可靠时保持 theta（不发散）。
    res = irt.newton_update([(1.0, -100.0, 1)] * 3, theta0=0.0)
    assert res.theta == 0.0


def test_newton_uses_full_history() -> None:
    # 两题历史 vs 只放最后一题，结果应不同。
    full = irt.newton_update([(1.0, -0.5, 1), (1.0, 0.5, 0)], theta0=0.0)
    single = irt.newton_update([(1.0, 0.5, 0)], theta0=0.0)
    assert full.theta != single.theta


def test_choose_max_information_and_stable_tie() -> None:
    # theta=0 时，b 离 0 近的信息量大。
    chosen = irt.choose([("ITM-002", 1.0, -1.5), ("ITM-001", 1.0, 0.2)], theta=0.0)
    assert chosen == "ITM-001"

    # 平局时取稳定最小的 item_id（与传入顺序无关）。
    cands = [("ITM-009", 1.0, 0.0), ("ITM-001", 1.0, 0.0), ("ITM-005", 1.0, 0.0)]
    assert irt.choose(list(reversed(cands)), theta=0.0) == "ITM-001"
