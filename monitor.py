"""
Olist 数据监控脚本
每日自动检查核心指标是否异常偏离，输出结构化监控报告。
检测到异常时自动发送邮件告警。
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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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

# ==================== 邮件告警配置 ====================
# 请修改为你的邮箱信息，发件人和收件人可以是同一个邮箱
EMAIL_CONFIG = {
    "smtp_server": "smtp.qq.com",      # QQ邮箱 SMTP 服务器
    "smtp_port": 465,                   # SSL 端口
    "sender_email": "your_email@qq.com",# 发件邮箱
    "sender_password": "授权码",         # QQ邮箱 → 设置 → 账户 → POP3/SMTP 服务 → 生成授权码
    "receiver_email": "your_email@qq.com",# 收件邮箱（可与发件相同）
    "enabled": True,                    # False=仅控制台输出，不发送邮件
}

# 获取QQ邮箱授权码（16位字符）：
#   https://service.mail.qq.com → 设置 → 账户 → POP3/IMAP/SMTP服务 → 开启并生成
# 其他邮箱配置参考：
#   163邮箱：smtp_server="smtp.163.com", smtp_port=465
#   Gmail：  smtp_server="smtp.gmail.com", smtp_port=587，需开启两步验证并使用应用专用密码


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


def send_alert_email(anomaly_count, anomaly_details, target_date, report_text):
    """
    发送异常告警邮件。
    anomaly_count: 异常指标数量（0 时不发送）
    anomaly_details: [(指标名, 实际值, 基准值, 状态描述), ...]
    target_date: 监控目标日期
    report_text: 完整报告文本（作为邮件备用内容）
    """
    if not EMAIL_CONFIG.get("enabled", False):
        print("\n[INFO] 邮件告警未启用（EMAIL_CONFIG['enabled']=False），跳过发送")
        return False

    if anomaly_count == 0:
        return False  # 全部正常时不发邮件

    try:
        # 构建 HTML 邮件正文
        subject = f"⚠️ Olist 数据监控告警 - {target_date}（{anomaly_count}/5 项异常）"

        # 状态行颜色
        rows_html = ""
        for name, actual, baseline, status_text, is_ok in anomaly_details:
            row_color = "#d4edda" if is_ok else "#f8d7da"
            row_icon = "✅" if is_ok else "❌"
            rows_html += f"""
            <tr style="background:{row_color}">
                <td style="padding:8px 12px;border:1px solid #ddd">{row_icon} {name}</td>
                <td style="padding:8px 12px;border:1px solid #ddd;text-align:right">{actual}</td>
                <td style="padding:8px 12px;border:1px solid #ddd;text-align:right">{baseline}</td>
                <td style="padding:8px 12px;border:1px solid #ddd">{status_text}</td>
            </tr>"""

        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
            <h2 style="color:#e74c3c">⚠️ Olist 数据监控告警</h2>
            <p>监控日期：<b>{target_date}</b> | 执行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <table style="width:100%;border-collapse:collapse;margin:16px 0">
                <tr style="background:#f5f5f5">
                    <th style="padding:8px 12px;border:1px solid #ddd;text-align:left">指标</th>
                    <th style="padding:8px 12px;border:1px solid #ddd;text-align:right">实际值</th>
                    <th style="padding:8px 12px;border:1px solid #ddd;text-align:right">基准值</th>
                    <th style="padding:8px 12px;border:1px solid #ddd">状态</th>
                </tr>
                {rows_html}
            </table>
            <p style="color:#888">共检查 5 项指标，其中 <b style="color:#e74c3c">{anomaly_count} 项</b> 触发告警。</p>
            <hr style="border:1px solid #eee">
            <p style="color:#aaa;font-size:12px">此邮件由 Olist 数据监控脚本自动发送，请勿回复。</p>
        </div>"""

        # 组装邮件
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_CONFIG["sender_email"]
        msg["To"] = EMAIL_CONFIG["receiver_email"]
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # 发送
        with smtplib.SMTP_SSL(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"]) as server:
            server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
            server.sendmail(EMAIL_CONFIG["sender_email"], [EMAIL_CONFIG["receiver_email"]], msg.as_string())

        print(f"\n📧 异常告警邮件已发送至 {EMAIL_CONFIG['receiver_email']}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("\n[ERROR] 邮件发送失败：认证错误，请检查邮箱地址和授权码是否正确")
        return False
    except smtplib.SMTPConnectError:
        print("\n[ERROR] 邮件发送失败：无法连接SMTP服务器，请检查网络和端口")
        return False
    except Exception as e:
        print(f"\n[ERROR] 邮件发送失败：{e}")
        return False


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
    anomaly_details = []  # 收集每项指标的结果

    # --- 指标1：昨日销售额 ---
    sales_actual = today["total_sales"] or 0
    sales_threshold = baseline["daily_avg_sales"] * THRESHOLD_SALES_RATIO
    sales_ok = sales_actual >= sales_threshold
    status = "✅ 正常" if sales_ok else "❌ 异常"
    if not sales_ok:
        anomaly_count += 1
    pct = (sales_actual / baseline["daily_avg_sales"] * 100) if baseline["daily_avg_sales"] > 0 else 0
    anomaly_details.append((
        "昨日销售额",
        f"R$ {sales_actual:,.0f}",
        f"R$ {sales_threshold:,.0f}",
        f"仅为日均的 {pct:.0f}%" if not sales_ok else f"日均的 {pct:.0f}%",
        sales_ok,
    ))
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
    anomaly_details.append((
        "昨日订单量",
        f"{orders_actual:,} 笔",
        f"{orders_threshold:,.0f} 笔",
        f"仅为日均的 {pct:.0f}%" if not orders_ok else f"日均的 {pct:.0f}%",
        orders_ok,
    ))
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
    anomaly_details.append((
        "平均物流天数",
        f"{logistics_actual:.1f} 天",
        f"{logistics_threshold:.1f} 天",
        f"超出基准 {logistics_actual - baseline['avg_logistics']:.1f} 天" if not logistics_ok else "在合理范围",
        logistics_ok,
    ))
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
    ratio_str = f"超基准 {max_actual / (baseline['max_amount'] or 1):.0f} 倍" if not max_ok else "在合理范围"
    anomaly_details.append((
        "最大单笔金额",
        f"R$ {max_actual:,.0f}",
        f"R$ {max_threshold:,.0f}",
        ratio_str,
        max_ok,
    ))
    print(f"  最大单笔金额               R$ {max_actual:>12,.0f}   R$ {max_threshold:>10,.0f}   {status}")
    if not max_ok:
        print(f"    → [DETAIL] 最大单笔 R$ {max_actual:,.0f} 超过基准最大值 R$ {baseline['max_amount']:,.0f} 的 {THRESHOLD_MAX_AMOUNT_RATIO:.0f} 倍")

    # --- 指标5：负金额订单 ---
    neg_actual = today["negative_orders"] or 0
    neg_ok = neg_actual == 0
    status = "✅ 正常" if neg_ok else "❌ 异常"
    if not neg_ok:
        anomaly_count += 1
    anomaly_details.append((
        "负金额订单",
        f"{neg_actual} 笔",
        "0 笔",
        f"存在 {neg_actual} 笔异常" if not neg_ok else "无异常",
        neg_ok,
    ))
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

    # 7. 发送邮件告警（仅在异常时发送）
    if anomaly_count > 0:
        send_alert_email(anomaly_count, anomaly_details, target_date, "")

    sys.exit(1 if anomaly_count > 0 else 0)


if __name__ == "__main__":
    main()
