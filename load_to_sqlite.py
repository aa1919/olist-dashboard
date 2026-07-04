"""
Olist 电商数据集 → SQLite 数据库
一键加载 9 张 CSV，建立外键关联，存入 olist.db
"""
import os
import sqlite3
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "olist.db")

# ===== 1. 读取全部 CSV =====
datasets = {}
csv_files = {
    "customers":        "olist_customers_dataset.csv",
    "geolocation":      "olist_geolocation_dataset.csv",
    "order_items":      "olist_order_items_dataset.csv",
    "order_payments":   "olist_order_payments_dataset.csv",
    "order_reviews":    "olist_order_reviews_dataset.csv",
    "orders":           "olist_orders_dataset.csv",
    "products":         "olist_products_dataset.csv",
    "sellers":          "olist_sellers_dataset.csv",
    "category_trans":   "product_category_name_translation.csv",
}

for name, filename in csv_files.items():
    path = os.path.join(BASE_DIR, filename)
    if os.path.exists(path):
        datasets[name] = pd.read_csv(path)
        print(f"[OK] {name:18s}  {len(datasets[name]):>10,} 行  |  {filename}")
    else:
        print(f"[!!] {name:18s}  文件不存在: {filename}")

# ===== 2. 写入 SQLite =====
conn = sqlite3.connect(DB_PATH)

for name, df in datasets.items():
    df.to_sql(name, conn, if_exists="replace", index=False)
    print(f"[DB] 写入表: {name}")

# ===== 3. 建立索引（加速关联查询） =====
indexes = [
    "CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_order     ON order_items(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_product   ON order_items(product_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_seller    ON order_items(seller_id)",
    "CREATE INDEX IF NOT EXISTS idx_payments_order  ON order_payments(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_order   ON order_reviews(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_geo_zip         ON geolocation(geolocation_zip_code_prefix)",
    "CREATE INDEX IF NOT EXISTS idx_customers_zip   ON customers(customer_zip_code_prefix)",
    "CREATE INDEX IF NOT EXISTS idx_sellers_zip     ON sellers(seller_zip_code_prefix)",
]

for sql in indexes:
    conn.execute(sql)

conn.commit()

# ===== 4. 写入关联视图（方便直接查询） =====
view_sql = """
CREATE VIEW IF NOT EXISTS v_order_full AS
SELECT
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.customer_city,
    c.customer_state,
    o.order_status,
    o.order_purchase_timestamp,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,
    oi.order_item_id,
    oi.product_id,
    p.product_category_name,
    ct.product_category_name_english,
    oi.seller_id,
    s.seller_city,
    s.seller_state,
    oi.price,
    oi.freight_value,
    oi.price + oi.freight_value AS item_total,
    pay.payment_type,
    pay.payment_installments,
    pay.payment_value,
    rev.review_score
FROM orders o
LEFT JOIN customers c          ON o.customer_id = c.customer_id
LEFT JOIN order_items oi       ON o.order_id = oi.order_id
LEFT JOIN products p           ON oi.product_id = p.product_id
LEFT JOIN category_trans ct    ON p.product_category_name = ct.product_category_name
LEFT JOIN sellers s            ON oi.seller_id = s.seller_id
LEFT JOIN order_payments pay   ON o.order_id = pay.order_id AND pay.payment_sequential = 1
LEFT JOIN order_reviews rev    ON o.order_id = rev.order_id
"""
conn.execute(view_sql)
conn.commit()
conn.close()

# ===== 5. 验证 =====
print(f"\n[OK] 数据库路径: {DB_PATH}")
conn = sqlite3.connect(DB_PATH)
tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", conn)
print(f"[DB] 表数量: {len(tables)}")
for _, row in tables.iterrows():
    cnt = pd.read_sql(f"SELECT COUNT(*) AS n FROM [{row['name']}]", conn).iloc[0, 0]
    print(f"   {row['name']:25s} {cnt:>10,} 行")
view_cnt = pd.read_sql("SELECT COUNT(*) AS n FROM v_order_full", conn).iloc[0, 0]
print(f"   {'v_order_full (视图)':25s} {view_cnt:>10,} 行")
conn.close()
print("\n[DONE] 全部完成！")
