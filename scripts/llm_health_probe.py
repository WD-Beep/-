#!/usr/bin/env python3
"""Optional live LLM API health probe (manual use only; not part of pytest).

Reads ``.env`` from the project root via ``kimi_client.get_kimi_config()``.
Never prints the full API key.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kimi_client import build_llm_health_report  # noqa: E402


def _print_human(report: dict) -> None:
    print(f"provider: {report.get('provider', '')}")
    print(f"model: {report.get('model', '')}")
    print(f"endpoint: {report.get('endpoint', '')}")
    print(f"api_key_source: {report.get('api_key_source', '')}")
    print(f"api_key_masked: {report.get('api_key_masked', '')}")
    print(f"status: {report.get('status', '')}")
    err = str(report.get("error") or "").strip()
    if err:
        print(f"error: {err}")
    ms = report.get("probe_latency_ms")
    if ms:
        print(f"probe_latency_ms: {ms}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional live LLM API health probe")
    parser.add_argument(
        "--config-only",
        action="store_true",
        help="Read config only; do not call the remote API",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of plain text")
    args = parser.parse_args()
    report = build_llm_health_report(live_probe=not args.config_only)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    if report.get("status") in {"ok", "config_only"}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
