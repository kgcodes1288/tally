#!/usr/bin/env python3
"""Build the knowledge base from every kind of source Tally supports:

  playbooks   kb/docs/<workspace>/*.md          (authority: internal)
  registry    kb/sources.yaml: PDFs, web pages, wiki articles (authority from the registry)
  official    USAspending glossary, NYC 311 column definitions (structured docs from the data publishers)
  uploads     kb/uploads/<workspace>/*.{pdf,docx,md,html,txt} (authority: uploaded)

Each document is parsed in a format-aware way, split into passages that keep their heading or page number,
embedded locally (fastembed, BAAI/bge-small-en-v1.5) and stored with a ready-made citation.
Unchanged documents (same SHA-256) are skipped, so re-running is cheap.

  ingest.py            ingest everything
  ingest.py --force    re-embed everything
"""
import hashlib, io, json, re, sys, urllib.parse, urllib.request
from pathlib import Path

import docx, trafilatura, yaml
from fastembed import TextEmbedding
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "loaders"))
from common import connect

KB = Path(__file__).resolve().parent
CACHE = KB / "cache"; CACHE.mkdir(exist_ok=True)
UA = {"User-Agent": "Tally/1.0 (personal open-source research project)"}
MAX, OVERLAP = 1400, 200


# ---------------------------------------------------------------- fetching (polite, cached)
def fetch(url: str) -> bytes:
    p = CACHE / hashlib.sha1(url.encode()).hexdigest()
    if not p.exists():
        p.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read())
    return p.read_bytes()


def wiki(page: str) -> tuple[str, str]:
    q = urllib.parse.urlencode({"action": "query", "prop": "extracts", "explaintext": 1, "format": "json", "redirects": 1, "titles": page})
    raw = fetch(f"https://en.wikipedia.org/w/api.php?{q}")
    text = next(iter(json.loads(raw)["query"]["pages"].values()))["extract"]
    return text, f"https://en.wikipedia.org/wiki/{page}"


# ---------------------------------------------------------------- splitting
def windows(text: str):
    """Split long text on paragraph boundaries into overlapping windows of about MAX characters."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= MAX:
        if text: yield text
        return
    paras, cur = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()], ""
    for p in paras:
        while len(p) > MAX:                      # a single huge paragraph
            yield (cur + " " + p[:MAX]).strip() if cur else p[:MAX]; cur = ""; p = p[MAX - OVERLAP:]
        if len(cur) + len(p) + 1 > MAX:
            yield cur; cur = cur[-OVERLAP:] + " " + p
        else:
            cur = (cur + "\n" + p).strip()
    if cur.strip(): yield cur


def by_headings(text: str, pattern: str):
    """Split text into (heading, body) by a heading regex with one capture group."""
    parts = re.split(pattern, text, flags=re.M)
    if parts[0].strip(): yield "Introduction", parts[0]
    for i in range(1, len(parts) - 1, 2):
        yield parts[i].strip(), parts[i + 1]


# ---------------------------------------------------------------- parsers: each yields (section, page, content)
def parse_pdf(data: bytes):
    r = PdfReader(io.BytesIO(data))
    for n, page in enumerate(r.pages, 1):
        t = page.extract_text() or ""
        if len(t.strip()) < 80: continue         # covers, blank and image-only pages
        for w in windows(t): yield f"Page {n}", n, w


def parse_markdown(text: str):
    title_free = re.sub(r"^# .*\n", "", text, count=1)
    for head, body in by_headings(title_free, r"^#{2,3} (.+)$"):
        for w in windows(body): yield head, None, w


def parse_html(data: bytes, url: str):
    md = trafilatura.extract(data.decode("utf-8", "ignore"), url=url, output_format="markdown", include_links=False, include_tables=True) or ""
    yield from parse_markdown(md)


def parse_wiki(text: str):
    text = re.split(r"^== (See also|References|External links|Notes|Further reading) ==$", text, flags=re.M)[0]
    for head, body in by_headings(text, r"^={2,3} (.+?) ={2,3}$"):
        for w in windows(body): yield head, None, w


def parse_docx(data: bytes):
    d = docx.Document(io.BytesIO(data)); head, buf = "Introduction", []
    for p in d.paragraphs:
        if p.style.name.lower().startswith("heading") and p.text.strip():
            if buf: yield from ((head, None, w) for w in windows("\n".join(buf)))
            head, buf = p.text.strip(), []
        elif p.text.strip():
            buf.append(p.text)
    if buf: yield from ((head, None, w) for w in windows("\n".join(buf)))


# ---------------------------------------------------------------- citations
def cite(doc: dict, section: str, page):
    if page: return f"{doc['title']}, p. {page}"
    if doc["authority"] == "internal": return f'Tally playbook "{doc["title"]}", section "{section}"'
    if doc["source_type"] == "glossary": return f"{doc['title']}: {section}"
    return f'{doc["title"]} ({doc["publisher"]}), section "{section}"'


# ---------------------------------------------------------------- document collection
def documents():
    """Yield (doc metadata, raw bytes for hashing, passage generator factory)."""
    for ws_dir in sorted((KB / "docs").iterdir()):
        for f in sorted(ws_dir.glob("*.md")):
            text = f.read_text(); title = re.search(r"^# (.+)$", text, re.M).group(1)
            yield ({"workspace_id": ws_dir.name, "title": title, "source_type": "markdown", "authority": "internal",
                    "publisher": "Tally", "url": None}, text.encode(), lambda t=text: parse_markdown(t))

    for ws, items in yaml.safe_load((KB / "sources.yaml").read_text()).items():
        for s in items:
            meta = {"workspace_id": ws, "title": s["title"], "source_type": s["type"], "authority": s["authority"], "publisher": s["publisher"]}
            try:
                if s["type"] == "wiki":
                    text, url = wiki(s["page"]); yield meta | {"url": url}, text.encode(), lambda t=text: parse_wiki(t)
                elif s["type"] == "pdf":
                    data = fetch(s["url"]); yield meta | {"url": s["url"]}, data, lambda d=data: parse_pdf(d)
                elif s["type"] == "html":
                    data = fetch(s["url"]); yield meta | {"url": s["url"]}, data, lambda d=data, u=s["url"]: parse_html(d, u)
            except Exception as e:                # one bad source must not stop the rest
                print(f"  ! skipped {s['title']}: {e}", flush=True)

    g = (KB / "sources/usaspending_glossary.json").read_bytes()
    def glossary():
        for t in json.loads(g)["results"]:
            body = (t.get("plain") or "").strip()
            if t.get("official"): body += "\n\nOfficial definition: " + t["official"].strip()
            if body: yield t["term"], None, body
    yield ({"workspace_id": "ws_federal", "title": "USAspending glossary", "source_type": "glossary", "authority": "official",
            "publisher": "USAspending.gov", "url": "https://www.usaspending.gov/"}, g, glossary)

    m = (KB / "sources/nyc311_metadata.json").read_bytes()
    def columns():
        meta = json.loads(m)
        yield "About the dataset", None, meta.get("description", "")
        for c in meta["columns"]:
            if c.get("description"): yield c["fieldName"], None, f'{c["name"]}: {c["description"]}'
    yield ({"workspace_id": "ws_city", "title": "NYC 311 column definitions", "source_type": "metadata", "authority": "official",
            "publisher": "NYC Open Data", "url": "https://data.cityofnewyork.us/d/erm2-nwe9"}, m, columns)

    for ws_dir in sorted(p for p in (KB / "uploads").iterdir() if p.is_dir()):
        for f in sorted(ws_dir.iterdir()):
            data, ext = f.read_bytes(), f.suffix.lower()
            kinds = {".pdf": ("pdf", lambda d=data: parse_pdf(d)), ".docx": ("docx", lambda d=data: parse_docx(d)),
                     ".md": ("markdown", lambda d=data: parse_markdown(d.decode())), ".txt": ("markdown", lambda d=data: parse_markdown(d.decode())),
                     ".html": ("html", lambda d=data: parse_html(d, ""))}
            if ext in kinds:
                kind, gen = kinds[ext]
                yield ({"workspace_id": ws_dir.name, "title": f.stem.replace("_", " "), "source_type": kind, "authority": "uploaded",
                        "publisher": "Uploaded by a workspace member", "url": None}, data, gen)


# ---------------------------------------------------------------- main
def main(force=False):
    pg = connect(); model = TextEmbedding("BAAI/bge-small-en-v1.5")
    seen = set()
    for meta, raw, parts in documents():
        key = (meta["workspace_id"], meta["title"]); seen.add(key)
        sha = hashlib.sha256(raw).hexdigest()
        old = pg.execute("SELECT id, sha256 FROM tally.kb_documents WHERE workspace_id=%s AND title=%s", key).fetchone()
        if old and old[1] == sha and not force:
            print(f"  = {meta['title']} (unchanged)"); continue
        if old: pg.execute("DELETE FROM tally.kb_documents WHERE id=%s", (old[0],))
        passages = [(s, p, c) for s, p, c in parts() if c and c.strip()]
        if not passages:
            print(f"  ! {meta['title']}: no text extracted"); continue
        pages = max((p or 0) for _, p, _ in passages) or None
        doc_id = pg.execute("""INSERT INTO tally.kb_documents (workspace_id, title, source_type, authority, publisher, url, sha256, pages)
                               VALUES (%(workspace_id)s, %(title)s, %(source_type)s, %(authority)s, %(publisher)s, %(url)s, %(sha)s, %(pages)s) RETURNING id""",
                            meta | {"sha": sha, "pages": pages}).fetchone()[0]
        vecs = model.embed([f"{meta['title']} | {s}\n{c}" for s, _, c in passages], batch_size=64)
        with pg.cursor() as cur:
            cur.executemany("""INSERT INTO tally.kb_chunks (doc_id, workspace_id, section, page, content, citation, embedding)
                               VALUES (%s,%s,%s,%s,%s,%s,%s::vector)""",
                            [(doc_id, meta["workspace_id"], s[:300], p, c, cite(meta, s, p), "[" + ",".join(f"{x:.6f}" for x in v) + "]")
                             for (s, p, c), v in zip(passages, vecs)])
        print(f"  + {meta['workspace_id']:<11} {meta['source_type']:<9} {meta['authority']:<9} {meta['title']}: {len(passages)} passages", flush=True)
    for doc_id, ws, title in pg.execute("SELECT id, workspace_id, title FROM tally.kb_documents").fetchall():
        if (ws, title) not in seen:
            pg.execute("DELETE FROM tally.kb_documents WHERE id=%s", (doc_id,)); print(f"  - removed {title}")
    for ws, d, n in pg.execute("SELECT d.workspace_id, count(DISTINCT d.id), count(c.id) FROM tally.kb_documents d JOIN tally.kb_chunks c ON c.doc_id=d.id GROUP BY 1 ORDER BY 1"):
        print(f"{ws}: {d} documents, {n} passages")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
