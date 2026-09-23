"""仅用标准库的端到端演示：创建会话 → 作答 → 幂等重放 → 查询。

用法：
    python demo.py            # 默认 http://127.0.0.1:8000
    BASE=http://x:8000 python demo.py
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE = os.getenv("BASE", "http://127.0.0.1:8000").rstrip("/")


def call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def show(title: str, value: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> None:
    print(f"目标服务: {BASE}")

    status, health = call("GET", "/health")
    show("健康检查", {"http": status, **health})

    status, session = call("POST", "/sessions", {"max_items": 5})
    show("创建会话", {"http": status, **session})
    sid = session["session_id"]

    response_id = "resp-demo-0001"
    first_answer = 0  # 故意先选 A（下标 0），便于观察 theta 变化

    for turn in range(5):
        current = session["current_item"] if turn == 0 else result["next_item"]
        if current is None:
            print("没有更多题目，测验结束。")
            break

        # 第一轮演示：同一 response_id 提交两次，验证幂等。
        body = {"response_id": response_id if turn == 0 else f"resp-demo-{turn+1:04d}",
                "selected_index": first_answer if turn == 0 else current["options"][0]["index"]}
        status, result = call("POST", f"/sessions/{sid}/responses", body)
        show(f"第 {turn+1} 次作答", {"http": status, **result})

        if turn == 0:
            status, replay = call("POST", f"/sessions/{sid}/responses", body)
            show("同一 response_id 重放（应 replayed=true，theta/曝光不重复更新）",
                 {"http": status, **replay})

    status, progress = call("GET", f"/sessions/{sid}/progress")
    show("会话进度", {"http": status, **progress})

    status, history = call("GET", f"/sessions/{sid}/responses")
    show("答题记录", {"http": status, "count": history["count"]})

    status, bank = call("GET", f"/items?session_id={sid}")
    show("题库曝光情况", {"http": status, **bank})


if __name__ == "__main__":
    main()
