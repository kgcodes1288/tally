#!/usr/bin/env python3
"""Build the knowledge base: playbooks (kb/docs/<workspace>/*.md) plus official dataset documentation,
split into sections, embedded locally with fastembed (BAAI/bge-small-en-v1.5) and stored in tally.kb_chunks.
Re-running replaces everything, so it is safe to run after editing a playbook."""
import json, re, sys
from pathlib import Path
from fastembed import TextEmbedding

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "loaders"))
from common import connect

KB = Path(__file__).resolve().parent
MODEL = "BAAI/bge-small-en-v1.5"


def markdown_chunks(ws, path):
    text = path.read_text()
    title = re.search(r"^# (.+)$", text, re.M).group(1)
    parts = re.split(r"^## ", text, flags=re.M)
    intro = parts[0].split("\n", 1)[1].strip() if "\n" in parts[0] else ""
    if intro: yield ws, title, "Overview", None, intro
    for p in parts[1:]:
        head, _, body = p.partition("\n")
        yield ws, title, head.strip(), None, body.strip()


def official_chunks():
    g = json.loads((KB / "sources/usaspending_glossary.json").read_text())["results"]
    for t in g:
        body = (t.get("plain") or "").strip()
        if t.get("official"): body += "\n\nOfficial definition: " + t["official"].strip()
        if body: yield "ws_federal", "USAspending glossary", t["term"], "https://www.usaspending.gov/", body
    m = json.loads((KB / "sources/nyc311_metadata.json").read_text())
    yield "ws_city", "NYC 311 dataset (NYC Open Data)", "About the dataset", "https://data.cityofnewyork.us/d/erm2-nwe9", m.get("description", "")
    for c in m["columns"]:
        if c.get("description"):
            yield "ws_city", "NYC 311 column definitions", c["fieldName"], "https://data.cityofnewyork.us/d/erm2-nwe9", f'{c["name"]}: {c["description"]}'


def main():
    rows = [c for ws_dir in sorted((KB / "docs").iterdir()) for f in sorted(ws_dir.glob("*.md")) for c in markdown_chunks(ws_dir.name, f)]
    rows += list(official_chunks())
    rows = [r for r in rows if r[4]]
    model = TextEmbedding(MODEL)
    vecs = list(model.embed([f"{r[1]}. {r[2]}. {r[4]}" for r in rows]))
    pg = connect()
    pg.execute("TRUNCATE tally.kb_chunks")
    with pg.cursor() as cur:
        cur.executemany("INSERT INTO tally.kb_chunks (workspace_id, doc, section, source_url, content, embedding) VALUES (%s,%s,%s,%s,%s,%s::vector)",
                        [(*r, "[" + ",".join(f"{x:.6f}" for x in v) + "]") for r, v in zip(rows, vecs)])
    for ws, n in pg.execute("SELECT workspace_id, count(*) FROM tally.kb_chunks GROUP BY 1 ORDER BY 1"):
        print(f"  {ws}: {n} chunks")


if __name__ == "__main__":
    main()
