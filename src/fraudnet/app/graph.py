"""The live link graph: Cytoscape.js (vendored, MIT) inside an embedded HTML component (D-027).

Everything interactive happens in the browser: drag, zoom, click a person to light up their links,
click a link to read what it is. Text from the data is set with textContent, never as HTML.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fraudnet.app import theme
from fraudnet.app.data import Network

VENDOR = Path(__file__).resolve().parent / "vendor" / "cytoscape.min.js"

FAMILY_COLOUR = {"IDENTITY": "#F4A62A", "BILLING": "#FF6A3D", "STORY": "#C9A0F0", "TIMING": "#7FE0B5",
                 "INCIDENT": "#8FB2FF", "LOCATION": "#5BC6E8", "CONTEXT": "#5A6678"}
LINK_LABEL = {
    "SHARED_BANK": "Shared bank account", "SHARED_PHONE": "Shared phone number", "SHARED_EMAIL": "Shared email address",
    "SHARED_ADDRESS": "Shared address", "SHARED_CONTACT_PROVIDER": "Holds the provider's own contact details",
    "DUPLICATE_INVOICE": "Copies of the same invoice", "SIMILAR_NARRATIVE": "Near-identical story at one provider",
    "EARLY_CLAIM_PAIR": "Both claimed days after their policy started, at one provider", "SAME_INCIDENT": "Same incident",
    "USED_PROVIDER": "Used this provider (context only)",
}


@lru_cache(maxsize=1)
def _library() -> str:
    return VENDOR.read_text(encoding="utf-8")


def _register_note(recorded) -> str:
    if recorded == 0:
        return "missing from the recorded register"
    return "also in the recorded register" if recorded == 1 else "no recorded-register type"


def elements(network: Network) -> list[dict]:
    """Cytoscape elements. Each kind of evidence between one pair of people becomes one line (a bank
    account and a phone shared by the same two people are one 'shared contact details' line); clicking
    it lists every link behind it. Provider use is drawn as context only."""
    graph = network.detail.get("graph", {"nodes": [], "edges": []})
    nodes = [{"data": {"id": node["id"], "label": node["label"] if node["type"] == "CLAIMANT" else node["id"],
                       "kind": node["type"].lower()}} for node in graph["nodes"]]
    pairs: dict[tuple[str, str, str], list[dict]] = {}
    edges = []
    for edge in graph["edges"]:
        if not edge.get("evidence"):
            edges.append({"data": {"id": edge["id"], "source": edge["source"], "target": edge["target"], "family": "CONTEXT",
                                   "colour": FAMILY_COLOUR["CONTEXT"], "width": 1, "context": True,
                                   "label": LINK_LABEL.get(edge["edge_type"], edge["edge_type"]), "links": []}})
            continue
        source, target = sorted((edge["source"], edge["target"]))
        pairs.setdefault((source, target, edge.get("family", "CONTEXT")), []).append(edge)
    for (source, target, _), links in sorted(pairs.items()):
        links.sort(key=lambda link: -float(link.get("strength") or 0))
        top = links[0]
        family = top.get("family", "CONTEXT")
        edges.append({"data": {
            "id": "|".join(link["id"] for link in links), "source": source, "target": target, "family": family,
            "colour": FAMILY_COLOUR.get(family, FAMILY_COLOUR["CONTEXT"]), "context": False,
            "width": round(1.2 + 3.5 * float(top.get("strength") or 0), 2),
            "label": LINK_LABEL.get(top["edge_type"], top["edge_type"]),
            "missing": sum(1 for link in links if link.get("recorded") == 0),
            "links": [f"{LINK_LABEL.get(link['edge_type'], link['edge_type'])} · {float(link.get('strength') or 0):.3f} · "
                      f"{_register_note(link.get('recorded'))}"
                      + (f" · explained as {link['explanation']}" if link.get("explanation") else "")
                      + f" · {link['id']}" for link in links],
        }})
    return nodes + edges


def _json(value) -> str:
    return json.dumps(value).replace("</", "<\\/")


def html(network: Network, height: int = 560) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
html,body{{margin:0;height:100%;background:{theme.PANEL};font-family:Inter,system-ui,sans-serif;color:{theme.TEXT}}}
#wrap{{position:relative;height:{height}px}}
#cy{{position:absolute;inset:0}}
#info{{position:absolute;bottom:34px;right:12px;width:250px;padding:12px 14px;border-radius:10px;background:{theme.INK};
  border:1px solid {theme.LINE};font-size:13px;line-height:1.45;display:none}}
#info .k{{font-family:'JetBrains Mono',monospace;font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:{theme.FAINT}}}
#info .t{{font-weight:600;font-size:15px;margin:4px 0 6px}}
#info .r{{color:{theme.MUTED}}}
#hint{{position:absolute;left:12px;bottom:10px;font-size:12px;color:{theme.FAINT}}}
</style></head><body>
<div id="wrap"><div id="cy" role="img" aria-label="Link graph of {len(network.members)} people"></div><div id="info"></div>
<div id="hint">Click a person or a link · drag to move · scroll to zoom · click empty space to reset</div></div>
<script>{_library()}</script>
<script>
const els = {_json(elements(network))};
const cy = cytoscape({{
  container: document.getElementById('cy'), elements: els, wheelSensitivity: 0.25, minZoom: 0.3, maxZoom: 3,
  layout: {{name: 'concentric', concentric: n => n.data('kind') === 'provider' ? 2 : 1, levelWidth: () => 1,
            minNodeSpacing: 110, padding: 40, animate: false}},
  style: [
    {{selector: 'node', style: {{'background-color': '{theme.RAISED}', 'border-width': 3, 'border-color': '{theme.AMBER}',
      'width': 30, 'height': 30, 'label': 'data(label)', 'color': '{theme.TEXT}', 'font-size': 12, 'font-family': 'Inter, sans-serif',
      'text-valign': 'bottom', 'text-margin-y': 7, 'text-outline-color': '{theme.PANEL}', 'text-outline-width': 3}}}},
    {{selector: 'node[kind = "provider"]', style: {{'shape': 'hexagon', 'border-color': '{theme.CYAN}', 'width': 36, 'height': 36,
      'font-family': 'JetBrains Mono, monospace', 'font-size': 11, 'color': '#9BDDF1'}}}},
    {{selector: 'node[kind = "incident"]', style: {{'shape': 'round-diamond', 'border-color': '{FAMILY_COLOUR["INCIDENT"]}',
      'width': 30, 'height': 30, 'font-family': 'JetBrains Mono, monospace', 'font-size': 11, 'color': '#C3D3FF'}}}},
    {{selector: 'node[kind = "policy"], node[kind = "payment"]', style: {{'shape': 'round-rectangle', 'border-color': '#5A6678',
      'width': 24, 'height': 24, 'font-family': 'JetBrains Mono, monospace', 'font-size': 10, 'color': '{theme.MUTED}'}}}},
    {{selector: 'edge', style: {{'line-color': 'data(colour)', 'width': 'data(width)', 'curve-style': 'bezier',
      'control-point-step-size': 26, 'opacity': 0.75}}}},
    {{selector: 'edge[?context]', style: {{'line-style': 'dotted', 'opacity': 0.5}}}},
    {{selector: '.faded', style: {{'opacity': 0.08, 'text-opacity': 0.25}}}},
    {{selector: 'node.focus', style: {{'border-color': '{theme.TEXT}', 'border-width': 4}}}},
    {{selector: 'edge.focus', style: {{'opacity': 1, 'width': 'mapData(width, 1, 7, 4, 9)'}}}}
  ]
}});
if (cy.zoom() > 1.3) {{ cy.zoom(1.3); cy.center(); }}
const info = document.getElementById('info');
function line(cls, text) {{ const d = document.createElement('div'); d.className = cls; d.textContent = text; info.appendChild(d); }}
function show(kicker, title, rows) {{ info.replaceChildren(); line('k', kicker); line('t', title); rows.forEach(r => line('r', r)); info.style.display = 'block'; }}
function reset() {{ cy.elements().removeClass('faded focus'); info.style.display = 'none'; }}
cy.on('tap', e => {{ if (e.target === cy) reset(); }});
cy.on('tap', 'node', e => {{
  const n = e.target; reset();
  const near = n.closedNeighborhood();
  cy.elements().not(near).addClass('faded'); n.addClass('focus'); n.connectedEdges().addClass('focus');
  const people = n.neighborhood('node[kind = "claimant"]').length;
  const counts = {{}};
  n.connectedEdges('[!context]').forEach(ed => ed.data('links').forEach(l => {{ const k = l.split(' · ')[0]; counts[k] = (counts[k] || 0) + 1; }}));
  const rows = [people + (people === 1 ? ' person' : ' people') + ' linked directly'];
  Object.entries(counts).sort((a, b) => b[1] - a[1]).forEach(([l, c]) => rows.push(c + ' × ' + l));
  const kinds = {{provider: 'Provider · context only', incident: 'Incident · context only', claimant: 'Claimant · ' + n.id()}};
  show(kinds[n.data('kind')] || n.data('kind'), n.data('label'), rows);
}});
cy.on('tap', 'edge', e => {{
  const d = e.target.data(); reset();
  cy.elements().not(e.target.connectedNodes().union(e.target)).addClass('faded'); e.target.addClass('focus');
  const ends = e.target.connectedNodes().map(n => n.data('label')).join(' and ');
  if (d.context) {{ show('Context', d.label, [ends, 'Using the same provider never joins people by itself.']); return; }}
  show(d.links.length + (d.links.length === 1 ? ' link' : ' links') + ' between', ends, d.links);
}});
</script></body></html>"""
