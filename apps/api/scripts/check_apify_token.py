"""检查 .env 中的 APIFY_TOKEN 是否有效。"""

from __future__ import annotations

import httpx

from app.core.config import settings


def main() -> None:
    token = settings.apify_token.strip()
    if not token:
        print("STATUS=missing")
        return

    fingerprint = f"{token[:12]}...{token[-4:]}" if len(token) > 20 else "(too short)"
    print(f"token_fingerprint={fingerprint}")
    print(f"token_length={len(token)}")
    print(f"configured={settings.is_apify_configured}")

    try:
        response = httpx.get(
            "https://api.apify.com/v2/users/me",
            params={"token": token},
            timeout=15.0,
        )
        print(f"apify_http={response.status_code}")
        if response.status_code == 200:
            data = response.json().get("data", {})
            print(f"apify_user={data.get('username')}")
            plan = data.get("plan")
            plan_id = plan.get("id") if isinstance(plan, dict) else plan
            print(f"apify_plan={plan_id}")
            print("STATUS=valid")
            return
        print(f"apify_error={response.text[:300]}")
        print("STATUS=invalid")
    except Exception as exc:
        print(f"apify_exception={exc}")
        print("STATUS=network_error")


if __name__ == "__main__":
    main()
