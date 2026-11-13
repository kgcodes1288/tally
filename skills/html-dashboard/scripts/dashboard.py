#!/usr/bin/env python3
"""Build a polished, self-contained, offline HTML dashboard from a JSON spec.

  dashboard.py spec.json --out /workspace/out/dashboard.html

Spec (all keys optional except title):
{
  "title": "...", "subtitle": "...", "as_of": "FY2025, period 12",
  "kpis":   [{"label": "Unlinked obligations", "value": 52703187.65, "unit": "$", "note": "0.23% of File C",
              "status": "good|warning|critical"}],
  "charts": [{"title": "...", "subtitle": "...", "type": "bar|hbar|line|grouped_bar|stacked_bar|scatter",
              "data": "/workspace/data/x.csv"  OR  {"columns": [...], "rows": [[...], ...]},
              "x": "col", "y": "col" or ["col", "col"], "series": "col (long format, optional)",
              "unit": "$|%|hrs|count", "highlight": "x value to emphasise", "sort": "desc|asc", "wide": true}],
  "tables": [{"title": "...", "data": ..., "max_rows": 50}],
  "notes":   ["Caveat or method note"],
  "sources": ["Citation as returned by search_knowledge"]
}
Design rules (from a validated data-viz method): fixed categorical order, one y-axis per chart, legends for 2+ series,
hairline grids, 2px gaps, rounded bar ends, hover tooltips, and a data table behind every chart for accessibility.
"""
import argparse, csv, html, json, math, sys
from datetime import datetime
from pathlib import Path

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]   # validated order
MUTED_MARK = "#c9c7bf"
SURFACE, GRID, TEXT, TEXT2, TEXT3 = "#fcfcfb", "#e9e8e3", "#0b0b0b", "#52514e", "#8a8983"
BRAND, ACCENT = "#1f3a5f", "#0f7b6c"
STATUS = {"good": ("#0ca30c", "✓", "On track"), "warning": ("#b77800", "!", "Watch"), "critical": ("#d03b3b", "✕", "Needs attention")}
FONT = "Inter, 'Segoe UI', system-ui, -apple-system, Roboto, 'Noto Sans', sans-serif"


def load(data):
    """Return (columns, rows) from a CSV path or an inline {columns, rows} object, converting numbers."""
    if isinstance(data, dict):
        cols, rows = data["columns"], [list(r) for r in data["rows"]]
    else:
        with open(data, newline="") as f:
            r = list(csv.reader(f)); cols, rows = r[0], r[1:]
    def num(v):
        if isinstance(v, (int, float)) or v is None: return v
        try:
            f = float(str(v).replace(",", "")); return int(f) if f.is_integer() and "." not in str(v) else f
        except ValueError:
            return v if v != "" else None
    return cols, [[num(v) for v in row] for row in rows]


def fmt(v, unit=""):
    """Human-friendly number: $52.7M, 0.23%, 1,204 hrs."""
    if v is None or (isinstance(v, float) and math.isnan(v)): return "n/a"
    if not isinstance(v, (int, float)): return str(v)
    if unit == "%": return f"{v:,.2f}%" if abs(v) < 10 else f"{v:,.1f}%"
    a = abs(v)
    s = (f"{v / 1e12:,.2f}T" if a >= 1e12 else f"{v / 1e9:,.2f}B" if a >= 1e9 else f"{v / 1e6:,.1f}M" if a >= 1e6
         else f"{v:,.0f}" if a >= 1000 or float(v).is_integer() else f"{v:,.2f}")
    if unit == "$":
        return f"-${s[1:]}" if s.startswith("-") else f"${s}"
    return f"{s} {unit}" if unit and unit != "count" else s


def figure(c):
    cols, rows = load(c["data"])
    ix = {k: i for i, k in enumerate(cols)}
    kind, unit = c.get("type", "bar"), c.get("unit", "")
    x = c.get("x", cols[0])
    ys = c.get("y", [k for k in cols if k != x][:1])
    ys = [ys] if isinstance(ys, str) else ys
    if c.get("sort") in ("desc", "asc") and kind in ("bar", "hbar"):
        rows.sort(key=lambda r: (r[ix[ys[0]]] is None, r[ix[ys[0]]] or 0), reverse=c["sort"] == "desc")
    groups = []                                              # (name, xs, ys)
    if c.get("series"):
        s = c["series"]; seen = {}
        for r in rows:
            seen.setdefault(r[ix[s]], []).append(r)
        for name, rs in seen.items():
            groups.append((str(name), [r[ix[x]] for r in rs], [r[ix[ys[0]]] for r in rs]))
    else:
        for y in ys:
            groups.append((y.replace("_", " "), [r[ix[x]] for r in rows], [r[ix[y]] for r in rows]))
    if kind == "scatter" and len(groups) > 3:
        raise SystemExit("scatter charts allow at most 3 series (colour safety); facet or fold the rest into 'Other'")
    if len(groups) > 8:
        raise SystemExit("more than 8 series: fold the smallest into 'Other' or split into several charts")

    if kind in ("bar", "grouped_bar", "stacked_bar") and max((len(str(v)) for _, gx, _ in groups for v in gx), default=0) > 14:
        kind = "hbar" if kind == "bar" else kind      # long labels read badly tilted; lay the bars on their side
        horizontal = True
    else:
        horizontal = kind == "hbar"
    ends = sorted(g[2][-1] for g in groups if g[2] and isinstance(g[2][-1], (int, float)))
    span = (max(v for g in groups for v in g[2] if isinstance(v, (int, float))) - min(v for g in groups for v in g[2] if isinstance(v, (int, float)))) or 1
    ends_apart = all(b - a > 0.06 * span for a, b in zip(ends, ends[1:]))
    fig = go.Figure()
    hover_val = "%{x:,.2f}" if horizontal else "%{y:,.2f}"
    for i, (name, gx, gy) in enumerate(groups):
        color = SERIES[i]
        if kind in ("bar", "hbar", "grouped_bar", "stacked_bar"):
            colors = color
            if c.get("highlight") is not None and len(groups) == 1:
                colors = [SERIES[0] if str(v) == str(c["highlight"]) else MUTED_MARK for v in gx]
            horiz = horizontal
            fig.add_bar(name=name, x=gy if horiz else gx, y=gx if horiz else gy, orientation="h" if horiz else "v",
                        marker=dict(color=colors, line=dict(color=SURFACE, width=2)),
                        text=[fmt(v, unit) for v in gy] if len(groups) == 1 and len(gx) <= 15 else None,
                        textposition="outside", cliponaxis=False, textfont=dict(color=TEXT2, size=12),
                        hovertemplate=f"<b>%{{{'y' if horiz else 'x'}}}</b><br>{name}: {hover_val}<extra></extra>")
        elif kind == "line":
            fig.add_scatter(name=name, x=gx, y=gy, mode="lines+markers", line=dict(color=color, width=2, shape="linear"),
                            marker=dict(size=8, color=color, line=dict(color=SURFACE, width=2)),
                            hovertemplate=f"{name}: %{{y:,.2f}}<extra></extra>")
            if len(groups) <= 4 and gx and ends_apart:       # direct label at the end of each line
                fig.add_annotation(x=gx[-1], y=gy[-1], text=name, showarrow=False, xanchor="left", xshift=8,
                                   font=dict(color=TEXT2, size=12))
        elif kind == "scatter":
            fig.add_scatter(name=name, x=gx, y=gy, mode="markers",
                            marker=dict(size=10, color=color, opacity=0.85, line=dict(color=SURFACE, width=2)),
                            hovertemplate=f"{name}<br>%{{x}}: %{{y:,.2f}}<extra></extra>")
    multi = len(groups) >= 2
    fig.update_layout(
        barmode="stack" if kind == "stacked_bar" else "group", bargap=0.28, bargroupgap=0.06, barcornerradius=4,
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, font=dict(family=FONT, color=TEXT2, size=13),
        margin=dict(l=8, r=90 if kind == "line" and multi else 24, t=12, b=8), height=c.get("height", 380),
        showlegend=multi, legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=TEXT2)),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=GRID, font=dict(color=TEXT, family=FONT)),
        hovermode="x unified" if kind == "line" else "closest")
    axis = dict(gridcolor=GRID, gridwidth=1, zeroline=False, linecolor=GRID, tickfont=dict(color=TEXT2), title=None, automargin=True)
    fig.update_xaxes(**axis, showgrid=horizontal or kind == "scatter")
    fig.update_yaxes(**axis, showgrid=not horizontal)
    value_axis = dict(exponentformat="B", tickprefix="$" if unit == "$" else "", ticksuffix="%" if unit == "%" else "", separatethousands=True)
    if horizontal:
        fig.update_xaxes(**value_axis); fig.update_yaxes(showgrid=False, autorange="reversed")
    else:
        fig.update_yaxes(**value_axis)
    if kind in ("bar", "hbar") and len(groups) == 1:   # leave room for the value labels outside the bars
        vals = [v for v in groups[0][2] if isinstance(v, (int, float))]
        if vals:
            lo, hi = min(0, min(vals)), max(vals)
            pad = 0.22 * (max(abs(lo), abs(hi)) or 1)      # room for labels on both sides of zero
            rng = [lo - (pad if lo < 0 else 0), hi + pad if hi > 0 else 0]
            (fig.update_xaxes if horizontal else fig.update_yaxes)(range=rng)
    if horizontal:
        fig.update_layout(height=c.get("height", max(260, 46 * len(groups[0][1]) * (1 + 0.6 * (len(groups) - 1)) + 80)))
    return fig, cols, rows


def table_html(cols, rows, max_rows=50, unit=""):
    head = "".join(f"<th>{html.escape(str(c).replace('_', ' '))}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td class='{'num' if isinstance(v, (int, float)) else ''}'>{html.escape(fmt(v) if isinstance(v, (int, float)) else str(v if v is not None else ''))}</td>" for v in r) + "</tr>"
                   for r in rows[:max_rows])
    more = f"<p class='more'>Showing {max_rows} of {len(rows):,} rows.</p>" if len(rows) > max_rows else ""
    return f"<div class='tbl'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{more}"


CSS = f"""
*{{box-sizing:border-box}} body{{margin:0;background:#f4f3ef;color:{TEXT};font:15px/1.5 {FONT}}}
header{{background:{BRAND};color:#fff;padding:28px 40px 24px}} header .brand{{font-size:12px;letter-spacing:.14em;text-transform:uppercase;opacity:.75;font-weight:700}}
header h1{{margin:6px 0 4px;font-size:28px;letter-spacing:-.01em}} header p{{margin:0;opacity:.85}}
main{{max-width:1200px;margin:0 auto;padding:28px 32px 48px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin-bottom:22px}}
.kpi{{background:{SURFACE};border:1px solid {GRID};border-radius:14px;padding:16px 18px}}
.kpi .label{{color:{TEXT2};font-size:13px;font-weight:600}} .kpi .value{{font-size:30px;font-weight:700;color:{TEXT};line-height:1.15;margin:4px 0 2px;font-variant-numeric:tabular-nums}}
.kpi .note{{color:{TEXT3};font-size:13px}} .pill{{display:inline-flex;gap:6px;align-items:center;font-size:12px;font-weight:700;border-radius:999px;padding:2px 10px;margin-top:8px;color:#fff}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} @media (max-width:900px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:{SURFACE};border:1px solid {GRID};border-radius:14px;padding:18px 20px}} .card.wide{{grid-column:1/-1}}
.card h2{{margin:0;font-size:17px;color:{TEXT}}} .card .sub{{color:{TEXT2};font-size:13px;margin:2px 0 10px}}
details{{margin-top:6px}} summary{{cursor:pointer;color:{ACCENT};font-size:13px;font-weight:600}}
.tbl{{overflow-x:auto;max-height:420px;margin-top:8px}} table{{border-collapse:collapse;width:100%;font-size:13px}}
th{{text-align:left;color:{TEXT2};font-weight:600;border-bottom:1px solid {GRID};padding:6px 10px;position:sticky;top:0;background:{SURFACE}}}
td{{border-bottom:1px solid #f0efea;padding:6px 10px}} td.num{{text-align:right;font-variant-numeric:tabular-nums}} .more{{color:{TEXT3};font-size:12px}}
section.notes{{margin-top:22px}} section.notes h2{{font-size:16px}} section.notes li{{margin:4px 0;color:{TEXT2}}}
footer{{color:{TEXT3};font-size:12px;text-align:center;padding:10px 0 30px}}
"""


def build(spec, out):
    parts, figs = [], 0
    for k in spec.get("kpis", []):
        st = STATUS.get(k.get("status", ""))
        pill = f"<span class='pill' style='background:{st[0]}' role='img' aria-label='{st[2]}'>{st[1]} {st[2]}</span>" if st else ""
        val = k["value"] if isinstance(k["value"], str) else fmt(k["value"], k.get("unit", ""))
        parts.append(f"<div class='kpi'><div class='label'>{html.escape(k['label'])}</div><div class='value'>{html.escape(val)}</div>"
                     f"<div class='note'>{html.escape(k.get('note', ''))}</div>{pill}</div>")
    kpis = f"<div class='kpis'>{''.join(parts)}</div>" if parts else ""
    cards = []
    for c in spec.get("charts", []):
        fig, cols, rows = figure(c); figs += 1
        div = fig.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False, "responsive": True,
                          "modeBarButtonsToRemove": ["lasso2d", "select2d"]}, div_id=f"chart{figs}")
        cards.append(f"<div class='card{' wide' if c.get('wide') else ''}'><h2>{html.escape(c['title'])}</h2>"
                     f"<div class='sub'>{html.escape(c.get('subtitle', ''))}</div>{div}"
                     f"<details><summary>Show data</summary>{table_html(cols, rows, 200)}</details></div>")
    for t in spec.get("tables", []):
        cols, rows = load(t["data"])
        cards.append(f"<div class='card wide'><h2>{html.escape(t['title'])}</h2><div class='sub'>{html.escape(t.get('subtitle', ''))}</div>"
                     f"{table_html(cols, rows, t.get('max_rows', 50))}</div>")
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in spec.get("notes", []))
    srcs = "".join(f"<li>{html.escape(s)}</li>" for s in spec.get("sources", []))
    extra = ""
    if notes: extra += f"<section class='notes card'><h2>Notes and method</h2><ul>{notes}</ul></section>"
    if srcs: extra += f"<section class='notes card'><h2>Sources</h2><ul>{srcs}</ul></section>"
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(spec['title'])}</title><style>{CSS}</style><script>{get_plotlyjs()}</script></head>
<body><header><div class="brand">Tally</div><h1>{html.escape(spec['title'])}</h1><p>{html.escape(spec.get('subtitle', ''))}</p></header>
<main>{kpis}<div class="grid">{''.join(cards)}</div>{extra}</main>
<footer>Generated by Tally on {datetime.now():%B %d, %Y}{(' · Data: ' + html.escape(spec['as_of'])) if spec.get('as_of') else ''}</footer></body></html>"""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(doc)
    print(f"dashboard -> {out} ({len(doc) / 1e6:.1f} MB, {figs} charts, {len(spec.get('kpis', []))} KPIs, works offline)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    build(json.loads(Path(a.spec).read_text()), a.out)
