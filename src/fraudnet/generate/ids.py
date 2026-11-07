"""ID formats from the brief and docs/DECISIONS.md (D-004, D-005)."""
from __future__ import annotations

import re

_FORMATS = {
    "claimant": ("CLT-", 6),
    "contact": ("CON-", 6),
    "policy": ("POL-", 6),
    "provider": ("PRV-", 6),
    "incident": ("INC-2026-", 6),
    "claim": ("CLM-2026-", 6),
    "payment": ("PAY-2026-", 6),
    "investigation": ("INVG-2026-", 6),
    "edge": ("EDG-", 6),
    "indicator": ("FIN-", 6),
    "network": ("NET-", 6),
    "exception": ("EXC-", 6),
    "label": ("GT-", 6),
    "policy_event": ("PEV-", 8),
    "claim_event": ("CEV-", 8),
    "invoice_event": ("IEV-", 8),
    "payment_event": ("YEV-", 8),
    "investigation_event": ("VEV-", 8),
}

ID_PATTERNS = {
    entity: re.compile(rf"^{re.escape(prefix)}\d{{{width}}}$")
    for entity, (prefix, width) in _FORMATS.items()
}
ID_PATTERNS["invoice"] = re.compile(r"^INV-PRV-\d{6}-\d{6}$")


def _pad(number: int, width: int) -> str:
    if number < 1 or number >= 10**width:
        raise ValueError(f"counter {number} does not fit in {width} digits")
    return f"{number:0{width}d}"


def make_id(entity: str, number: int) -> str:
    """Build an ID such as make_id("claim", 1) -> CLM-2026-000001."""
    prefix, width = _FORMATS[entity]
    return f"{prefix}{_pad(number, width)}"


def make_invoice_id(provider_id: str, counter: int) -> str:
    """Build an invoice ID from a provider ID and that provider's own counter."""
    if not ID_PATTERNS["provider"].match(provider_id):
        raise ValueError(f"not a provider ID: {provider_id}")
    return f"INV-{provider_id}-{_pad(counter, 6)}"
