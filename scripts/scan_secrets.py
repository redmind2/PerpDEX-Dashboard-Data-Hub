from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


SECRET_RE = re.compile(
    r"(api[_-]?key|api[_-]?secret|private[_-]?key|secret[_-]?key|"
    r"mnemonic|seed phrase|password|bearer\s+[A-Za-z0-9._~+/=-]+|"
    r"github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9_]+|sk-[A-Za-z0-9]{20,}|"
    r"0x[a-fA-F0-9]{64})",
    re.IGNORECASE,
)

SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".agents", ".codex"}
SKIP_FILES = {".env.example", "pre-commit", "scan_secrets.py"}
SKIP_SUFFIXES = {".pyc", ".sqlite", ".db", ".log"}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def should_scan(path: Path) -> bool:
    if path.name in SKIP_FILES:
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    return path.suffix.lower() not in SKIP_SUFFIXES


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        if not should_scan(path) or not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if SECRET_RE.search(line):
                findings.append(f"{path}:{line_no}: {line.strip()[:160]}")

    if findings:
        print("Potential secrets found:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("No tracked secret-like content found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
