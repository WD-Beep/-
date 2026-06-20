"""Quick collection smoke check — removed after run."""
from __future__ import annotations

import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
H = {"X-User-Id": "1", "X-Product-Id": "1", "Content-Type": "application/json"}


def mk(platform: str, keywords: list[str]) -> dict:
    return {
        "name": f"verify-{platform}-{int(time.time())}",
        "collection_mode": "discovery",
        "platform": platform,
        "platforms": [platform],
        "keywords": keywords,
        "discovery_limit": 3,
        "schedule_enabled": False,
        "email_enabled": False,
        "email_recipients": [],
    }


def snap(client: httpx.Client, tid: int) -> dict:
    t = client.get(f"{BASE}/api/collection-tasks/{tid}", headers=H).json()
    return {
        "id": tid,
        "status": t.get("status"),
        "stage": t.get("current_stage"),
        "discovered": t.get("discovered_count"),
        "deduped": t.get("deduped_count"),
        "hydration": f"{t.get('processed_count')}/{t.get('total_estimate')}",
        "inserted": t.get("inserted_count"),
        "error_message": t.get("error_message"),
        "last_error": t.get("last_error"),
        "recoverable": t.get("recoverable"),
        "summary": (t.get("status_summary") or "")[:160],
    }


def wait_until(client: httpx.Client, tid: int, max_s: int = 180) -> dict:
    out: dict[str, dict] = {}
    elapsed = 0
    while elapsed <= max_s:
        if elapsed > 0:
            time.sleep(30)
            elapsed += 30
        else:
            elapsed = 30
        label = f"{elapsed}s"
        s = snap(client, tid)
        out[label] = s
        print(label, json.dumps(s, ensure_ascii=False), flush=True)
        if s["status"] not in {"running", "pending", "draft"}:
            break
    return out


def main() -> int:
    with httpx.Client(timeout=120.0) as c:
        caps = c.get(f"{BASE}/api/collection-tasks/platform-capabilities", headers=H).json()
        print("CAPS", json.dumps({"max_running": caps.get("collection_max_running_tasks")}, ensure_ascii=False), flush=True)

        ig = c.post(f"{BASE}/api/collection-tasks", headers=H, json=mk("instagram", ["amazon home organization", "amazon home finds"])).json()
        tt = c.post(f"{BASE}/api/collection-tasks", headers=H, json=mk("tiktok", ["amazon finds", "amazon must haves"])).json()
        ig_run = c.post(f"{BASE}/api/collection-tasks/{ig['id']}/run", headers=H).json()
        tt_run = c.post(f"{BASE}/api/collection-tasks/{tt['id']}/run", headers=H).json()
        print("CONCURRENT_START", json.dumps({"ig": ig_run.get("status"), "tt": tt_run.get("status")}, ensure_ascii=False), flush=True)

        results: dict = {
            "instagram": wait_until(c, ig["id"]),
            "tiktok": wait_until(c, tt["id"]),
        }

        for platform, keywords in [
            ("youtube", ["amazon home organization", "amazon product review"]),
            ("facebook", ["amazon home decor", "amazon travel essentials"]),
        ]:
            created = c.post(f"{BASE}/api/collection-tasks", headers=H, json=mk(platform, keywords)).json()
            started = c.post(f"{BASE}/api/collection-tasks/{created['id']}/run", headers=H).json()
            print(
                f"{platform.upper()}_START",
                json.dumps({"id": created["id"], "status": started.get("status")}, ensure_ascii=False),
                flush=True,
            )
            results[platform] = wait_until(c, created["id"])

    print("DONE", json.dumps(results, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
