#!/usr/bin/env python3
"""Render a professional PDF report from a JSON spec (WeasyPrint + matplotlib, fully offline).

  report.py spec.json --out /workspace/out/report.pdf

Spec:
{
  "title": "...", "subtitle": "...", "prepared_for": "NASA budget analyst", "as_of": "FY2025, period 12",
  "summary": ["Key finding one", "Key finding two"],              # the boxed executive summary
  "sections": [
    {"heading": "...", "body": "Markdown text",
     "chart": {"type": "bar|hbar|line|grouped_bar", "data": "/workspace/data/x.csv", "x": "col", "y": "col" or [..],
               "series": "col", "unit": "$|%|hrs|count", "title": "...", "highlight": "value"},
     "table": {"data": "/workspace/data/y.csv", "max_rows": 20, "caption": "..."}}
  ],
  "sources": ["Citation 1", "Citation 2"]
}
"""
import argparse, base64, csv, html, io, json, math
from datetime import datetime
from pathlib import Path

import markdown
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator
from weasyprint import HTML

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]   # same validated order as dashboards
MUTED, GRID, TEXT, TEXT2, BRAND, ACCENT = "#c9c7bf", "#e9e8e3", "#0b0b0b", "#52514e", "#1f3a5f", "#0f7b6c"


def load(path):
    with open(path, newline="") as f:
        r = list(csv.reader(f))
    def num(v):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return v
    return r[0], [[num(v) for v in row] for row in r[1:]]


def fmt(v, unit=""):
    if not isinstance(v, (int, float)) or (isinstance(v, float) and math.isnan(v)):
        return str(v)
    if unit == "%":
        return f"{v:,.1f}%"
    a = abs(v)
    s = (f"{v / 1e9:,.2f}B" if a >= 1e9 else f"{v / 1e6:,.1f}M" if a >= 1e6 else f"{v / 1e3:,.1f}K" if a >= 1e4
         else f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}")
    if unit == "$":
        return f"-${s[1:]}" if s.startswith("-") else f"${s}"
    return f"{s} {unit}" if unit and unit != "count" else s


def tick(v, unit=""):
    """Axis labels: short, no trailing decimals ($200M, $1.5B, 40%)."""
    a = abs(v)
    s = (f"{v / 1e9:g}B" if a >= 1e9 else f"{v / 1e6:g}M" if a >= 1e6 else f"{v / 1e3:g}K" if a >= 1e4 else f"{v:g}")
    if unit == "$": return f"-${s[1:]}" if s.startswith("-") else f"${s}"
    return f"{s}%" if unit == "%" else s


def chart_png(c):
    cols, rows = load(c["data"])
    ix = {k: i for i, k in enumerate(cols)}
    x, unit, kind = c.get("x", cols[0]), c.get("unit", ""), c.get("type", "bar")
    ys = c.get("y", [k for k in cols if k != x][:1]); ys = [ys] if isinstance(ys, str) else ys
    groups = []
    if c.get("series"):
        seen = {}
        for r in rows:
            seen.setdefault(r[ix[c["series"]]], []).append(r)
        groups = [(str(k), [r[ix[x]] for r in v], [r[ix[ys[0]]] for r in v]) for k, v in seen.items()][:8]
    else:
        groups = [(y.replace("_", " "), [r[ix[x]] for r in rows], [r[ix[y]] for r in rows]) for y in ys][:8]
    if kind in ("bar", "grouped_bar") and max(len(str(v)) for v in groups[0][1]) > 14:
        kind = "hbar"
    n = len(groups[0][1])
    fig, ax = plt.subplots(figsize=(7.2, max(2.6, 0.38 * n + 1.0) if kind == "hbar" else 3.2), dpi=200)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5})
    ax.set_facecolor("white"); fig.patch.set_facecolor("white")
    if kind == "line":
        for i, (name, gx, gy) in enumerate(groups):
            ax.plot(gx, gy, color=SERIES[i], lw=2, marker="o", ms=4, mec="white", mew=1.2, label=name)
    else:
        width = 0.8 / len(groups)
        for i, (name, gx, gy) in enumerate(groups):
            pos = [j + (i - (len(groups) - 1) / 2) * width for j in range(n)]
            colors = SERIES[i]
            if c.get("highlight") is not None and len(groups) == 1:
                colors = [SERIES[0] if str(v) == str(c["highlight"]) else MUTED for v in gx]
            if kind == "hbar":
                ax.barh(pos, gy, height=width * 0.92, color=colors, label=name)
            else:
                ax.bar(pos, gy, width=width * 0.92, color=colors, label=name)
            if len(groups) == 1 and n <= 15:
                for p, v in zip(pos, gy):
                    if isinstance(v, (int, float)):
                        if kind == "hbar":
                            ax.text(v, p, " " + fmt(v, unit), va="center", ha="left" if v >= 0 else "right", color=TEXT2, fontsize=7.5)
                        else:
                            ax.text(p, v, fmt(v, unit), ha="center", va="bottom", color=TEXT2, fontsize=7.5)
        labels = [str(v) for v in groups[0][1]]
        if kind == "hbar":
            ax.set_yticks(range(n), labels); ax.invert_yaxis(); ax.margins(x=0.18)
        else:
            ax.set_xticks(range(n), labels)
    value_axis = ax.xaxis if kind == "hbar" else ax.yaxis
    value_axis.set_major_locator(MaxNLocator(nbins=5))                       # few, clean ticks
    value_axis.set_major_formatter(FuncFormatter(lambda v, _: tick(v, unit)))
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="x" if kind == "hbar" else "y", color=GRID, lw=0.8); ax.set_axisbelow(True)
    ax.tick_params(colors=TEXT2, length=0)
    if len(groups) > 1:
        ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2 if max(len(g[0]) for g in groups) > 22 else min(4, len(groups)), fontsize=8)
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png", facecolor="white"); plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def table(t):
    cols, rows = load(t["data"])
    mx = t.get("max_rows", 25)
    head = "".join(f"<th>{html.escape(c.replace('_', ' '))}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td class='{'n' if isinstance(v, float) else ''}'>{html.escape(fmt(v) if isinstance(v, float) else str(v))}</td>" for v in r) + "</tr>"
                   for r in rows[:mx])
    note = f" Showing {mx} of {len(rows):,} rows." if len(rows) > mx else ""
    cap = f"<p class='cap'>{html.escape(t.get('caption', ''))}{note}</p>" if t.get("caption") or note else ""
    size = "8.5pt" if len(cols) <= 5 else "7.5pt" if len(cols) <= 7 else "6.5pt"     # wide tables shrink to fit the page
    return f"<table style='font-size:{size}'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{cap}"


CSS = f"""
@page {{ size: Letter; margin: 0.8in 0.75in 0.85in;
  @bottom-left {{ content: "Tally"; font: 8pt 'DejaVu Sans'; color: #8a8983; }}
  @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font: 8pt 'DejaVu Sans'; color: #8a8983; }} }}
@page :first {{ margin-top: 0; @bottom-left {{ content: none }} @bottom-right {{ content: none }} }}
body {{ font: 10pt/1.5 'DejaVu Sans', sans-serif; color: {TEXT}; }}
.cover {{ background: {BRAND}; color: #fff; margin: 0 -0.75in; padding: 1.1in 0.75in 0.5in; }}
.cover .brand {{ font-size: 8pt; letter-spacing: 2px; text-transform: uppercase; opacity: .75; font-weight: bold; }}
.cover h1 {{ font-size: 23pt; line-height: 1.15; margin: 8pt 0 6pt; }} .cover p {{ margin: 2pt 0; opacity: .9; }}
.meta {{ margin-top: 14pt; font-size: 9pt; opacity: .85; }}
.summary {{ border-left: 4pt solid {ACCENT}; background: #f1f7f6; padding: 10pt 14pt; margin: 18pt 0; }}
.summary h2 {{ margin: 0 0 4pt; font-size: 11pt; color: {ACCENT}; }} .summary li {{ margin: 3pt 0; }}
h2 {{ color: {BRAND}; font-size: 13pt; margin: 18pt 0 6pt; page-break-after: avoid; }}
h3 {{ font-size: 11pt; margin: 12pt 0 4pt; }}
img.chart {{ width: 100%; margin: 4pt 0 6pt; }} .figure {{ page-break-inside: avoid; }} .chart-title {{ font-weight: bold; font-size: 9.5pt; color: {TEXT2}; margin-top: 8pt; }}
table {{ border-collapse: collapse; width: 100%; table-layout: fixed; margin: 6pt 0; page-break-inside: auto; }} td, th {{ overflow-wrap: anywhere; }}
th {{ text-align: left; color: {TEXT2}; border-bottom: 1pt solid #bbb; padding: 4pt 6pt; }} td {{ border-bottom: .5pt solid #e5e5e0; padding: 3.5pt 6pt; }}
td.n {{ text-align: right; }} tr {{ page-break-inside: avoid; }} .cap {{ font-size: 8pt; color: #8a8983; margin-top: 2pt; }}
.sources li {{ font-size: 8.5pt; color: {TEXT2}; margin: 2pt 0; }}
"""


def build(spec, out):
    parts = [f"<div class='cover'><div class='brand'>Tally report</div><h1>{html.escape(spec['title'])}</h1>",
             f"<p>{html.escape(spec.get('subtitle', ''))}</p><div class='meta'>"]
    if spec.get("prepared_for"): parts.append(f"Prepared for: {html.escape(spec['prepared_for'])}<br>")
    if spec.get("as_of"): parts.append(f"Data: {html.escape(spec['as_of'])}<br>")
    parts.append(f"Generated {datetime.now():%B %d, %Y}</div></div>")
    if spec.get("summary"):
        parts.append("<div class='summary'><h2>Summary</h2><ul>" + "".join(f"<li>{markdown.markdown(s)[3:-4]}</li>" for s in spec["summary"]) + "</ul></div>")
    for sec in spec.get("sections", []):
        parts.append(f"<h2>{html.escape(sec['heading'])}</h2>")
        if sec.get("body"): parts.append(markdown.markdown(sec["body"], extensions=["tables"]))
        if sec.get("chart"):
            title = f"<div class='chart-title'>{html.escape(sec['chart']['title'])}</div>" if sec["chart"].get("title") else ""
            parts.append(f"<div class='figure'>{title}<img class='chart' src='data:image/png;base64,{chart_png(sec['chart'])}'></div>")
        if sec.get("table"): parts.append(table(sec["table"]))
    if spec.get("sources"):
        parts.append("<h2>Sources</h2><ol class='sources'>" + "".join(f"<li>{html.escape(s)}</li>" for s in spec["sources"]) + "</ol>")
    doc = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    HTML(string=doc).write_pdf(target=out)
    print(f"report -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    build(json.loads(Path(a.spec).read_text()), a.out)
