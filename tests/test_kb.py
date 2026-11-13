"""Knowledge base: the right playbook comes back for a question, and workspaces cannot read each other's knowledge."""
import pytest
from fastembed import TextEmbedding
from test_rls import temp_login

M = TextEmbedding("BAAI/bge-small-en-v1.5")
def vec(q): return "[" + ",".join(f"{x:.6f}" for x in next(iter(M.embed([q])))) + "]"

def search(conn, q, k=3):
    return conn.execute("SELECT workspace_id, doc, section FROM tally.kb_search(%s::vector, %s, %s)", (vec(q), q, k)).fetchall()

@pytest.mark.parametrize("persona, question, expect_doc", [
    ("p_fed_nasa", "why would File C rows not match any award?", "How the federal spending files fit together"),
    ("p_fed_oversight", "how do I reconcile File A with File B?", "Federal spending reconciliation playbook"),
    ("p_ret_finance", "why does amount paid differ from the order total?", "Olist marketplace data model"),
    ("p_city_citywide", "some requests have negative response time", "NYC 311 service requests: model and data quality"),
])
def test_retrieves_relevant_doc(persona, question, expect_doc):
    admin, name, c = temp_login(persona)
    try:
        assert expect_doc in [d for _, d, _ in search(c, question)]
    finally:
        c.close(); admin.execute(f"DROP ROLE {name}")

def test_knowledge_is_scoped_to_workspace():
    admin, name, c = temp_login("p_ret_sp")
    try:
        hits = search(c, "File A File B reconciliation unlinked awards", k=10)
        assert hits and all(ws == "ws_retail" for ws, _, _ in hits)
    finally:
        c.close(); admin.execute(f"DROP ROLE {name}")
