"""
Olist 数据监控脚本
每日自动检查核心指标是否异常偏离，输出结构化监控报告。
用法：python monitor.py
返回：0 = 全部正常，1 = 存在异常
"""
import sys
import io

# Windows 下强制 UTF-8 编码，避免 emoji 输出报错
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import sqlite3
import os
from datetime import datetime, timedelta, date

# ==================== 配置 ====================
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "olist.db")
BASELINE_DAYS = 30          # 对比基准天数
MIN_BASELINE_DAYS = 5       # 基准天数不足时的最低阈值
OUTLIER_THRESHOLD = 100000  # 排除极限值的金额上限

# 异常阈值
THRESHOLD_SALES_RATIO = 0.70     # 销售额低于基准 70%
THRESHOLD_ORDERS_RATIO = 0.60    # 订单量低于基准 60%
THRESHOLD_LOGISTICS_DELTA = 3    # 物流天数超出基准 3 天
THRESHOLD_MAX_AMOUNT_RATIO = 5.0 # 最大单笔超过基准 5 倍


def get_db_connection():
    """建立数据库连接，失败返回 None"""
    try:
        if not os.path.exists(DB_PATH):
            print(f"[ERROR] 数据库文件不存在：{DB_PATH}")
            return None
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row  # 字典式返回
        return conn
    except sqlite3.Error as e:
        print(f"[ERROR] 数据库连接失败：{e}")
        return None


def get_latest_date(conn):
    """获取数据集中最新日期作为「昨天」"""
    row = conn.execute(
        "SELECT DATE(MAX(purchase_time)) AS latest FROM fact_order"
    ).fetchone()
    return row["latest"] if row and row["latest"] else None


def fetch_baseline(conn, target_date_str):
    """
    计算过去 N 天的基准数据。
    基准区间 = target_date - BASELINE_DAYS 到 target_date - 1 天。
    排除 total_price > OUTLIER_THRESHOLD 的异常订单。
    如果有效天数不足 MIN_BASELINE_DAYS，则扩大到全部历史数据。
    """
    start = date.fromisoformat(target_date_str) - timedelta(days=BASELINE_DAYS)
    start_str = start.isoformat()
    # 目标日期往前推1天作为基准结束日
    end = date.fromisoformat(target_date_str) - timedelta(days=1)
    end_str = end.isoformat()

    # 先检查基准区间有多少天的数据
    day_count = conn.execute("""
        SELECT COUNT(DISTINCT DATE(purchase_time)) AS cnt
        FROM fact_order
        WHERE DATE(purchase_time) BETWEEN ? AND ?
          AND order_total_amount <= ?
    """, (start_str, end_str, OUTLIER_THRESHOLD)).fetchone()["cnt"]

    use_all_history = (day_count < MIN_BASELINE_DAYS)

    if use_all_history:
        print(f"  [INFO] 过去30天仅 {day_count} 天有数据，使用全部历史数据作为基准")
        baseline_agg = conn.execute("""
            SELECT
                COUNT(DISTINCT DATE(purchase_time)) AS total_days,
                SUM(order_total_amount) AS total_sales,
                COUNT(DISTINCT order_id) AS total_orders,
                AVG(logistics_days) AS avg_logistics,
                MAX(order_total_amount) AS max_amount
            FROM fact_order
            WHERE DATE(purchase_time) < ?
              AND order_total_amount <= ?
        """, (target_date_str, OUTLIER_THRESHOLD)).fetchone()
    else:
        baseline_agg = conn.execute("""
            SELECT
                COUNT(DISTINCT DATE(purchase_time)) AS total_days,
                SUM(order_total_amount) AS total_sales,
                COUNT(DISTINCT order_id) AS total_orders,
                AVG(logistics_days) AS avg_logistics,
                MAX(order_total_amount) AS max_amount
            FROM fact_order
            WHERE DATE(purchase_time) BETWEEN ? AND ?
              AND order_total_amount <= ?
        """, (start_str, end_str, OUTLIER_THRESHOLD)).fetchone()

    total_days = baseline_agg["total_days"] or 1
    daily_avg_sales = (baseline_agg["total_sales"] or 0) / total_days
    daily_avg_orders = (baseline_agg["total_orders"] or 0) / total_days

    return {
        "total_days": total_days,
        "use_all_history": use_all_history,
        "daily_avg_sales": daily_avg_sales,
        "daily_avg_orders": daily_avg_orders,
        "avg_logistics": baseline_agg["avg_logistics"] or 0,
        "max_amount": baseline_agg["max_amount"] or 0,
    }


def check_today(conn, target_date_str):
    """获取昨日的各项实际指标"""
    row = conn.execute("""
        SELECT
            SUM(order_total_amount) AS total_sales,
            COUNT(DISTINCT order_id) AS total_orders,
            AVG(logistics_days) AS avg_logistics,
            MAX(order_total_amount) AS max_amount,
            SUM(CASE WHEN order_total_amount < 0 THEN 1 ELSE 0 END) AS negative_orders
        FROM fact_order
        WHERE DATE(purchase_time) = ?
    """, (target_date_str,)).fetchone()
    return row


# ==================== 主流程 ====================
def main():
    print("=" * 60)
    print("  Olist 数据监控报告")
    print(f"  执行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 连接数据库
    conn = get_db_connection()
    if conn is None:
        sys.exit(1)
    print("[OK] 数据库连接成功")

    # 2. 确定目标日期（数据集最新日期 = "昨天"）
    target_date = get_latest_date(conn)
    if target_date is None:
        print("[ERROR] 无法获取最新数据日期")
        conn.close()
        sys.exit(1)
    print(f"[INFO] 监控目标日期：{target_date}（数据集最新日期）")

    # 3. 计算基准
    print(f"\n[INFO] 计算过去 {BASELINE_DAYS} 天基准数据...")
    baseline = fetch_baseline(conn, target_date)

    # 4. 获取昨日实际指标
    today = check_today(conn, target_date)
    conn.close()

    if today["total_orders"] is None or today["total_orders"] == 0:
        print(f"[WARN] {target_date} 无订单数据，跳过监控")
        sys.exit(0)

    # 5. 逐项检查
    print(f"\n{'─' * 60}")
    print(f"  指标                       实际值              基准值              状态")
    print(f"{'─' * 60}")

    anomaly_count = 0

    # --- 指标1：昨日销售额 ---
    sales_actual = today["total_sales"] or 0
    sales_threshold = baseline["daily_avg_sales"] * THRESHOLD_SALES_RATIO
    sales_ok = sales_actual >= sales_threshold
    status = "✅ 正常" if sales_ok else "❌ 异常"
    if not sales_ok:
        anomaly_count += 1
    pct = (sales_actual / baseline["daily_avg_sales"] * 100) if baseline["daily_avg_sales"] > 0 else 0
    print(f"  昨日销售额                 R$ {sales_actual:>12,.0f}   R$ {sales_threshold:>10,.0f}   {status}  ({pct:.0f}% of 日均)")
    if not sales_ok:
        print(f"    → [DETAIL] 昨日销售额 R$ {sales_actual:,.0f} 低于基准日均 R$ {baseline['daily_avg_sales']:,.0f} 的 {THRESHOLD_SALES_RATIO*100:.0f}% (={sales_threshold:,.0f})")

    # --- 指标2：昨日订单量 ---
    orders_actual = today["total_orders"] or 0
    orders_threshold = baseline["daily_avg_orders"] * THRESHOLD_ORDERS_RATIO
    orders_ok = orders_actual >= orders_threshold
    status = "✅ 正常" if orders_ok else "❌ 异常"
    if not orders_ok:
        anomaly_count += 1
    pct = (orders_actual / baseline["daily_avg_orders"] * 100) if baseline["daily_avg_orders"] > 0 else 0
    print(f"  昨日订单量                 {orders_actual:>12,.0f}   {orders_threshold:>10,.0f}   {status}  ({pct:.0f}% of 日均)")
    if not orders_ok:
        print(f"    → [DETAIL] 昨日订单量 {orders_actual:,} 低于基准日均 {baseline['daily_avg_orders']:,.0f} 的 {THRESHOLD_ORDERS_RATIO*100:.0f}% (={orders_threshold:,.0f})")

    # --- 指标3：平均物流天数 ---
    logistics_actual = today["avg_logistics"] or 0
    logistics_threshold = (baseline["avg_logistics"] or 0) + THRESHOLD_LOGISTICS_DELTA
    logistics_ok = logistics_actual <= logistics_threshold
    status = "✅ 正常" if logistics_ok else "❌ 异常"
    if not logistics_ok:
        anomaly_count += 1
    print(f"  平均物流天数               {logistics_actual:>12.1f} 天  {logistics_threshold:>10.1f} 天   {status}")
    if not logistics_ok:
        print(f"    → [DETAIL] 昨日物流 {logistics_actual:.1f} 天，超出基准 {baseline['avg_logistics']:.1f} 天 + {THRESHOLD_LOGISTICS_DELTA} 天")

    # --- 指标4：最大单笔金额 ---
    max_actual = today["max_amount"] or 0
    max_threshold = (baseline["max_amount"] or 1) * THRESHOLD_MAX_AMOUNT_RATIO
    max_ok = max_actual <= max_threshold
    status = "✅ 正常" if max_ok else "❌ 异常"
    if not max_ok:
        anomaly_count += 1
    print(f"  最大单笔金额               R$ {max_actual:>12,.0f}   R$ {max_threshold:>10,.0f}   {status}")
    if not max_ok:
        print(f"    → [DETAIL] 最大单笔 R$ {max_actual:,.0f} 超过基准最大值 R$ {baseline['max_amount']:,.0f} 的 {THRESHOLD_MAX_AMOUNT_RATIO:.0f} 倍")

    # --- 指标5：负金额订单 ---
    neg_actual = today["negative_orders"] or 0
    neg_ok = neg_actual == 0
    status = "✅ 正常" if neg_ok else "❌ 异常"
    if not neg_ok:
        anomaly_count += 1
    print(f"  负金额订单                 {neg_actual:>12} 笔  0 笔             {status}")
    if not neg_ok:
        print(f"    → [DETAIL] 存在 {neg_actual} 笔负金额订单，可能为退款/系统错误")

    # 6. 汇总
    print(f"\n{'─' * 60}")
    if anomaly_count == 0:
        print("  🟢 全部正常：5/5 项指标通过检查")
    else:
        print(f"  🔴 存在异常：{anomaly_count}/5 项指标未通过检查")
    print(f"{'─' * 60}")
    print()

    conn.close() if hasattr(sys.modules.get('sqlite3.Connection', None), 'close') else None
    sys.exit(1 if anomaly_count > 0 else 0)


if __name__ == "__main__":
    main()
