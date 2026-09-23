"""端到端 API 测试：选题、能力更新、幂等、曝光上限、会话生命周期。"""
from __future__ import annotations


def test_health_and_item_bank(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["items"] == 15

    r = client.get("/items")
    assert r.status_code == 200
    assert r.json()["exposure_cap"] == 3
    assert all(row["exposure"] == 0 for row in r.json()["items"])
    # 管理视图不泄露答案
    assert "answer_index" not in r.json()["items"][0]


def test_create_session_picks_first_item_and_counts_exposure(client) -> None:
    r = client.post("/sessions", json={"max_items": 5})
    assert r.status_code == 201
    data = r.json()
    sid = data["session_id"]
    assert data["status"] == "in_progress"
    assert data["answered_count"] == 0
    first = data["current_item"]
    assert first is not None
    assert set(first.keys()) == {"item_id", "stem", "options"}

    # 施测即计一次曝光
    bank = client.get("/items").json()
    row = next(x for x in bank["items"] if x["item_id"] == first["item_id"])
    assert row["exposure"] == 1

    # 初始 theta=0：各题信息量 I=a²p(1-p)，最大的是 ITM-009（a=1.3, b=0.4）
    assert first["item_id"] == "ITM-009"

    prog = client.get(f"/sessions/{sid}/progress").json()
    assert prog["remaining"] == 5
    assert prog["current_item"]["item_id"] == "ITM-009"


def test_submit_updates_theta_and_adapts_next_item(client) -> None:
    sid = client.post("/sessions", json={}).json()["session_id"]

    r = client.post(
        f"/sessions/{sid}/responses",
        json={"response_id": "r1", "selected_index": 0},  # ITM-009 正确答案
    )
    assert r.status_code == 200
    data = r.json()
    assert data["replayed"] is False
    assert data["correct"] is True
    assert data["score"] == 1
    assert data["theta_after"] > data["theta_before"]
    assert data["answered_count"] == 1
    assert data["next_item"] is not None
    # 答对后 theta 升高，下一题应变难（b 更大）且不重复
    assert data["next_item"]["item_id"] != "ITM-009"
    bank = {x["item_id"]: x for x in client.get("/items").json()["items"]}
    assert bank[data["next_item"]["item_id"]]["b"] > bank["ITM-009"]["b"]


def test_duplicate_response_id_returns_first_result_without_reupdate(client) -> None:
    sid = client.post("/sessions", json={}).json()["session_id"]
    url = f"/sessions/{sid}/responses"
    body = {"response_id": "dup-1", "selected_index": 1}

    first = client.post(url, json=body).json()
    second = client.post(url, json=body).json()

    assert second["replayed"] is True
    assert first["replayed"] is False
    # 首次结果完全一致
    for key in ("theta_before", "theta_after", "item_id", "next_item", "answered_count"):
        assert second[key] == first[key]

    # 进度与记录也只反映一次作答
    prog = client.get(f"/sessions/{sid}/progress").json()
    assert prog["answered_count"] == 1
    hist = client.get(f"/sessions/{sid}/responses").json()
    assert hist["count"] == 1
    assert hist["responses"][0]["response_id"] == "dup-1"

    # 曝光只增加了 2 次（首题 + 第二题），重放不增加
    first_item = next(x for x in client.get("/items").json()["items"] if x["exposure"] >= 1)
    assert first_item["exposure"] == 1


def test_answer_mismatch_and_session_not_found(client) -> None:
    r = client.post("/sessions/SES-does-not-exist/responses",
                    json={"response_id": "x", "selected_index": 0})
    assert r.status_code == 404

    sid = client.post("/sessions", json={}).json()["session_id"]
    r = client.post(f"/sessions/{sid}/responses",
                    json={"response_id": "bad-idx", "selected_index": 9})
    assert r.status_code == 422


def test_exposure_cap_excludes_overexposed_items(client) -> None:
    # 曝光上限 3：让 ITM-009（theta=0 下信息最大）被 3 个会话施测后，
    # 第 4 个新会话的第一题不应再选它。
    for _ in range(3):
        client.post("/sessions", json={"max_items": 1})

    bank = {x["item_id"]: x for x in client.get("/items").json()["items"]}
    assert bank["ITM-009"]["exposure"] == 3
    assert bank["ITM-009"]["exposure_remaining"] == 0

    fourth = client.post("/sessions", json={"max_items": 1}).json()
    assert fourth["current_item"]["item_id"] != "ITM-009"
    # 应选择其余候选题中信息最大的 ITM-010（a=1.4, b=0.8）
    assert fourth["current_item"]["item_id"] == "ITM-010"


def test_session_finishes_at_max_items_and_rejects_further_answers(client) -> None:
    sid = client.post("/sessions", json={"max_items": 2}).json()["session_id"]

    r1 = client.post(f"/sessions/{sid}/responses",
                     json={"response_id": "a", "selected_index": 0}).json()
    assert r1["status"] == "in_progress"
    r2 = client.post(f"/sessions/{sid}/responses",
                     json={"response_id": "b", "selected_index": 0}).json()
    assert r2["status"] == "finished"
    assert r2["finish_reason"] == "max_items_reached"
    assert r2["next_item"] is None

    prog = client.get(f"/sessions/{sid}/progress").json()
    assert prog["status"] == "finished"
    assert prog["remaining"] == 0
    assert prog["current_item"] is None

    r3 = client.post(f"/sessions/{sid}/responses",
                     json={"response_id": "c", "selected_index": 0})
    assert r3.status_code == 409

    # 已结束会话上重放旧 response_id 仍返回首次结果（幂等优先）
    replay = client.post(
        f"/sessions/{sid}/responses",
        json={"response_id": "b", "selected_index": 0},
    ).json()
    assert replay["replayed"] is True


def test_same_item_not_repeated_within_session(client) -> None:
    sid = client.post("/sessions", json={"max_items": 4}).json()["session_id"]
    seen = set()
    for i in range(4):
        cur = (client.get(f"/sessions/{sid}/progress").json())["current_item"]
        assert cur["item_id"] not in seen
        seen.add(cur["item_id"])
        client.post(f"/sessions/{sid}/responses",
                    json={"response_id": f"r{i}", "selected_index": 0})
    assert len(seen) == 4
