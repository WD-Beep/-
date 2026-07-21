# 文件说明：后端维护脚本，用于检查、迁移、验证或批处理任务；当前文件：test youtube collect5 api
"""通过 HTTP API 创建并运行 YouTube 采集，轮询至完成。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/collection-tasks"
POLL_SECONDS = 15
MAX_WAIT_SECONDS = 900


def request(method: str, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main() -> int:
    payload = {
        "name": "Agent YouTube 5条入库测试",
        "collection_mode": "category_discovery",
        "platform": "youtube",
        "keywords": [
            "AmazonFinds",
            "amazon finds creator",
            "amazon home finds",
            "amazon must haves",
        ],
        "country": "US",
        "category": "AmazonFinds",
        "discovery_limit": 5,
        "min_engagement_rate": 0.5,
        "min_followers_count": 3000,
        "filter_include_keywords": [
            "amazon",
            "finds",
            "must haves",
            "must-haves",
            "storefront",
            "home",
            "deals",
            "recommendations",
            "affiliate",
            "creator",
            "influencer",
            "haul",
            "review",
            "ltk",
            "link in bio",
        ],
        "filter_exclude_keywords": [
            "wholesale",
            "official store",
            "our shop",
            "customer service",
            "fan page",
            "coupon only",
            "news account",
        ],
    }

    task = request("POST", BASE, payload)
    task_id = task["id"]
    print(f"created task_id={task_id}")

    try:
        kickoff = request("POST", f"{BASE}/{task_id}/run")
        print(f"started status={kickoff.get('status')} summary={kickoff.get('status_summary')!r}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        print(f"run failed http={exc.code} body={body}")
        return 1

    deadline = time.time() + MAX_WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        current = request("GET", f"{BASE}/{task_id}")
        status = current.get("status")
        inserted = current.get("inserted_count") or 0
        target = current.get("discovery_limit") or 5
        print(
            f"poll status={status} inserted={inserted}/{target} "
            f"discovered={current.get('discovered_count')} filtered={current.get('filtered_out_count')}"
        )
        if status != "running":
            print("--- final ---")
            print(json.dumps(
                {
                    "status": status,
                    "inserted_count": inserted,
                    "discovery_limit": target,
                    "discovered_count": current.get("discovered_count"),
                    "deduped_count": current.get("deduped_count"),
                    "profile_fetched_count": current.get("profile_fetched_count"),
                    "filtered_out_count": current.get("filtered_out_count"),
                    "status_summary": current.get("status_summary"),
                    "last_error": current.get("last_error"),
                },
                ensure_ascii=False,
                indent=2,
            ))
            return 0 if inserted >= target else 2

    print("timeout waiting for task completion")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
