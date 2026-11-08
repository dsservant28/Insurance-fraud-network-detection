"""Load detector settings and fingerprint them for the run record."""
from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).with_name("detector.toml")


def load_config(path: Path = DEFAULT_CONFIG) -> tuple[dict, str]:
    """Return the settings and the SHA-256 of the file they came from.

    Line endings are normalised first, so a Windows checkout (CRLF) and a Linux host (LF) give the
    same fingerprint and therefore the same run ID.
    """
    raw = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return tomllib.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
