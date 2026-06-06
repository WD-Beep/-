from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET_SUFFIXES = {
    ".py",
    ".js",
    ".html",
    ".css",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".txt",
    ".csv",
    ".tsv",
}
SKIP_PARTS = {"__pycache__", ".idea"}
SKIP_PREFIXES = ("pytest-cache-files-",)
UTF8_BOM = b"\xef\xbb\xbf"


def should_skip(path: Path) -> bool:
    return any(part in SKIP_PARTS or part.startswith(SKIP_PREFIXES) for part in path.parts)


def scan_utf8_violations() -> tuple[list[Path], list[Path]]:
    non_utf8: list[Path] = []
    with_bom: list[Path] = []

    for file_path in ROOT.rglob("*"):
        if not file_path.is_file():
            continue

        rel = file_path.relative_to(ROOT)
        if should_skip(rel):
            continue
        if file_path.suffix.lower() not in TARGET_SUFFIXES:
            continue

        raw = file_path.read_bytes()
        if raw.startswith(UTF8_BOM):
            with_bom.append(rel)
            continue
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            non_utf8.append(rel)

    return non_utf8, with_bom


def main() -> int:
    non_utf8, with_bom = scan_utf8_violations()
    if not non_utf8 and not with_bom:
        print("UTF-8 check passed.")
        return 0

    print("UTF-8 check failed.")
    if non_utf8:
        print("Files that are not UTF-8:")
        for path in non_utf8:
            print(f"  - {path}")
    if with_bom:
        print("Files with UTF-8 BOM (not allowed):")
        for path in with_bom:
            print(f"  - {path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
