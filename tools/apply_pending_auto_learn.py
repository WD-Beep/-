from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.knowledge_pending_apply import apply_pending_auto_learn  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply pending auto-learn rows into price_kb.xlsx")
    parser.add_argument("--pending-file", type=Path, default=None)
    parser.add_argument("--kb-path", type=Path, default=None)
    parser.add_argument("--min-confidence", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-reload", action="store_true")
    args = parser.parse_args()

    result = apply_pending_auto_learn(
        pending_file=args.pending_file,
        kb_path=args.kb_path,
        min_confidence=args.min_confidence,
        dry_run=args.dry_run,
        reload_after_write=not args.skip_reload,
    )
    print(
        "pending_auto_learn "
        f"total={result.total} applied={result.applied} "
        f"existing={result.skipped_existing} invalid={result.invalid} "
        f"failed={result.failed} kept={result.kept}"
    )
    for err in result.errors:
        print(f"warning: {err}")
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
