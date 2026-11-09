"""The live link graph: Cytoscape.js (vendored, MIT) inside an embedded HTML component.

People sit evenly on a ring, providers and incidents in the middle as context. Each kind of evidence
between one pair of people is one line: the strongest kind is straight, any other kind curves outward.
Everything interactive happens in the browser: drag, zoom, click a person to light up their links,
click a line to read what it is. Text from the data is set with textContent, never as HTML.
"""
from __future__ import annotations

import json
import math
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
RING_SPACING = 130   # model units between neighbouring people on the ring
BEND_STEP = 40       # how far each extra kind of evidence between one pair curves outward


@lru_cache(maxsize=1)
def _library() -> str:
    return VENDOR.read_text(encoding="utf-8")


def _register_note(recorded) -> str:
    if recorded == 0:
        return "missing from the recorded register"
    return "also in the recorded register" if recorded == 1 else "no recorded-register type"


def ring_radius(people: int) -> float:
    return max(190.0, RING_SPACING * people / (2 * math.pi))


def _positions(network: Network, nodes: list[dict]) -> dict[str, dict]:
    """People evenly on a ring, starting at the top and going clockwise; context nodes in the middle."""
    claimants = {node["id"] for node in nodes if node["type"] == "CLAIMANT"}
    people = [m for m in network.members if m in claimants] + sorted(claimants - set(network.members))
    radius = ring_radius(len(people))
    spots = {}
    for i, node_id in enumerate(people):
        angle = -math.pi / 2 + 2 * math.pi * i / len(people)
        spots[node_id] = {"x": round(radius * math.cos(angle), 1), "y": round(radius * math.sin(angle), 1)}
    middle = [node["id"] for node in nodes if node["type"] != "CLAIMANT"]
    for i, node_id in enumerate(middle):
        angle = -math.pi / 2 + 2 * math.pi * i / len(middle)
        spread = 0 if len(middle) == 1 else 70
        spots[node_id] = {"x": round(spread * math.cos(angle), 1), "y": round(spread * math.sin(angle), 1)}
    return spots


def elements(network: Network) -> list[dict]:
    """Cytoscape elements with fixed ring positions. Clicking a line lists every link behind it."""
    graph = network.detail.get("graph", {"nodes": [], "edges": []})
    spots = _positions(network, graph["nodes"])
    nodes = [{"data": {"id": node["id"], "label": node["label"] if node["type"] == "CLAIMANT" else node["id"],
                       "kind": node["type"].lower()}, "position": spots[node["id"]]} for node in graph["nodes"]]
    pairs: dict[tuple[str, str], dict[str, list[dict]]] = {}
    edges = []
    for edge in graph["edges"]:
        if not edge.get("evidence"):
            edges.append({"data": {"id": edge["id"], "source": edge["source"], "target": edge["target"], "family": "CONTEXT",
                                   "colour": FAMILY_COLOUR["CONTEXT"], "width": 1.2, "context": True, "bend": 0,
                                   "label": LINK_LABEL.get(edge["edge_type"], edge["edge_type"]), "links": []}})
            continue
        source, target = sorted((edge["source"], edge["target"]))
        pairs.setdefault((source, target), {}).setdefault(edge.get("family", "CONTEXT"), []).append(edge)
    for (source, target), families in sorted(pairs.items()):
        ranked = sorted(families.items(), key=lambda item: -max(float(link.get("strength") or 0) for link in item[1]))
        for position, (family, links) in enumerate(ranked):
            links.sort(key=lambda link: -float(link.get("strength") or 0))
            top = links[0]
            edges.append({"data": {
                "id": "|".join(link["id"] for link in links), "source": source, "target": target, "family": family,
                "colour": FAMILY_COLOUR.get(family, FAMILY_COLOUR["CONTEXT"]), "context": False,
                "width": round(1.8 + 1.6 * float(top.get("strength") or 0), 2), "bend": BEND_STEP * position,
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


def html(network: Network, height: int = 620) -> str:
    graph = network.detail.get("graph", {"nodes": []})
    radius = ring_radius(sum(1 for node in graph["nodes"] if node["type"] == "CLAIMANT"))
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
html,body{{margin:0;height:100%;background:{theme.PANEL};font-family:Inter,system-ui,sans-serif;color:{theme.TEXT};overflow:hidden}}
#wrap{{position:relative;height:{height}px}}
#ring{{position:absolute;border-radius:50%;border:1.5px dotted #2A3442;pointer-events:none}}
#cy{{position:absolute;inset:0}}
#labels{{position:absolute;inset:0;pointer-events:none}}
.lab{{position:absolute;white-space:nowrap;line-height:1.3}}
.lab .n{{font-weight:600;font-size:15px;color:{theme.TEXT};text-shadow:0 0 4px {theme.PANEL},0 0 8px {theme.PANEL}}}
.lab .i{{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;color:{theme.MUTED};text-shadow:0 0 4px {theme.PANEL}}}
.lab.mid{{text-align:center}}
.lab.mid .n{{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:13px;color:#9BDDF1}}
#info{{position:absolute;top:12px;left:12px;width:250px;padding:12px 14px;border-radius:10px;background:{theme.INK};
  border:1px solid {theme.LINE};font-size:13px;line-height:1.45;display:none}}
#info .k{{font-family:'JetBrains Mono',monospace;font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:{theme.FAINT}}}
#info .t{{font-weight:600;font-size:15px;margin:4px 0 6px}}
#info .r{{color:{theme.MUTED}}}
#hint{{position:absolute;left:12px;bottom:10px;font-size:12px;color:{theme.FAINT}}}
</style></head><body>
<div id="wrap"><div id="ring"></div><div id="cy" role="img" aria-label="Link graph of {len(network.members)} people"></div>
<div id="labels"></div><div id="info"></div>
<div id="hint">Click a person or a line · drag to move · scroll to zoom · click empty space to reset</div></div>
<script>{_library()}</script>
<script>
const els = {_json(elements(network))};
const RADIUS = {radius:.1f};
const cy = cytoscape({{
  container: document.getElementById('cy'), elements: els, wheelSensitivity: 0.25, minZoom: 0.3, maxZoom: 3,
  layout: {{name: 'preset', fit: false}},
  style: [
    {{selector: 'node', style: {{'background-color': '#1A140A', 'border-width': 3, 'border-color': '{theme.AMBER}', 'width': 34, 'height': 34}}}},
    {{selector: 'node[kind = "provider"]', style: {{'shape': 'hexagon', 'background-color': '#0E2A36', 'border-color': '{theme.CYAN}',
      'width': 64, 'height': 58}}}},
    {{selector: 'node[kind = "incident"]', style: {{'shape': 'round-diamond', 'background-color': '#141C33',
      'border-color': '{FAMILY_COLOUR["INCIDENT"]}', 'width': 40, 'height': 40}}}},
    {{selector: 'node[kind = "policy"], node[kind = "payment"]', style: {{'shape': 'round-rectangle', 'border-color': '#5A6678',
      'background-color': '{theme.RAISED}', 'width': 28, 'height': 28}}}},
    {{selector: 'edge', style: {{'line-color': 'data(colour)', 'width': 'data(width)', 'curve-style': 'straight', 'opacity': 0.5}}}},
    {{selector: 'edge[family != "IDENTITY"]', style: {{'opacity': 0.9}}}},
    {{selector: 'edge[bend > 0]', style: {{'curve-style': 'unbundled-bezier', 'control-point-distances': 'data(bend)',
      'control-point-weights': 0.5, 'opacity': 0.95, 'width': 3.5}}}},
    {{selector: 'edge[?context]', style: {{'line-style': 'dashed', 'line-dash-pattern': [5, 5], 'opacity': 0.75, 'width': 1.2}}}},
    {{selector: '.faded', style: {{'opacity': 0.07}}}},
    {{selector: 'node.focus', style: {{'border-color': '{theme.TEXT}', 'border-width': 4}}}},
    {{selector: 'edge.focus', style: {{'opacity': 1, 'width': 4.5}}}}
  ]
}});
// Fill the frame: the ring plus room for a name label on each side.
const W = cy.width(), H = cy.height();
cy.zoom(Math.max(0.3, Math.min((W - 2 * 125) / (2 * RADIUS + 40), (H - 2 * 46) / (2 * RADIUS + 40), 1.4)));
cy.pan({{x: W / 2, y: H / 2 - 8}});
// Curved lines must bend away from the middle of the ring. Check each one once it is drawn and flip it if needed.
cy.one('render', () => {{
  const p = cy.pan();
  cy.edges('[bend > 0]').forEach(e => {{
    const cps = e.controlPoints();
    if (!cps || !cps.length) return;
    const s = e.source().renderedPosition(), t = e.target().renderedPosition();
    const mid = {{x: (s.x + t.x) / 2, y: (s.y + t.y) / 2}};
    const cp = {{x: cps[0].x * cy.zoom() + p.x, y: cps[0].y * cy.zoom() + p.y}};
    if (Math.hypot(cp.x - p.x, cp.y - p.y) < Math.hypot(mid.x - p.x, mid.y - p.y)) {{
      e.style('control-point-distances', -e.data('bend'));
    }}
  }});
}});
const ring = document.getElementById('ring'), labels = document.getElementById('labels'), tags = {{}};
cy.nodes().forEach(n => {{
  const kind = n.data('kind'), el = document.createElement('div');
  el.className = 'lab' + (kind === 'claimant' ? '' : ' mid');
  const a = document.createElement('div'); a.className = 'n'; a.textContent = n.data('label');
  const b = document.createElement('div'); b.className = 'i';
  b.textContent = kind === 'claimant' ? n.id() : 'context, not evidence';
  el.appendChild(a); el.appendChild(b); labels.appendChild(el); tags[n.id()] = el;
}});
function place() {{
  const z = cy.zoom(), p = cy.pan();
  ring.style.left = (p.x - RADIUS * z) + 'px'; ring.style.top = (p.y - RADIUS * z) + 'px';
  ring.style.width = ring.style.height = (2 * RADIUS * z) + 'px';
  cy.nodes().forEach(n => {{
    const el = tags[n.id()], r = n.renderedPosition(), half = n.renderedOuterWidth() / 2;
    if (n.data('kind') !== 'claimant') {{
      el.style.left = r.x + 'px'; el.style.top = (r.y + half + 4) + 'px'; el.style.transform = 'translateX(-50%)';
    }} else if (r.x >= p.x - 1) {{
      el.style.left = (r.x + half + 10) + 'px'; el.style.top = r.y + 'px'; el.style.transform = 'translateY(-50%)'; el.style.textAlign = 'left';
    }} else {{
      el.style.left = (r.x - half - 10) + 'px'; el.style.top = r.y + 'px'; el.style.transform = 'translate(-100%, -50%)'; el.style.textAlign = 'right';
    }}
    el.style.opacity = n.hasClass('faded') ? 0.2 : 1;
  }});
}}
cy.on('render', place); place();
const info = document.getElementById('info');
function line(cls, text) {{ const d = document.createElement('div'); d.className = cls; d.textContent = text; info.appendChild(d); }}
function show(kicker, title, rows) {{ info.replaceChildren(); line('k', kicker); line('t', title); rows.forEach(r => line('r', r)); info.style.display = 'block'; }}
function reset() {{ cy.elements().removeClass('faded focus'); info.style.display = 'none'; }}
cy.on('tap', e => {{ if (e.target === cy) reset(); }});
cy.on('tap', 'node', e => {{
  const n = e.target; reset();
  cy.elements().not(n.closedNeighborhood()).addClass('faded'); n.addClass('focus'); n.connectedEdges().addClass('focus');
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
