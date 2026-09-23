"""测试夹具：在导入 app 之前把数据库指向临时文件。"""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()

os.environ["CAT_DB_PATH"] = _TMP.name
os.environ["CAT_MAX_ITEMS"] = "10"
os.environ["CAT_EXPOSURE_CAP"] = "3"
os.environ["CAT_INITIAL_THETA"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import database  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    """每个测试重建一份干净的题库与空库。"""
    if os.path.exists(_TMP.name):
        os.remove(_TMP.name)
    database.init_db(_TMP.name)
    with TestClient(app) as c:
        yield c
