"""Run the generator stages in a fixed order with one seeded random generator."""
from __future__ import annotations

import numpy as np
import pandas as pd

from fraudnet.generate.config import GeneratorConfig
from fraudnet.generate.finalize import finalize
from fraudnet.generate.ground_truth import build_labels
from fraudnet.generate.lifecycle import build_lifecycle
from fraudnet.generate.master import build_master
from fraudnet.generate.plant import plan_planting
from fraudnet.generate.transactions import build_transaction_source


def generate_with_labels(config: GeneratorConfig) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Return the input tables and, separately, the hidden labels."""
    rng = np.random.default_rng(config.seed)
    master = build_master(config, rng)
    plan = plan_planting(config, rng, master)
    source = build_transaction_source(config, rng, master, plan)
    derived = build_lifecycle(rng, master, source)
    tables, ids = finalize(master, derived, rng)
    planted_claims = derived.claim[derived.claim["plan_group"].notna()]
    claim_groups = {ids["claim"][int(key)]: int(group)
                    for key, group in zip(planted_claims["claim_key"], planted_claims["plan_group"])}
    return tables, build_labels(plan, claim_groups, ids)


def generate(config: GeneratorConfig) -> dict[str, pd.DataFrame]:
    return generate_with_labels(config)[0]
