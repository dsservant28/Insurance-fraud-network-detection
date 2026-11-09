"""First start on a host: build the dataset the app reads (D-018).

`data/output` is not in git, so a fresh deployment builds it once: generate, validate, detect and open the
demo cases (the evaluation pages read committed summaries, so that stage is skipped). The build goes into a
temporary folder that is renamed into place only when complete, so a half-built dataset is never read.
"""
from __future__ import annotations

import gc
import os
import shutil
from pathlib import Path

from fraudnet.app.data import DATA_ENV, REPO
from fraudnet.generate.config import DEFAULT_SEED
from fraudnet.run import run

OUTPUT = REPO / "data" / "output"


def ready(folder: Path) -> bool:
    return (folder / "detect" / "network.csv").exists() and (folder / "fraudnet.db").exists()


def build(target: Path = OUTPUT, scale: float = 1.0) -> bool:
    """Build the dataset into `target` unless it is already there. Returns True when it built one."""
    if ready(target):
        return False
    staging = target.parent / f".build-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    run(DEFAULT_SEED, scale, staging, demo_cases=True, evaluate=False, say=lambda *_: None)
    gc.collect()  # release any database handles still open, so Windows allows the rename
    try:
        os.replace(staging, target)  # atomic on one file system
    except OSError:
        if ready(target):  # another process finished first: keep theirs
            shutil.rmtree(staging, ignore_errors=True)
        else:  # the rename itself was refused: move the files instead, never discard a good build
            shutil.move(str(staging), str(target))
    return True


def needed() -> bool:
    return not os.environ.get(DATA_ENV) and not ready(OUTPUT)
