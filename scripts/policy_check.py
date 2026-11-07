"""Project policy checker.

Enforces three rules that come straight from the problem statement / project rules:

  R1  No label leakage: code under src/**/detect/ must not mention ground-truth names
      (ground_truth, is_fraud, ring_id, planted, issue_type). Only evaluation code may.
  R2  Determinism: generator code (src/**/generate/) must not use the global `random`
      module, global numpy.random functions, or the wall clock. Use a seeded
      numpy Generator: rng = np.random.default_rng(seed).
  R3  No secrets: no hard-coded API keys, passwords or DB URLs with passwords.

A line ending with "# policy: allow" is skipped (only with the owner's approval).

Usage:
  python scripts/policy_check.py          # scan the whole project, exit 1 on violations
  python scripts/policy_check.py --hook   # Claude Code PostToolUse hook: check the edited
                                          # file; exit 2 so Claude sees and fixes the problem
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCANNED_SUFFIXES = {".py", ".toml", ".yml", ".yaml", ".json", ".ini", ".cfg"}
SKIPPED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "data", "tests", ".claude", "prompts"}
ALLOW_MARKER = "# policy: allow"

LEAK_TERMS = re.compile(r"\b(ground_truth|is_fraud|ring_id|planted|issue_type)\b")

NONDET_RULES = [
    (re.compile(r"^\s*(import\s+random\b|from\s+random\s+import\b)"),
     "uses the global 'random' module; use the seeded numpy Generator passed in"),
    (re.compile(r"\b(np|numpy)\.random\.(?!default_rng\b|Generator\b|PCG64\b|SeedSequence\b)\w+"),
     "calls a global numpy.random function; use rng = np.random.default_rng(seed)"),
    (re.compile(r"\b(datetime\.now|datetime\.utcnow|date\.today|time\.time)\s*\("),
     "reads the wall clock; derive dates from a fixed reference date"),
]

SECRET_RULES = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "looks like an API key"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "looks like a GitHub token"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
     "hard-coded credential; read it from an environment variable"),
    (re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^:\s/@]+:[^@\s]+@"),
     "database URL with an embedded password; read it from an environment variable"),
]


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.path}:{self.line}: {self.message}"


def _in_src_area(rel_parts: tuple[str, ...], area: str) -> bool:
    return len(rel_parts) > 0 and rel_parts[0] == "src" and area in rel_parts[:-1]


def check_file(path: Path, root: Path = ROOT) -> list[Violation]:
    path = Path(path).resolve()
    root = Path(root).resolve()
    try:
        rel = path.relative_to(root)
    except ValueError:
        return []
    if path.suffix.lower() not in SCANNED_SUFFIXES or any(p in SKIPPED_DIRS for p in rel.parts[:-1]):
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    rel_str = rel.as_posix()
    is_detect = _in_src_area(rel.parts, "detect")
    is_generate = _in_src_area(rel.parts, "generate")
    found: list[Violation] = []

    for n, line in enumerate(lines, start=1):
        if line.rstrip().endswith(ALLOW_MARKER):
            continue
        if is_detect and path.suffix == ".py":
            m = LEAK_TERMS.search(line)
            if m:
                found.append(Violation("R1-leakage", rel_str, n,
                                       f"detector code mentions '{m.group(1)}'; detection must never use ground truth"))
        if is_generate and path.suffix == ".py":
            for pattern, msg in NONDET_RULES:
                if pattern.search(line):
                    found.append(Violation("R2-determinism", rel_str, n, msg))
        for pattern, msg in SECRET_RULES:
            if pattern.search(line):
                found.append(Violation("R3-secret", rel_str, n, msg))
    return found


def check_repo(root: Path = ROOT) -> list[Violation]:
    root = Path(root).resolve()
    found: list[Violation] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            found.extend(check_file(path, root))
    return found


def _run_hook() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        file_path = (data.get("tool_input") or {}).get("file_path")
        if not file_path:
            return 0
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ROOT)
        violations = check_file(Path(file_path), root)
    except Exception:
        return 0  # a broken checker must never block work
    if not violations:
        return 0
    print("Project policy violation(s) - fix before continuing:", file=sys.stderr)
    for v in violations:
        print(f"  {v}", file=sys.stderr)
    print("See CLAUDE.md section 2 (hard rules).", file=sys.stderr)
    return 2  # exit code 2: Claude Code shows this message to Claude


def main(argv: list[str]) -> int:
    if "--hook" in argv:
        return _run_hook()
    violations = check_repo(ROOT)
    if violations:
        print(f"{len(violations)} policy violation(s):")
        for v in violations:
            print(f"  {v}")
        return 1
    print("Policy check passed: no leakage, determinism or secret violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
