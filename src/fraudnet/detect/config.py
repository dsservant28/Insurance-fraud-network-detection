"""Load detector settings and fingerprint them for the run record."""
from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).with_name("detector.toml")


def load_config(path: Path = DEFAULT_CONFIG) -> tuple[dict, str]:
    """Return the settings and the SHA-256 of the file they came from."""
    raw = Path(path).read_bytes()
    return tomllib.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
