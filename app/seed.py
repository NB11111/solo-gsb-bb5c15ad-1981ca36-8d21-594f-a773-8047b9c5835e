"""初始题库：每题含题干、4 个选项、正确项下标，以及 2PL 参数 a（区分度）、b（难度）。"""
from __future__ import annotations

import json
from typing import Any

_RAW: list[dict[str, Any]] = [
    {
        "id": "ITM-001",
        "stem": "计算：7 + 8 = ?",
        "options": ["13", "14", "15", "16"],
        "answer_index": 2,
        "a": 0.8,
        "b": -2.5,
    },
    {
        "id": "ITM-002",
        "stem": "一个三角形内角和是多少度？",
        "options": ["90°", "180°", "270°", "360°"],
        "answer_index": 1,
        "a": 0.9,
        "b": -2.2,
    },
    {
        "id": "ITM-003",
        "stem": "计算：6 × 7 = ?",
        "options": ["36", "42", "48", "49"],
        "answer_index": 1,
        "a": 1.0,
        "b": -1.8,
    },
    {
        "id": "ITM-004",
        "stem": "0.5 用分数表示为？",
        "options": ["1/5", "1/4", "1/2", "2/3"],
        "answer_index": 2,
        "a": 1.0,
        "b": -1.4,
    },
    {
        "id": "ITM-005",
        "stem": "若 3x = 12，则 x = ?",
        "options": ["2", "3", "4", "6"],
        "answer_index": 2,
        "a": 1.1,
        "b": -1.0,
    },
    {
        "id": "ITM-006",
        "stem": "圆的直径是 10，半径是多少？",
        "options": ["2", "5", "10", "20"],
        "answer_index": 1,
        "a": 1.1,
        "b": -0.7,
    },
    {
        "id": "ITM-007",
        "stem": "计算：(-3) × (-4) = ?",
        "options": ["-12", "-7", "7", "12"],
        "answer_index": 3,
        "a": 1.2,
        "b": -0.3,
    },
    {
        "id": "ITM-008",
        "stem": "化简：2(x + 3) - x = ?",
        "options": ["x+3", "x+6", "3x+3", "3x+6"],
        "answer_index": 1,
        "a": 1.2,
        "b": 0.0,
    },
    {
        "id": "ITM-009",
        "stem": "数据 2, 4, 4, 6, 9 的中位数是？",
        "options": ["4", "5", "6", "9"],
        "answer_index": 0,
        "a": 1.3,
        "b": 0.4,
    },
    {
        "id": "ITM-010",
        "stem": "直角三角形两直角边为 3 和 4，斜边长为？",
        "options": ["5", "6", "7", "√7"],
        "answer_index": 0,
        "a": 1.4,
        "b": 0.8,
    },
    {
        "id": "ITM-011",
        "stem": "若 log₂(x) = 3，则 x = ?",
        "options": ["6", "8", "9", "12"],
        "answer_index": 1,
        "a": 1.4,
        "b": 1.2,
    },
    {
        "id": "ITM-012",
        "stem": "函数 f(x) = x² 在 x = 3 处的导数是？",
        "options": ["3", "6", "9", "12"],
        "answer_index": 1,
        "a": 1.5,
        "b": 1.6,
    },
    {
        "id": "ITM-013",
        "stem": "∫₀¹ 2x dx = ?",
        "options": ["1/2", "1", "2", "4"],
        "answer_index": 1,
        "a": 1.5,
        "b": 2.0,
    },
    {
        "id": "ITM-014",
        "stem": "向量 (1,2) 与 (2,-1) 的点积是？",
        "options": ["0", "1", "2", "4"],
        "answer_index": 0,
        "a": 1.6,
        "b": 2.3,
    },
    {
        "id": "ITM-015",
        "stem": "lim(x→0) sin(x)/x = ?",
        "options": ["0", "1/2", "1", "不存在"],
        "answer_index": 2,
        "a": 1.7,
        "b": 2.7,
    },
]


def _serialize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for it in items:
        row = dict(it)
        row["options_json"] = json.dumps(it["options"], ensure_ascii=False)
        del row["options"]
        out.append(row)
    return out


SEED_ITEMS = _serialize(_RAW)
