"""运行期配置，均可通过环境变量覆盖。"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("CAT_DB_PATH", "/data/cat.db")
    initial_theta: float = _float("CAT_INITIAL_THETA", 0.0)
    max_items: int = _int("CAT_MAX_ITEMS", 10)
    exposure_cap: int = _int("CAT_EXPOSURE_CAP", 5)
    theta_bound: float = _float("CAT_THETA_BOUND", 4.0)


settings = Settings()
