"""Run the generator stages in a fixed order with one seeded random generator."""
from __future__ import annotations

import numpy as np
import pandas as pd

from fraudnet.generate.config import GeneratorConfig
from fraudnet.generate.finalize import finalize
from fraudnet.generate.lifecycle import build_lifecycle
from fraudnet.generate.master import build_master
from fraudnet.generate.transactions import build_transaction_source


def generate(config: GeneratorConfig) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(config.seed)
    master = build_master(config, rng)
    source = build_transaction_source(config, rng, master)
    derived = build_lifecycle(rng, master, source)
    return finalize(master, derived, rng)
