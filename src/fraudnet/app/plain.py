"""Plain-language reasons for the queue: one sentence an investigator can read at a glance.

Built only from the detector's own evidence for a network. Codes and IDs stay on the dossier page.
"""
from __future__ import annotations

from fraudnet.app.data import Network

# Things people can share: merged into one "share a, b and c" clause.
SHARED = {"SHARED_BANK": "a bank account", "SHARED_PHONE": "a phone number", "SHARED_EMAIL": "an email address",
          "SHARED_ADDRESS": "an address", "SHARED_CONTACT_PROVIDER": "a provider's own contact details"}
# Everything else is its own clause.
CLAUSE = {"DUPLICATE_INVOICE": "carry copies of the same invoice",
          "SIMILAR_NARRATIVE": "filed near-identical stories at one provider",
          "EARLY_CLAIM_PAIR": "claimed within days of their policies starting, at one provider",
          "SAME_INCIDENT": "claimed on the same incident"}
FAMILY_LABEL = {"IDENTITY": "Shared contact details", "BILLING": "Same invoice", "STORY": "Near-identical stories",
                "TIMING": "Early claims at one provider", "INCIDENT": "Same incident", "LOCATION": "Shared address",
                "PROVIDER": "Same provider", "SUPPORT": "Supporting facts"}
ORDER = ("SHARED_BANK", "SHARED_PHONE", "SHARED_EMAIL", "SHARED_CONTACT_PROVIDER", "SHARED_ADDRESS",
         "DUPLICATE_INVOICE", "SIMILAR_NARRATIVE", "EARLY_CLAIM_PAIR", "SAME_INCIDENT")


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _surnames_differ(network: Network) -> bool:
    surnames = [name.split()[-1].lower() for name in network.names.values() if name]
    return len(surnames) > 1 and len(set(surnames)) == len(surnames)


def reason(network: Network) -> str:
    """For example: "7 people with different surnames share a bank account and a phone number;
    3 of them also share an address." """
    total = len(network.members)
    groups: dict[int, list[str]] = {}
    for item in sorted(network.evidence, key=lambda item: ORDER.index(item["edge_type"]) if item["edge_type"] in ORDER else 99):
        groups.setdefault(len(item["claimants"]), []).append(item["edge_type"])
    clauses = []
    for count in sorted(groups, reverse=True):
        types = list(dict.fromkeys(groups[count]))
        shared = [SHARED[name] for name in types if name in SHARED]
        if "SHARED_BANK" in types and "SHARED_CONTACT_PROVIDER" in types:
            # One fact seen twice: the account they share is the provider's own.
            shared = ["a bank account that belongs to their provider"] + [
                SHARED[name] for name in types if name in SHARED and name not in ("SHARED_BANK", "SHARED_CONTACT_PROVIDER")]
        parts = ["share " + _join(shared)] if shared else []
        parts += [CLAUSE[name] for name in types if name in CLAUSE]
        if parts:
            clauses.append((count, _join(parts)))
    if not clauses:
        return f"{total} people linked by supporting evidence only."
    # A different surname matters only for shared contact details: it rules out a household.
    contact = any(item["edge_type"] in SHARED and item["edge_type"] != "SHARED_ADDRESS" for item in network.evidence)
    people = f"{total} people" + (" with different surnames" if contact and _surnames_differ(network) else "")
    count, text = clauses[0]
    sentence = f"{people} {text}" if count == total else f"{count} of {people} {text}"
    for count, text in clauses[1:]:
        sentence += f"; {'all of them' if count == total else f'{count} of them'} also {text}"
    return sentence + "."
