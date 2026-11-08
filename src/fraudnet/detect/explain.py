"""Plain-language explanations that cite concrete IDs, values and rates (ARCHITECTURE.md section 3.5)."""
from __future__ import annotations

import json

import pandas as pd

from fraudnet.detect.networks import Network, TypeEvidence

INDICATOR_CODES = {
    "SHARED_BANK": "SHARED_BANK", "SHARED_PHONE": "SHARED_PHONE", "SHARED_EMAIL": "SHARED_EMAIL",
    "SHARED_ADDRESS": "SHARED_ADDRESS", "SHARED_CONTACT_PROVIDER": "PROVIDER_SHARED_CONTACT",
    "DUPLICATE_INVOICE": "DUPLICATE_INVOICE", "SIMILAR_NARRATIVE": "REPEATED_NARRATIVE",
    "EARLY_CLAIM_PAIR": "CLAIM_BURST", "SAME_INCIDENT": "SHARED_INCIDENT",
}
FAMILY_NAMES = {"IDENTITY": "shared identity details", "BILLING": "duplicate billing", "STORY": "repeated stories",
                "TIMING": "early-claim timing", "INCIDENT": "a shared incident", "LOCATION": "a shared address"}
_CONTACT_NAMES = {"SHARED_BANK": "bank account", "SHARED_PHONE": "phone number", "SHARED_EMAIL": "email address"}


def id_list(values, limit: int = 5) -> str:
    items = sorted({str(value) for value in values})
    if len(items) > limit:
        return f"{', '.join(items[:limit])} and {len(items) - limit} more"
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def money(cents: float) -> str:
    return f"${cents / 100:,.2f}"


def severity(strength: float) -> str:
    return "HIGH" if strength >= 0.7 else "MEDIUM" if strength >= 0.4 else "LOW"


def _details(rows: pd.DataFrame) -> list[dict]:
    return [json.loads(text) for text in rows["detail_json"]]


def type_sentence(evidence: TypeEvidence, rarity: dict) -> str:
    rows, who = evidence.links, id_list(evidence.touched)
    details = _details(rows)
    kind = evidence.edge_type
    if kind in _CONTACT_NAMES:
        text = f"{who} share {_CONTACT_NAMES[kind]} {id_list(rows['matched_value'])}."
    elif kind == "SHARED_ADDRESS":
        text = f"{who} share the address {id_list(value.split(' / ')[0] for value in rows['matched_value'])}."
    elif kind == "SHARED_CONTACT_PROVIDER":
        fields = id_list(detail["field"].replace("_", " ") for detail in details)
        text = (f"{who} hold the {fields} of provider {id_list(rows['target_node_id'])} "
                f"({id_list(rows['matched_value'])}).")
    elif kind == "DUPLICATE_INVOICE":
        first = details[0]
        invoices = [invoice for detail in details for invoice in detail["invoices"]]
        text = (f"{who} were billed the same invoice {first['external_invoice_no']} from provider "
                f"{first['provider_id']} dated {first['invoice_date']} for {money(first['total_cents'])}, "
                f"on invoices {id_list(invoices)}.")
    elif kind == "SIMILAR_NARRATIVE":
        incidents = {incident for detail in details for incident in detail["incidents"]}
        cities = {city for detail in details for city in detail["cities"]}
        best = max(detail["similarity"] for detail in details)
        text = (f"{who} filed near-identical narratives (similarity up to {best:.2f}) on separate incidents "
                f"{id_list(incidents)} in {len(cities)} {'city' if len(cities) == 1 else 'cities'}, "
                f"all at provider {id_list(rows['matched_value'])}.")
    elif kind == "EARLY_CLAIM_PAIR":
        claims = {claim for detail in details for claim in detail["claims"]}
        latest = max(max(detail["days_after_policy_start"]) for detail in details)
        apart = max(detail["days_apart"] for detail in details)
        text = (f"{who} each claimed within {latest} days of their policy starting, at provider "
                f"{id_list(rows['matched_value'])}, on claims {id_list(claims)} no more than {apart} days apart.")
    else:  # SAME_INCIDENT
        parties = max(detail["parties"] for detail in details)
        text = f"{who} all claimed on incident {id_list(rows['matched_value'])} ({parties} claimants)."
    share = rarity.get(kind, {}).get("share")
    if share is not None and evidence.family != "INCIDENT":
        text += f" Only {share:.1%} of claimants have a link like this with no innocent explanation."
    return text


def support_sentence(code: str, evidence: dict) -> str:
    if code == "UNRECORDED_LINK":
        first = evidence["pairs"][0]
        return (f"{len(evidence['link_ids'])} of these links ({id_list(evidence['edge_types'])}) are missing from "
                f"the recorded relationship register, for example between {first[0]} and {first[1]}, and were "
                f"found only by rebuilding links from raw data.")
    if code == "PROVIDER_CONCENTRATION":
        return (f"{evidence['claimants_using']} of {evidence['members']} members use provider {evidence['provider_id']}, "
                f"which is not a busy provider.")
    return (f"Their invoices at provider {evidence['provider_id']} have a median of {evidence['median_ratio']:.1f}x "
            f"the peer median for the same incident and provider type.")


def network_summary(network: Network, rarity: dict, threshold: float) -> str:
    families = sorted(network.families.items(), key=lambda item: (-item[1], item[0]))
    lead = (f"{len(network.members)} claimants ({id_list(network.members)}) linked by "
            f"{id_list(FAMILY_NAMES[family] for family, _ in families)}.")
    sentences = []
    for family, _ in families:
        strongest = max((item for item in network.types.values() if item.family == family),
                        key=lambda item: (item.strength, item.edge_type))
        sentences.append(type_sentence(strongest, rarity))
    sentences += [support_sentence(item.code, item.evidence) for item in network.support]
    verdict = (f"Score {network.score:.2f} ({network.priority})." if network.flagged
               else f"Score {network.score:.2f}, below the flag threshold of {threshold:.2f}: "
                    f"not enough independent evidence to investigate.")
    return " ".join([lead, *sentences, verdict])


def cleared_sentence(code: str, rows: pd.DataFrame, settings: dict, provider_customers: dict) -> str:
    """Why a group of linked claimants is not suspicious."""
    explain = settings["explanations"]
    who = id_list(set(rows["source_node_id"]) | set(rows["target_node_id"]))
    details = _details(rows)
    if code == "HOUSEHOLD":
        surnames = {name for detail in details for name in detail["surnames"]}
        kinds = id_list(rows["edge_type"].str.replace("SHARED_", "").str.lower())
        return (f"{who} share the surname {id_list(name.title() for name in surnames)} and an address: a household. "
                f"Their shared {kinds} count at {explain['household_factor']}x strength.")
    if code == "BUILDING":
        residents = max(detail["residents_at_once"] for detail in details)
        address = rows["matched_value"].iloc[0].split(" / ")[0]
        return (f"{residents} residents live at {address} at the same time: a shared building. "
                f"Address links count at {explain['building_factor']}x strength.")
    if code == "COMMON_EVENT":
        cities = {city for detail in details for city in detail["cities"]}
        return (f"{who} filed similar narratives in {id_list(cities)} within {explain['common_event_days']} days: "
                f"one common event such as a storm. Story links count at {explain['common_event_factor']}x strength.")
    providers = sorted(set(rows["matched_value"]))
    counts = id_list(f"{provider} ({provider_customers.get(provider, 0)} customers)" for provider in providers)
    return (f"{who} are linked only through busy provider {counts}, where similar or early claims are expected "
            f"by chance. These links count at {explain['busy_provider_factor']}x strength.")
