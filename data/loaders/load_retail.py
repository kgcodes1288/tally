#!/usr/bin/env python3
"""Online Retail workspace: Olist Brazilian e-commerce (Kaggle, CC BY-NC-SA 4.0), about 100K orders 2016-2018.

Customer-side tables carry customer_state (two-letter Brazilian state) as the scope column; sellers are scoped by
seller_state. Products, category names and zip geolocation are shared reference data (no row-level security).
Review text is in Portuguese.
"""
import duckdb
from common import RAW, connect, load_table, persona, secure

WS = "ws_retail"
R = RAW / "olist"


def csv(name):
    return f"read_csv('{R / name}', header=true, sample_size=-1)"


def main():
    pg = connect(); con = duckdb.connect()
    pg.execute(f"CREATE SCHEMA IF NOT EXISTS {WS}")
    pg.execute("""INSERT INTO tally.workspaces (id, name, description, scope_label) VALUES (%s,%s,%s,%s)
                  ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, description=EXCLUDED.description, scope_label=EXCLUDED.scope_label""",
               (WS, "Online Retail", "Olist, a Brazilian e-commerce marketplace: about 100K orders (2016 to 2018) with items, payments, reviews, sellers and products.", "state"))
    personas = [("p_ret_sp", "São Paulo regional manager", "Customers and sellers in São Paulo state (SP).", ["SP"]),
                ("p_ret_rj", "Rio de Janeiro regional manager", "Customers and sellers in Rio de Janeiro state (RJ).", ["RJ"]),
                ("p_ret_south", "South region manager", "Customers and sellers in Paraná, Santa Catarina and Rio Grande do Sul (PR, SC, RS).", ["PR", "SC", "RS"]),
                ("p_ret_finance", "Head of finance", "All regions, for company-wide payment and revenue analysis.", None)]
    for role, title, desc, scopes in personas:
        persona(pg, WS, role, title, desc, scopes)
    roles = [p[0] for p in personas]

    con.sql(f"CREATE TABLE cust AS SELECT * FROM {csv('olist_customers_dataset.csv')}")
    con.sql(f"CREATE TABLE ord AS SELECT o.*, c.customer_state FROM {csv('olist_orders_dataset.csv')} o JOIN cust c USING (customer_id)")
    st = "SELECT order_id, customer_state FROM ord"
    tables = {
        "customers": ("SELECT * FROM cust", "customer_state",
                      "One row per order-level customer id. customer_unique_id identifies the person across orders."),
        "orders": ("SELECT * FROM ord", "customer_state",
                   "Order header: status and purchase, approval, carrier, delivery and estimated-delivery timestamps."),
        "order_items": (f"SELECT i.*, s.customer_state FROM {csv('olist_order_items_dataset.csv')} i JOIN ({st}) s USING (order_id)", "customer_state",
                        "One row per item in an order: product, seller, price and freight. Order total = sum(price + freight_value)."),
        "order_payments": (f"SELECT p.*, s.customer_state FROM {csv('olist_order_payments_dataset.csv')} p JOIN ({st}) s USING (order_id)", "customer_state",
                           "Payments per order (an order can be paid in several parts and installments). payment_value is in BRL."),
        "order_reviews": (f"SELECT r.*, s.customer_state FROM {csv('olist_order_reviews_dataset.csv')} r JOIN ({st}) s USING (order_id)", "customer_state",
                          "Customer reviews, score 1 to 5, free text in Portuguese."),
        "sellers": (f"SELECT * FROM {csv('olist_sellers_dataset.csv')}", "seller_state",
                    "Sellers on the marketplace and their location."),
    }
    for t, (q, scope, comment) in tables.items():
        load_table(pg, con, q, WS, t, comment)
        secure(pg, WS, t, scope, roles)

    reference = {
        "products": (f"SELECT p.*, t.product_category_name_english FROM {csv('olist_products_dataset.csv')} p "
                     f"LEFT JOIN {csv('product_category_name_translation.csv')} t USING (product_category_name)",
                     "Product catalog (shared reference data) with English category names."),
        "geolocation": (f"SELECT geolocation_zip_code_prefix AS zip_code_prefix, avg(geolocation_lat) AS lat, avg(geolocation_lng) AS lng, "
                        f"any_value(geolocation_city) AS city, any_value(geolocation_state) AS state "
                        f"FROM {csv('olist_geolocation_dataset.csv')} GROUP BY 1",
                        "Approximate coordinates per 5-digit zip prefix (shared reference data)."),
    }
    for t, (q, comment) in reference.items():
        load_table(pg, con, q, WS, t, comment)
        for r in roles:
            pg.execute(f"GRANT SELECT ON {WS}.{t} TO {r}")

    for t, c in [("orders", "order_id"), ("order_items", "order_id"), ("order_payments", "order_id"),
                 ("order_reviews", "order_id"), ("customers", "customer_id")]:
        pg.execute(f"CREATE INDEX ON {WS}.{t} ({c})")
    pg.execute("ANALYZE")
    print("retail workspace ready")


if __name__ == "__main__":
    main()
