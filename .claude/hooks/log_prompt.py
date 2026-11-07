"""Claude Code UserPromptSubmit hook: append every prompt to prompts/claude_code_prompts.md.

Why: YottaFlex requires the full prompt history. This records each prompt exactly as typed,
with a running number, IST timestamp and session id. The only automatic change is that
strings that look like secrets (API keys, tokens) are replaced with [REDACTED: secret].

Safety: this hook never blocks a prompt and prints nothing (stdout from this hook would be
added to Claude's context). Any error is swallowed so your work is never interrupted.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
LOG_RELATIVE = Path("prompts") / "claude_code_prompts.md"

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),                      # OpenAI / Anthropic style keys
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),                   # GitHub tokens
    re.compile(r"(?i)(password|passwd|api[_-]?key|secret|token)(\s*[:=]\s*)\S+"),
]

HEADER = """# Claude Code prompt history

Auto-captured by `.claude/hooks/log_prompt.py` (UserPromptSubmit hook).
Prompts are recorded exactly as typed; only secret-looking strings are replaced with `[REDACTED: secret]`.
Times are IST (UTC+05:30).
"""


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED: secret]", text)
        else:
            text = pattern.sub("[REDACTED: secret]", text)
    return text


def main() -> None:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        prompt = data.get("prompt", "")
        if not prompt.strip():
            return
        session = data.get("session_id", "unknown")
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ".")
        log_path = root / LOG_RELATIVE
        log_path.parent.mkdir(parents=True, exist_ok=True)

        existing = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        number = existing.count("\n## Prompt ") + 1
        stamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        entry = (
            f"\n## Prompt {number:03d}\n"
            f"- Time: {stamp}\n"
            f"- Session: `{session}`\n\n"
            f"````text\n{redact(prompt).rstrip()}\n````\n"
        )
        with log_path.open("a", encoding="utf-8", newline="\n") as f:
            if not existing:
                f.write(HEADER)
            f.write(entry)
    except Exception:
        pass  # never interrupt the user's work


if __name__ == "__main__":
    main()
    sys.exit(0)
