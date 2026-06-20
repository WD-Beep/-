"""Temporary smoke verification for collection tasks — delete after run."""
from __future__ import annotations

import json
import time
from datetime import datetime

import httpx

BASE = "http://127.0.0.1:8000"
HEADERS = {"X-User-Id": "1", "X-Product-Id": "1", "Content-Type": "application/json"}

CASES = [
    ("instagram", ["amazon home organization", "amazon home finds"]),
    ("tiktok", ["amazon finds", "amazon must haves"]),
    ("youtube", ["amazon home organization", "amazon product review"]),
    ("facebook", ["amazon home decor", "amazon travel essentials"]),
]


def create_and_run(client: httpx.Client, platform: str, keywords: list[str]) -> dict:
    payload = {
        "name": f"smoke-{platform}-{int(time.time())}",
        "collection_mode": "discovery",
        "platform": platform,
        "platforms": [platform],
        "keywords": keywords,
        "discovery_limit": 3,
        "schedule_enabled": False,
        "email_enabled": False,
        "email_recipients": [],
    }
    created = client.post(f"{BASE}/api/collection-tasks", headers=HEADERS, json=payload).json()
    task_id = created["id"]
    started = client.post(f"{BASE}/api/collection-tasks/{task_id}/run", headers=HEADERS).json()
    record = {
        "platform": platform,
        "task_id": task_id,
        "create": {"status": created.get("status"), "id": task_id},
        "start": {
            "status": started.get("status"),
            "error_message": started.get("error_message"),
            "last_error": started.get("last_error"),
        },
        "snapshots": {},
    }
    for wait in (30, 60, 180, 300):
        time.sleep(wait if not record["snapshots"] else wait - max(int(k) for k in record["snapshots"]))
        task = client.get(f"{BASE}/api/collection-tasks/{task_id}", headers=HEADERS).json()
        record["snapshots"][str(wait)] = {
            "status": task.get("status"),
            "current_stage": task.get("current_stage"),
            "discovered_count": task.get("discovered_count"),
            "deduped_count": task.get("deduped_count"),
            "profile_fetched_count": task.get("profile_fetched_count"),
            "inserted_count": task.get("inserted_count"),
            "error_message": task.get("error_message"),
            "last_error": task.get("last_error"),
            "status_summary": task.get("status_summary"),
            "recoverable": task.get("recoverable"),
        }
        if task.get("status") not in {"running", "pending", "draft"}:
            record["final"] = record["snapshots"][str(wait)]
            break
    else:
        record["final"] = record["snapshots"][str(max(int(k) for k in record["snapshots"]))] 
    return record


def main() -> None:
    results = []
    with httpx.Client(timeout=120.0) as client:
        caps = client.get(f"{BASE}/api/collection-tasks/platform-capabilities", headers=HEADERS).json()
        print("capabilities:", json.dumps({
            "collection_max_running_tasks": caps.get("collection_max_running_tasks"),
        }, ensure_ascii=False))
        # Batch 1: instagram + tiktok concurrent
        ig_kw = CASES[0][1]
        tt_kw = CASES[1][1]
        ig_payload = {
            "name": f"smoke-ig-{int(time.time())}",
            "collection_mode": "discovery",
            "platform": "instagram",
            "platforms": ["instagram"],
            "keywords": ig_kw,
            "discovery_limit": 3,
            "schedule_enabled": False,
            "email_enabled": False,
            "email_recipients": [],
        }
        tt_payload = dict(ig_payload)
        tt_payload.update({"name": f"smoke-tt-{int(time.time())}", "platform": "tiktok", "platforms": ["tiktok"], "keywords": tt_kw})
        ig = client.post(f"{BASE}/api/collection-tasks", headers=HEADERS, json=ig_payload).json()
        tt = client.post(f"{BASE}/api/collection-tasks", headers=HEADERS, json=tt_payload).json()
        ig_start = client.post(f"{BASE}/api/collection-tasks/{ig['id']}/run", headers=HEADERS).json()
        tt_start = client.post(f"{BASE}/api/collection-tasks/{tt['id']}/run", headers=HEADERS).json()
        results.append({"batch": "ig+tt", "create": [ig["id"], tt["id"]], "start_status": [ig_start.get("status"), tt_start.get("status")]})
        for wait in (30, 60, 180, 300):
            time.sleep(30 if wait == 30 else 30)
            snap = {}
            for tid in (ig["id"], tt["id"]):
                t = client.get(f"{BASE}/api/collection-tasks/{tid}", headers=HEADERS).json()
                snap[tid] = {
                    "status": t.get("status"),
                    "inserted": t.get("inserted_count"),
                    "error_message": t.get("error_message"),
                    "last_error": t.get("last_error"),
                    "recoverable": t.get("recoverable"),
                    "stage": t.get("current_stage"),
                    "discovered": t.get("discovered_count"),
                    "hydration": f"{t.get('processed_count')}/{t.get('total_estimate')}",
                }
            results[-1][f"t{wait}"] = snap
            if all(snap[t]["status"] not in {"running"} for t in snap):
                break
        # Batch 2: youtube + facebook
        for platform, keywords in CASES[2:]:
            results.append(create_and_run(client, platform, keywords))
    out = {"at": datetime.now().isoformat(), "results": results}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
