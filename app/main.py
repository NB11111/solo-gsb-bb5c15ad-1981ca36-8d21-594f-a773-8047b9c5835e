"""FastAPI 应用：自适应测验选题 API。

选题流程
========
1. 候选题 = 本会话未作答 且 全局曝光次数 < 曝光上限 的题。
2. 在候选题中按 2PL Fisher 信息量 I_j(theta) 取最大；信息量相同取最小 item_id
   （稳定、确定性的平局规则）。
3. 选中即把该题 exposure + 1（曝光在施测时计数，重复/幂等请求不会再加）。
4. 提交答案后，在全部历史作答上做一次 warm-started Newton 更新估计 theta。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Path

from . import irt
from .config import settings
from .database import connect, init_db
from .schemas import (
    CreateSessionRequest,
    Health,
    ItemBank,
    ItemBankRow,
    ItemBrief,
    OptionOut,
    Progress,
    ResponseHistory,
    ResponseRecord,
    SessionCreated,
    SubmitResponseRequest,
    SubmitResult,
)

ISO = "%Y-%m-%dT%H:%M:%S.%fZ"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime(ISO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="自适应测验选题 API",
    description=(
        "2PL IRT 计算机化自适应测验（CAT）：每题保存难度 b、区分度 a 与曝光次数；"
        "提交答案后用一次 Newton 更新估计能力值；在满足曝光上限的候选题中按信息量"
        "与稳定 item_id 选择下一题。response_id 幂等。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


def get_conn() -> sqlite3.Connection:
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


# --------------------------------------------------------------------------- helpers


def _item_brief(row: sqlite3.Row) -> ItemBrief:
    options = [OptionOut(index=i, text=text) for i, text in enumerate(json.loads(row["options_json"]))]
    return ItemBrief(item_id=row["id"], stem=row["stem"], options=options)


def _get_session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return row


def _get_item(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:  # 理论上不会发生（外键保证）
        raise HTTPException(status_code=500, detail=f"题目缺失: {item_id}")
    return row


def _administer_next_item(
    conn: sqlite3.Connection, session: sqlite3.Row
) -> tuple[sqlite3.Row | None, str | None]:
    """选下一题并原子地增加曝光。返回 (item_row, finish_reason)。

    必须在 BEGIN IMMEDIATE 事务内调用。
    """
    if session["answered_count"] >= session["max_items"]:
        return None, "max_items_reached"

    candidates = conn.execute(
        """
        SELECT id, a, b
          FROM items
         WHERE exposure < ?
           AND id NOT IN (
               SELECT item_id FROM responses WHERE session_id = ?
           )
         ORDER BY id
        """,
        (session["exposure_cap"], session["id"]),
    ).fetchall()

    if not candidates:
        return None, "no_available_items"

    chosen_id = irt.choose([(r["id"], r["a"], r["b"]) for r in candidates], session["theta"])
    cur = conn.execute("UPDATE items SET exposure = exposure + 1 WHERE id = ?", (chosen_id,))
    assert cur.rowcount == 1
    return _get_item(conn, chosen_id), None


def _finish_session(conn: sqlite3.Connection, session_id: str, reason: str, when: str) -> None:
    conn.execute(
        "UPDATE sessions SET current_item_id = NULL, status='finished', "
        "finish_reason=?, updated_at=? WHERE id=?",
        (reason, when, session_id),
    )


def _set_current(conn: sqlite3.Connection, session_id: str, item_id: str, when: str) -> None:
    conn.execute(
        "UPDATE sessions SET current_item_id=?, updated_at=? WHERE id=?",
        (item_id, when, session_id),
    )


# --------------------------------------------------------------------------- root


@app.get("/", tags=["meta"])
def index() -> dict[str, Any]:
    return {
        "service": "adaptive-quiz-api",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "endpoints": [
            "POST /sessions",
            "GET  /sessions/{session_id}/progress",
            "POST /sessions/{session_id}/responses",
            "GET  /sessions/{session_id}/responses",
            "GET  /items",
            "GET  /health",
        ],
    }


@app.get("/health", response_model=Health, tags=["meta"])
def health(conn: sqlite3.Connection = Depends(get_conn)) -> Health:
    items = conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
    sessions = conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
    return Health(status="ok", items=items, sessions=sessions)


# --------------------------------------------------------------------------- sessions


@app.post("/sessions", response_model=SessionCreated, status_code=201, tags=["sessions"])
def create_session(
    body: CreateSessionRequest | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
) -> SessionCreated:
    body = body or CreateSessionRequest()
    max_items = body.max_items or settings.max_items
    exposure_cap = body.exposure_cap or settings.exposure_cap
    session_id = f"SES-{uuid.uuid4().hex[:12]}"
    when = utcnow()

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO sessions (id, theta, current_item_id, answered_count, max_items, "
            "exposure_cap, status, finish_reason, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?, 'in_progress', NULL, ?, ?)",
            (
                session_id,
                settings.initial_theta,
                None,
                0,
                max_items,
                exposure_cap,
                when,
                when,
            ),
        )
        session = _get_session(conn, session_id)
        item, reason = _administer_next_item(conn, session)
        if item is None:
            _finish_session(conn, session_id, reason or "no_available_items", when)
        else:
            _set_current(conn, session_id, item["id"], when)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    fresh = _get_session(conn, session_id)
    current = _item_brief(_get_item(conn, fresh["current_item_id"])) if fresh["current_item_id"] else None
    return SessionCreated(
        session_id=session_id,
        status=fresh["status"],  # type: ignore[arg-type]
        theta=round(fresh["theta"], 6),
        answered_count=fresh["answered_count"],
        max_items=fresh["max_items"],
        exposure_cap=fresh["exposure_cap"],
        current_item=current,
        finish_reason=fresh["finish_reason"],
        created_at=fresh["created_at"],
    )


@app.get(
    "/sessions/{session_id}/progress",
    response_model=Progress,
    tags=["sessions"],
)
def get_progress(
    session_id: str = Path(..., min_length=1),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Progress:
    s = _get_session(conn, session_id)
    current = _item_brief(_get_item(conn, s["current_item_id"])) if s["current_item_id"] else None
    return Progress(
        session_id=s["id"],
        status=s["status"],  # type: ignore[arg-type]
        theta=round(s["theta"], 6),
        answered_count=s["answered_count"],
        max_items=s["max_items"],
        remaining=max(0, s["max_items"] - s["answered_count"]),
        exposure_cap=s["exposure_cap"],
        current_item=current,
        finish_reason=s["finish_reason"],
        created_at=s["created_at"],
        updated_at=s["updated_at"],
    )


# --------------------------------------------------------------------------- responses


@app.post(
    "/sessions/{session_id}/responses",
    response_model=SubmitResult,
    tags=["responses"],
)
def submit_response(
    body: SubmitResponseRequest,
    session_id: str = Path(..., min_length=1),
    conn: sqlite3.Connection = Depends(get_conn),
) -> SubmitResult:
    # 1) 幂等检查放在最前：重复 response_id 直接返回首次结果，绝不再次更新能力/曝光。
    existing = conn.execute(
        "SELECT result_json FROM responses WHERE session_id = ? AND id = ?",
        (session_id, body.response_id),
    ).fetchone()
    if existing is not None:
        payload = json.loads(existing["result_json"])
        payload["replayed"] = True
        return SubmitResult(**payload)

    # 2) 校验会话与当前待答题状态。
    session = _get_session(conn, session_id)
    if session["status"] != "in_progress" or session["current_item_id"] is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "session_not_active",
                "message": f"会话已结束（{session['finish_reason']}），不能继续提交答案",
                "session_id": session_id,
            },
        )

    item_id = session["current_item_id"]
    item = _get_item(conn, item_id)
    answer_index = item["answer_index"]
    if not 0 <= body.selected_index < len(json.loads(item["options_json"])):
        # Pydantic 已约束 0..3；此处对题项实际选项数做最终防线。
        raise HTTPException(status_code=422, detail="selected_index 超出题项选项范围")

    score = int(body.selected_index == answer_index)
    theta_before = session["theta"]

    conn.execute("BEGIN IMMEDIATE")
    try:
        # 双重检查：防止并发下同一 response_id 双写（主键也会兜底）。
        dup = conn.execute(
            "SELECT result_json FROM responses WHERE session_id = ? AND id = ?",
            (session_id, body.response_id),
        ).fetchone()
        if dup is not None:
            conn.rollback()
            payload = json.loads(dup["result_json"])
            payload["replayed"] = True
            return SubmitResult(**payload)

        # 3) 取全部历史作答参数（含本题），做一次 Newton 更新。
        history_rows = conn.execute(
            """
            SELECT i.a AS a, i.b AS b, r.score AS score
              FROM responses r
              JOIN items i ON i.id = r.item_id
             WHERE r.session_id = ?
             ORDER BY r.rowid
            """,
            (session_id,),
        ).fetchall()
        history = [(r["a"], r["b"], r["score"]) for r in history_rows]
        history.append((item["a"], item["b"], score))

        result = irt.newton_update(history, theta_before, bound=settings.theta_bound)
        when = utcnow()

        # 4) 写入作答记录。
        conn.execute(
            "INSERT INTO responses (id, session_id, item_id, selected_index, answer_index, "
            "score, probability, theta_before, theta_after, result_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                body.response_id,
                session_id,
                item_id,
                body.selected_index,
                answer_index,
                score,
                result.probability,
                theta_before,
                result.theta,
                "",  # 先占位，下面回填 JSON
                when,
            ),
        )

        answered_count = session["answered_count"] + 1
        conn.execute(
            "UPDATE sessions SET theta=?, current_item_id=NULL, answered_count=?, updated_at=? "
            "WHERE id=?",
            (result.theta, answered_count, when, session_id),
        )

        # 5) 选择下一题（受曝光上限约束），或结束会话。
        updated_session = _get_session(conn, session_id)
        next_row, finish_reason = _administer_next_item(conn, updated_session)
        if next_row is None:
            _finish_session(conn, session_id, finish_reason or "no_available_items", when)
            status, next_brief = "finished", None
        else:
            _set_current(conn, session_id, next_row["id"], when)
            status, next_brief = "in_progress", _item_brief(next_row)

        payload = {
            "replayed": False,
            "response_id": body.response_id,
            "item_id": item_id,
            "selected_index": body.selected_index,
            "answer_index": answer_index,
            "correct": bool(score),
            "score": score,
            "probability": round(result.probability, 6),
            "theta_before": round(theta_before, 6),
            "theta_after": round(result.theta, 6),
            "answered_count": answered_count,
            "next_item": next_brief.model_dump() if next_brief else None,
            "status": status,
            "finish_reason": finish_reason if next_row is None else None,
        }
        conn.execute(
            "UPDATE responses SET result_json=? WHERE session_id=? AND id=?",
            (json.dumps(payload, ensure_ascii=False), session_id, body.response_id),
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise

    return SubmitResult(**payload)


@app.get(
    "/sessions/{session_id}/responses",
    response_model=ResponseHistory,
    tags=["responses"],
)
def list_responses(
    session_id: str = Path(..., min_length=1),
    conn: sqlite3.Connection = Depends(get_conn),
) -> ResponseHistory:
    _get_session(conn, session_id)  # 404 if missing
    rows = conn.execute(
        "SELECT * FROM responses WHERE session_id = ? ORDER BY rowid",
        (session_id,),
    ).fetchall()
    records = [
        ResponseRecord(
            response_id=r["id"],
            item_id=r["item_id"],
            selected_index=r["selected_index"],
            answer_index=r["answer_index"],
            score=r["score"],
            correct=bool(r["score"]),
            probability=round(r["probability"], 6),
            theta_before=round(r["theta_before"], 6),
            theta_after=round(r["theta_after"], 6),
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return ResponseHistory(session_id=session_id, count=len(records), responses=records)


# --------------------------------------------------------------------------- item bank


@app.get("/items", response_model=ItemBank, tags=["items"])
def list_items(
    session_id: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
) -> ItemBank:
    """题库管理视图：参数与曝光计数（不返回正确答案）。

    可选 `?session_id=...` 标注该会话已施测过的题。
    """
    administered: set[str] = set()
    if session_id:
        _get_session(conn, session_id)
        administered = {
            r["item_id"]
            for r in conn.execute(
                "SELECT item_id FROM responses WHERE session_id = ?", (session_id,)
            ).fetchall()
        }

    rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
    items = [
        ItemBankRow(
            item_id=r["id"],
            a=r["a"],
            b=r["b"],
            exposure=r["exposure"],
            exposure_remaining=max(0, settings.exposure_cap - r["exposure"]),
            administered=r["id"] in administered,
        )
        for r in rows
    ]
    return ItemBank(exposure_cap=settings.exposure_cap, count=len(items), items=items)
