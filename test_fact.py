"""Test: Generate fact_order from Olist data."""
import sqlite3, pandas as pd, numpy as np
from collections import Counter

DB_PATH = r'c:\Users\Luminous\Desktop\项目\数据看板与监控\olist.db'
conn = sqlite3.connect(DB_PATH)

orders      = pd.read_sql('SELECT * FROM orders', conn)
order_items = pd.read_sql('SELECT * FROM order_items', conn)
order_pay   = pd.read_sql('SELECT * FROM order_payments', conn)
products    = pd.read_sql('SELECT * FROM products', conn)
customers   = pd.read_sql('SELECT * FROM customers', conn)
sellers     = pd.read_sql('SELECT * FROM sellers', conn)
cat_trans   = pd.read_sql('SELECT * FROM category_trans', conn)
conn.close()

# 1. orders
date_cols = ['order_purchase_timestamp','order_approved_at',
             'order_delivered_carrier_date','order_delivered_customer_date',
             'order_estimated_delivery_date']
for col in date_cols:
    orders[col] = pd.to_datetime(orders[col], errors='coerce')
p = orders['order_purchase_timestamp']
orders['purchase_year'] = p.dt.year
orders['purchase_month'] = p.dt.month
orders['purchase_quarter'] = p.dt.quarter
orders['purchase_weekday'] = p.dt.day_name()
orders['purchase_ym'] = p.dt.strftime('%Y-%m')
orders['logistics_days'] = (orders['order_delivered_customer_date'] - p).dt.days
orders['order_status_cn'] = orders['order_status'].apply(
    lambda s: '已完成' if s == 'delivered' else ('已取消' if s == 'canceled' else '其他')
)

# 2. order_items aggregation
order_agg = order_items.groupby('order_id').agg(
    order_item_count=('order_item_id', 'count'),
    order_total_price=('price', 'sum'),
    order_freight=('freight_value', 'sum')
).reset_index()
order_agg['order_total_amount'] = order_agg['order_total_price'] + order_agg['order_freight']

# 3. customer RFM
cp = orders[['order_id', 'customer_id', 'order_purchase_timestamp']].merge(
    order_agg[['order_id', 'order_total_amount']], on='order_id', how='inner'
)
customer_stats = cp.groupby('customer_id').agg(
    first_purchase_date=('order_purchase_timestamp', 'min'),
    last_purchase_date=('order_purchase_timestamp', 'max'),
    purchase_frequency=('order_id', 'count'),
    total_spent=('order_total_amount', 'sum'),
    avg_order_value=('order_total_amount', 'mean'),
).reset_index()

# 4. products + category translation
products = products.merge(cat_trans, on='product_category_name', how='left')
products['product_category_name_english'] = products['product_category_name_english'].fillna('unknown')

# 5. Build fact_order
fact = order_items.copy()

# -- order_dim (separate copy + rename to avoid pandas chain bugs) --
order_dim = orders[[
    'order_id', 'customer_id', 'order_purchase_timestamp',
    'logistics_days', 'order_status_cn',
    'purchase_year', 'purchase_month', 'purchase_quarter',
    'purchase_weekday', 'purchase_ym'
]].copy()
order_dim = order_dim.rename(columns={'order_purchase_timestamp': 'purchase_time'})
print(f"order_dim columns ({len(order_dim.columns)}): {list(order_dim.columns)}")
print(f"Duplicates in order_dim: {order_dim.columns.duplicated().sum()}")

fact = fact.merge(order_dim, on='order_id', how='left')
print(f"After order_dim merge: {len(fact.columns)} cols, dups: {fact.columns.duplicated().sum()}")

fact = fact.merge(order_agg, on='order_id', how='left')
print(f"After order_agg merge: {len(fact.columns)} cols, dups: {fact.columns.duplicated().sum()}")

first_payment = order_pay[order_pay['payment_sequential'] == 1][
    ['order_id', 'payment_type', 'payment_installments', 'payment_value']
]
fact = fact.merge(first_payment, on='order_id', how='left')
print(f"After payment merge: {len(fact.columns)} cols, dups: {fact.columns.duplicated().sum()}")

product_dim = products[['product_id', 'product_category_name_english',
                         'product_weight_g', 'product_length_cm',
                         'product_height_cm', 'product_width_cm']]
fact = fact.merge(product_dim, on='product_id', how='left')
print(f"After product merge: {len(fact.columns)} cols, dups: {fact.columns.duplicated().sum()}")

seller_dim = sellers[['seller_id', 'seller_city', 'seller_state']]
fact = fact.merge(seller_dim, on='seller_id', how='left')
print(f"After seller merge: {len(fact.columns)} cols, dups: {fact.columns.duplicated().sum()}")

customer_dim = customers[['customer_id', 'customer_unique_id',
                           'customer_city', 'customer_state']]
fact = fact.merge(customer_dim, on='customer_id', how='left')
print(f"After customer_dim merge: {len(fact.columns)} cols, dups: {fact.columns.duplicated().sum()}")

fact = fact.merge(customer_stats, on='customer_id', how='left')
print(f"After customer_stats merge: {len(fact.columns)} cols, dups: {fact.columns.duplicated().sum()}")

# Show duplicates before dedup
dup_list = list(fact.columns[fact.columns.duplicated()])
print(f"\nDuplicate column names: {dup_list}")
col_counter = Counter(fact.columns)
multi = {k: v for k, v in col_counter.items() if v > 1}
print(f"Column name counts > 1: {multi}")

# Dedup
fact = fact.loc[:, ~fact.columns.duplicated(keep='first')]
print(f"After dedup: {len(fact.columns)} cols")

# 6. Write to SQLite
conn2 = sqlite3.connect(DB_PATH)
fact.to_sql('fact_order', conn2, if_exists='replace', index=False)
conn2.execute("CREATE INDEX IF NOT EXISTS idx_fact_order_id ON fact_order(order_id)")
conn2.execute("CREATE INDEX IF NOT EXISTS idx_fact_customer ON fact_order(customer_id)")
conn2.execute("CREATE INDEX IF NOT EXISTS idx_fact_product ON fact_order(product_id)")
conn2.execute("CREATE INDEX IF NOT EXISTS idx_fact_date ON fact_order(purchase_ym)")
conn2.execute("CREATE INDEX IF NOT EXISTS idx_fact_category ON fact_order(product_category_name_english)")
conn2.commit()
conn2.close()

print(f"\n[DONE] fact_order: {len(fact):,} rows, {len(fact.columns)} cols")
print(f"Orders: {fact['order_id'].nunique():,}, Customers: {fact['customer_id'].nunique():,}")
