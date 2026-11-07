"""ID formats and scale settings."""
import pytest

from fraudnet.generate.config import DEFAULT_SEED, GeneratorConfig
from fraudnet.generate.ids import ID_PATTERNS, make_id, make_invoice_id


@pytest.mark.parametrize("entity, expected", [
    ("claim", "CLM-2026-000001"),
    ("incident", "INC-2026-000001"),
    ("provider", "PRV-000001"),
    ("investigation", "INVG-2026-000001"),
    ("claimant", "CLT-000001"),
    ("policy", "POL-000001"),
    ("payment", "PAY-2026-000001"),
    ("policy_event", "PEV-00000001"),
])
def test_id_formats(entity, expected):
    assert make_id(entity, 1) == expected
    assert ID_PATTERNS[entity].match(expected)


def test_invoice_id_uses_provider_number_and_its_own_counter():
    invoice_id = make_invoice_id("PRV-000042", 7)
    assert invoice_id == "INV-PRV-000042-000007"
    assert ID_PATTERNS["invoice"].match(invoice_id)


def test_invoice_id_rejects_bad_provider_id():
    with pytest.raises(ValueError):
        make_invoice_id("42", 1)


@pytest.mark.parametrize("number", [0, -1, 1_000_000])
def test_id_rejects_counter_that_does_not_fit(number):
    with pytest.raises(ValueError):
        make_id("claim", number)


def test_default_seed_matches_project_rule():
    assert GeneratorConfig().seed == DEFAULT_SEED == 20261022


@pytest.mark.parametrize("scale, claimants, providers, claims", [
    (0.1, 200, 50, 500),
    (1.0, 2_000, 500, 5_000),
    (2.0, 4_000, 1_000, 10_000),
])
def test_scale_counts(scale, claimants, providers, claims):
    config = GeneratorConfig(scale=scale)
    assert config.count("claimant") == claimants
    assert config.count("provider") == providers
    assert config.count("claim") == claims


@pytest.mark.parametrize("scale", [0, -1])
def test_scale_must_be_positive(scale):
    with pytest.raises(ValueError):
        GeneratorConfig(scale=scale)
