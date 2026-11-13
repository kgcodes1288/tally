"""Knowledge base: the right source comes back (with a citation) for real questions,
authoritative sources win, and workspaces cannot read each other's knowledge."""
import pytest
from fastembed import TextEmbedding
from test_rls import temp_login

M = TextEmbedding("BAAI/bge-small-en-v1.5")


def vec(q):
    return "[" + ",".join(f"{x:.6f}" for x in next(iter(M.embed([q])))) + "]"


def search(conn, q, k=5):
    return conn.execute("SELECT workspace_id, title, authority, citation, page FROM tally.kb_search(%s::vector, %s, %s)",
                        (vec(q), q, k)).fetchall()


@pytest.mark.parametrize("persona, question, expect_title", [
    # internal playbooks
    ("p_fed_oversight", "how do I reconcile File A with File B?", "Federal spending reconciliation playbook"),
    ("p_ret_finance", "why does amount paid differ from the order total?", "Olist marketplace data model"),
    # official PDF, official web page, official structured docs
    ("p_fed_nasa", "what does the account breakdown by award file contain in the data download?", "About the USAspending Data Download"),
    ("p_city_citywide", "what indoor temperature must landlords keep at night during heat season?", "Heat and Hot Water Information"),
    ("p_city_bronx", "Department of Housing Preservation and Development heat complaints performance", "Mayor's Management Report, Fiscal 2025"),
    ("p_city_citywide", "what does the open data channel type column mean?", "NYC 311 column definitions"),
    # wiki articles
    ("p_ret_sp", "what is a boleto payment?", "Boleto"),
    ("p_ret_south", "instant payment system launched by the Central Bank of Brazil", "Pix (payment system)"),
])
def test_retrieves_the_right_source(persona, question, expect_title):
    admin, name, c = temp_login(persona)
    try:
        hits = search(c, question)
        assert expect_title in [t for _, t, _, _, _ in hits], hits
    finally:
        c.close(); admin.execute(f"DROP ROLE {name}")


def test_pdf_passages_cite_page_numbers():
    admin, name, c = temp_login("p_city_citywide")
    try:
        hits = [h for h in search(c, "311 customer service performance indicators", k=10) if h[1].startswith("Mayor")]
        assert hits and all(h[4] and h[3].endswith(f"p. {h[4]}") for h in hits)
    finally:
        c.close(); admin.execute(f"DROP ROLE {name}")


def test_knowledge_is_scoped_to_workspace():
    admin, name, c = temp_login("p_ret_sp")
    try:
        hits = search(c, "File A File B reconciliation unlinked awards heat season 311", k=15)
        assert hits and all(ws == "ws_retail" for ws, *_ in hits)
        docs = {t for (t,) in c.execute("SELECT title FROM tally.kb_documents")}
        assert "Mayor's Management Report, Fiscal 2025" not in docs
    finally:
        c.close(); admin.execute(f"DROP ROLE {name}")
