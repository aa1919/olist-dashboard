"""
Olist 电商经营决策看板
基于 fact_order 宽表，使用 Streamlit + Plotly 构建交互式仪表盘
"""
import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os

# ==================== 页面配置 ====================
st.set_page_config(
    page_title="Olist 经营决策看板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== 数据加载 ====================
@st.cache_data(ttl=600)
def load_data():
    """从 SQLite 加载 fact_order 宽表并预处理时间字段"""
    db_path = os.path.join(os.path.dirname(__file__), "olist.db")
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT * FROM fact_order", conn)
    conn.close()

    # 时间字段转换
    df['purchase_time'] = pd.to_datetime(df['purchase_time'])
    df['first_purchase_date'] = pd.to_datetime(df['first_purchase_date'])
    df['last_purchase_date'] = pd.to_datetime(df['last_purchase_date'])
    df['purchase_month'] = df['purchase_time'].dt.to_period('M').astype(str)

    return df


# 巴西各州中心坐标（纬度, 经度），用于气泡地图
BRAZIL_STATE_COORDS = {
    'AC': (-9.0, -70.0), 'AL': (-9.6, -36.5), 'AP': (1.4, -51.8),
    'AM': (-3.0, -61.0), 'BA': (-12.5, -41.5), 'CE': (-5.5, -39.3),
    'DF': (-15.8, -47.9), 'ES': (-19.2, -40.3), 'GO': (-15.9, -49.8),
    'MA': (-5.0, -45.0), 'MT': (-12.5, -55.5), 'MS': (-20.5, -55.0),
    'MG': (-18.5, -44.5), 'PA': (-3.5, -53.0), 'PB': (-7.2, -36.5),
    'PR': (-24.5, -51.0), 'PE': (-8.3, -37.5), 'PI': (-7.0, -42.5),
    'RJ': (-22.0, -42.5), 'RN': (-5.8, -36.5), 'RS': (-30.0, -53.0),
    'RO': (-10.0, -63.0), 'RR': (2.8, -61.0), 'SC': (-27.0, -50.0),
    'SP': (-22.5, -48.0), 'SE': (-10.5, -37.5), 'TO': (-9.5, -48.5),
}


def fmt_currency(value):
    """大额数字缩写格式化，避免 st.metric 卡片中显示省略号"""
    abs_v = abs(value)
    if abs_v >= 1e6:
        return f"R$ {value/1e6:.1f}M"
    elif abs_v >= 1e3:
        return f"R$ {value/1e3:.0f}K"
    else:
        return f"R$ {value:,.0f}"


def fmt_number(value):
    """数字缩写格式化"""
    abs_v = abs(value)
    if abs_v >= 1e6:
        return f"{value/1e6:.1f}M"
    elif abs_v >= 1e3:
        return f"{value/1e3:.0f}K"
    else:
        return f"{value:,.0f}"


# ==================== 加载数据 ====================
with st.spinner("正在加载数据..."):
    df_all = load_data()

data_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ==================== 侧边栏筛选器 ====================
st.sidebar.header("🔍 筛选条件")

# 预处理月份列表
all_months = sorted(df_all['purchase_month'].unique())
valid_months = [m for m in all_months if df_all[df_all['purchase_month'] == m]['order_id'].nunique() >= 100]

# ---- 月度 GMV 汇总 ----
monthly_gmv = df_all.groupby('purchase_month')['order_total_amount'].sum()

# 峰值月：valid_months 中 GMV 最高的月份
valid_gmv = monthly_gmv.loc[monthly_gmv.index.isin(valid_months)]
peak_month = valid_gmv.idxmax()
peak_gmv = valid_gmv.max()

# 低谷月：排除销售额为0或不完整的月份
nonzero_gmv = valid_gmv[valid_gmv > 0]
valley_month = nonzero_gmv.idxmin()
valley_gmv = nonzero_gmv.min()

# ---- 初始化 session_state ----
if 'selected_period' not in st.session_state:
    st.session_state.selected_period = "📊 全部数据"
if 'scroll_month' not in st.session_state:
    # 默认滚动到最后一个可用月份
    st.session_state.scroll_month = valid_months[-1]

# ---- 4 种筛选模式按钮 ----
PERIOD_OPTIONS = {
    "📊 全部数据":   "展示全量数据，适用于整体大盘分析",
    "🏆 销售巅峰月": f"巅峰月：{peak_month}（R$ {peak_gmv/1e6:.1f}M）",
    "📉 销售低谷月": f"低谷月：{valley_month}（R$ {valley_gmv/1e3:.0f}K）",
    "📅 按月滚动":   "选择单个月份逐月对比",
}

# 按钮网格（2列布局）
st.sidebar.markdown("##### 筛选模式")
period_names = list(PERIOD_OPTIONS.keys())
for row_idx in range(0, len(period_names), 2):
    c1, c2 = st.sidebar.columns(2)
    for col, idx in [(c1, row_idx), (c2, row_idx + 1)]:
        if idx < len(period_names):
            name = period_names[idx]
            is_active = (st.session_state.selected_period == name)
            btn_type = "primary" if is_active else "secondary"
            with col:
                if st.button(name, key=f"period_{idx}", type=btn_type, use_container_width=True):
                    st.session_state.selected_period = name
                    st.rerun()

# ---- 显示当前模式说明 ----
selected_mode = st.session_state.selected_period
mode_desc = PERIOD_OPTIONS[selected_mode]
if selected_mode in ("🏆 销售巅峰月", "📉 销售低谷月"):
    st.sidebar.caption(f"ℹ️ {mode_desc}")

# ---- 按月滚动：月份选择器 + 导航按钮 ----
if selected_mode == "📅 按月滚动":
    current_idx = valid_months.index(st.session_state.scroll_month)
    st.sidebar.markdown("##### 选择月份")
    c1, c2, c3 = st.sidebar.columns([1, 2, 1])
    
    with c1:
        prev_disabled = (current_idx <= 0)
        if st.button("◀", key="prev_month", disabled=prev_disabled, use_container_width=True):
            st.session_state.scroll_month = valid_months[current_idx - 1]
            st.rerun()
    
    with c2:
        # 下拉选择月份
        selected_month = st.selectbox(
            "月份",
            options=valid_months,
            index=current_idx,
            label_visibility="collapsed",
        )
        if selected_month != st.session_state.scroll_month:
            st.session_state.scroll_month = selected_month
            st.rerun()
    
    with c3:
        next_disabled = (current_idx >= len(valid_months) - 1)
        if st.button("▶", key="next_month", disabled=next_disabled, use_container_width=True):
            st.session_state.scroll_month = valid_months[current_idx + 1]
            st.rerun()
    
    # 高亮显示当前月份信息
    cur_gmv = monthly_gmv.get(st.session_state.scroll_month, 0)
    st.sidebar.markdown(f"""
    <div style="
        background:#e8f4fd;
        border-radius:8px;
        padding:8px 12px;
        margin-top:4px;
        font-size:13px;
        text-align:center;
    ">
        📍 <b>{st.session_state.scroll_month}</b><br>
        <span style="color:#1a73e8;">R$ {cur_gmv/1e3:,.0f}K</span>
    </div>
    """, unsafe_allow_html=True)

# ---- 根据模式确定起止月 ----
if selected_mode == "📅 按月滚动":
    start_month = st.session_state.scroll_month
    end_month = st.session_state.scroll_month
    period_desc = f"单月：{start_month}"
elif selected_mode == "📊 全部数据":
    start_month, end_month = valid_months[0], valid_months[-1]
    period_desc = "全部历史数据"
elif selected_mode == "🏆 销售巅峰月":
    start_month = end_month = peak_month
    period_desc = mode_desc
elif selected_mode == "📉 销售低谷月":
    start_month = end_month = valley_month
    period_desc = mode_desc
else:
    start_month, end_month = valid_months[0], valid_months[-1]
    period_desc = "全部历史数据"

# ---- 产品分类筛选 ----
st.sidebar.divider()
st.sidebar.markdown("##### 产品分类")
all_categories = sorted(df_all['product_category_name_english'].dropna().unique())
selected_categories = st.sidebar.multiselect(
    "可多选，留空=全部",
    options=all_categories,
    default=[]
)

# ---- 数据导出按钮 ----
st.sidebar.divider()
st.sidebar.markdown("##### 📥 数据导出")

# 先构建导出用的筛选数据（与主区域一致，但不包括地图州锁定）
export_df = df_all[
    (df_all['purchase_month'] >= start_month) &
    (df_all['purchase_month'] <= end_month)
].copy()
if selected_categories:
    export_df = export_df[export_df['product_category_name_english'].isin(selected_categories)]

csv_data = export_df.to_csv(index=False).encode('utf-8-sig')
file_size_mb = len(csv_data) / (1024 * 1024)
st.sidebar.download_button(
    label=f"📄 下载筛选数据 CSV ({file_size_mb:.1f} MB)",
    data=csv_data,
    file_name=f"olist_{start_month}_{end_month}.csv",
    mime="text/csv",
    use_container_width=True,
)

# ---- 侧边栏底部：当前范围提示 ----
st.sidebar.divider()
st.sidebar.markdown(f"""
<div style="
    background:#e8f4fd;
    border-radius:8px;
    padding:10px 12px;
    font-size:13px;
    line-height:1.6;
">
    <b>📍 当前范围</b><br>
    {start_month} ~ {end_month}<br>
    <span style="color:#666;font-size:12px;">{period_desc}</span>
</div>
""", unsafe_allow_html=True)
if selected_categories:
    st.sidebar.caption(f"已筛选 {len(selected_categories)} 个品类")

# 清除地图州选择
if st.session_state.get('map_selected_states'):
    st.sidebar.warning(f"🔗 已锁定 {len(st.session_state.map_selected_states)} 个州")
    if st.sidebar.button("🔓 清除州筛选", use_container_width=True):
        st.session_state.map_selected_states = []
        st.rerun()


# ==================== 筛选数据 ====================
df = df_all[
    (df_all['purchase_month'] >= start_month) &
    (df_all['purchase_month'] <= end_month)
].copy()

if selected_categories:
    df = df[df['product_category_name_english'].isin(selected_categories)]

if len(df) == 0:
    st.warning("筛选条件下无数据，请调整筛选器。")
    st.stop()


# ==================== 计算指标 ====================
total_gmv = df['order_total_amount'].sum()
total_orders = df['order_id'].nunique()
total_customers = df['customer_id'].nunique()

# 客单价（每笔订单去重）
order_level = df.groupby('order_id')['order_total_amount'].first()
avg_order_value = order_level.mean()

# 复购率（本数据集客户ID已匿名化，仅为演示）
cust_freq = df.groupby('customer_id')['purchase_frequency'].first()
repeat_customers = (cust_freq > 1).sum()
repurchase_rate = repeat_customers / total_customers * 100 if total_customers > 0 else 0

# 物流
delivered = df[df['order_status_cn'] == '已完成']
avg_logistics = delivered['logistics_days'].mean() if len(delivered) > 0 else 0
on_time_count = (delivered['logistics_days'] <= 14).sum() if len(delivered) > 0 else 0
on_time_rate = on_time_count / len(delivered) * 100 if len(delivered) > 0 else 0

# 月度趋势
monthly_trend = df.groupby('purchase_month').agg(
    gmv=('order_total_amount', 'sum'),
    orders=('order_id', 'nunique')
).reset_index().sort_values('purchase_month')

# 分类排行
category_rank = df.groupby('product_category_name_english').agg(
    sales=('order_total_amount', 'sum')
).reset_index().sort_values('sales', ascending=False).head(10)

# 各州销售额
state_sales = df.groupby('customer_state').agg(
    sales=('order_total_amount', 'sum'),
    orders=('order_id', 'nunique')
).reset_index()

# ---- 地图点击状态联动 ----
if 'map_selected_states' not in st.session_state:
    st.session_state.map_selected_states = []

# 检查是否有地图点击选择事件
if 'state_map' in st.session_state:
    sel = st.session_state['state_map'].get('selection', {})
    if sel and sel.get('points'):
        st.session_state.map_selected_states = [p.get('customdata', [''])[0] for p in sel['points'] if p.get('customdata')]

# 应用地图选中的州过滤
if st.session_state.map_selected_states:
    df = df[df['customer_state'].isin(st.session_state.map_selected_states)]
    if len(df) == 0:
        st.warning("所选州在当前筛选条件下无数据。")
        st.session_state.map_selected_states = []
        st.rerun()

# 支付方式
payment_stats = df.groupby('payment_type').agg(
    count=('order_id', 'nunique')
).reset_index()
payment_stats = payment_stats[payment_stats['count'] > 0]

# 物流分段
if len(delivered) > 0:
    bins = [0, 3, 7, 14, 21, 30, 100]
    labels = ['0-3天', '4-7天', '8-14天', '15-21天', '22-30天', '30天+']
    delivered_copy = delivered.copy()
    delivered_copy['logistics_range'] = pd.cut(delivered_copy['logistics_days'], bins=bins, labels=labels)
    logistics_dist = delivered_copy['logistics_range'].value_counts().sort_index().reset_index()
    logistics_dist.columns = ['物流天数', '订单数']


# ==================== 环比基准计算 ====================
def shift_month(ym, offset):
    """月份偏移：shift_month('2017-01', -1) -> '2016-12'"""
    y, m = map(int, ym.split('-'))
    m += offset
    y += (m - 1) // 12
    m = ((m - 1) % 12) + 1
    return f"{y:04d}-{m:02d}"


# 当前选中范围的月份数量
selected_months = [m for m in valid_months if start_month <= m <= end_month]
period_len = len(selected_months)
is_all_data = (selected_mode == "📊 全部数据")

if is_all_data:
    # 全部数据模式：不计算环比
    has_prev = False
else:
    # 上期范围：等长周期，紧邻当期之前
    prev_end = shift_month(start_month, -1)
    prev_start = shift_month(start_month, -period_len)

    df_prev = df_all[
        (df_all['purchase_month'] >= prev_start) &
        (df_all['purchase_month'] <= prev_end)
    ].copy()
    if selected_categories:
        df_prev = df_prev[df_prev['product_category_name_english'].isin(selected_categories)]

    has_prev = len(df_prev) > 0

if has_prev:
    prev_gmv = df_prev['order_total_amount'].sum()
    prev_orders = df_prev['order_id'].nunique()
    prev_order_level = df_prev.groupby('order_id')['order_total_amount'].first()
    prev_aov = prev_order_level.mean()
    prev_cust_freq = df_prev.groupby('customer_id')['purchase_frequency'].first()
    prev_customers = df_prev['customer_id'].nunique()
    prev_repeat = (prev_cust_freq > 1).sum()
    prev_repurchase = prev_repeat / prev_customers * 100 if prev_customers > 0 else 0

    # 各州上期数据
    prev_state = df_prev.groupby('customer_state').agg(
        prev_sales=('order_total_amount', 'sum'),
        prev_orders=('order_id', 'nunique')
    ).reset_index()
    state_sales = state_sales.merge(prev_state, on='customer_state', how='left')
    state_sales['prev_sales'] = state_sales['prev_sales'].fillna(0)
    state_sales['prev_orders'] = state_sales['prev_orders'].fillna(0)
    state_sales['yoy_growth'] = np.where(
        state_sales['prev_sales'] > 0,
        (state_sales['sales'] - state_sales['prev_sales']) / state_sales['prev_sales'] * 100,
        np.nan
    )
else:
    prev_gmv = prev_orders = prev_aov = prev_repurchase = 0
    state_sales['yoy_growth'] = np.nan
    state_sales['prev_sales'] = 0
    state_sales['prev_orders'] = 0


def calc_change(current, previous):
    """
    安全计算环比变化率，返回 dict:
      value   : 变化率数值（可能为 None）
      text    : 显示文字
      status  : 'normal' | 'no_compare' | 'zero_current' | 'extreme'
    """
    if previous is None or previous == 0 or (isinstance(previous, float) and np.isnan(previous)):
        return {'value': None, 'text': '无同期对比', 'status': 'no_compare'}
    if current == 0:
        return {'value': -100, 'text': '▼ -100%', 'status': 'zero_current'}
    change = (current - previous) / previous * 100
    if abs(change) > 1000:
        return {'value': change, 'text': '基数过小，增长波动较大', 'status': 'extreme'}
    arrow = '▲' if change >= 0 else '▼'
    return {'value': change, 'text': f'{arrow} {change:+.1f}%', 'status': 'normal'}


if is_all_data:
    # 全部数据模式：不显示环比
    change_gmv   = {'value': None, 'text': '全部数据，无环比', 'status': 'no_compare'}
    change_orders = {'value': None, 'text': '全部数据，无环比', 'status': 'no_compare'}
    change_aov    = {'value': None, 'text': '全部数据，无环比', 'status': 'no_compare'}
    change_repurchase = {'value': None, 'text': '全部数据，无环比', 'status': 'no_compare'}
else:
    change_gmv   = calc_change(total_gmv,      prev_gmv)
    change_orders = calc_change(total_orders,    prev_orders)
    change_aov    = calc_change(avg_order_value, prev_aov)
    change_repurchase = calc_change(repurchase_rate, prev_repurchase)


# ==================== KPI 卡片样式函数 ====================
def kpi_card(label, value, change, icon):
    """
    渲染带背景色的 KPI 卡片。
    change 是 calc_change() 返回的 dict，包含 value / text / status。
    """
    status = change['status']
    delta_val = change['value']   # 可能为 None
    delta_text = change['text']

    if status == 'no_compare':
        bg = "#f8f9fa"
        delta_html = f'<span style="color:#888;font-size:13px;">{delta_text}</span>'

    elif status == 'zero_current':
        bg = "#f8d7da"
        delta_html = f'<span style="color:#721c24;font-size:14px;font-weight:600;">{delta_text}</span>'

    elif status == 'extreme':
        bg = "#fff3cd"
        delta_html = f'<span style="color:#856404;font-size:13px;">{delta_text}</span>'

    elif status == 'normal':
        if delta_val > 10:
            bg = "#d4edda"
            delta_html = f'<span style="color:#155724;font-size:14px;font-weight:600;">{delta_text}</span>'
        elif delta_val < -10:
            bg = "#f8d7da"
            delta_html = f'<span style="color:#721c24;font-size:14px;font-weight:600;">{delta_text}</span>'
        else:
            bg = "#f8f9fa"
            delta_html = f'<span style="color:{"#28a745" if delta_val >= 0 else "#dc3545"};font-size:14px;">{delta_text}</span>'

    else:
        bg = "#f8f9fa"
        delta_html = f'<span style="color:#999;font-size:13px;">{delta_text}</span>'

    html = f"""
    <div style="
        background:{bg};
        border-radius:12px;
        padding:18px 14px;
        margin:4px 0;
        text-align:center;
        min-height:120px;
        display:flex;
        flex-direction:column;
        justify-content:center;
    ">
        <div style="font-size:13px;color:#666;margin-bottom:6px;">{icon} {label}</div>
        <div style="font-size:26px;font-weight:700;color:#1a1a1a;margin:4px 0;">{value}</div>
        <div>{delta_html}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ==================== 页面标题 ====================
st.title("📊 Olist 电商经营决策看板")
st.caption(f"数据更新时间：{data_update_time} | 当前筛选：{start_month} ~ {end_month} | 订单数：{total_orders:,}")

st.divider()


# ==================== 自动异常预警 ====================
# 收集所有偏离历史均值超过阈值的指标
THRESHOLD_PCT = 15  # 偏离阈值：15%
anomalies = []

def check_anomaly(label, change_info):
    """检查单个指标是否异常偏离，返回预警文字（或空）"""
    if change_info['status'] != 'normal':
        return None  # no_compare / zero_current / extreme 都不触发预警
    val = change_info['value']
    if val is None:
        return None
    if val < -THRESHOLD_PCT:
        direction = "低于" if val < 0 else "高于"
        return f"⚠️ **{label}**：{direction}历史均值 {abs(val):.0f}%"
    if val > THRESHOLD_PCT:
        return f"📈 **{label}**：高于历史均值 {val:.0f}%"
    return None

for label, change in [
    ("销售额 (GMV)", change_gmv),
    ("订单量", change_orders),
    ("客单价", change_aov),
    ("复购率", change_repurchase),
]:
    a = check_anomaly(label, change)
    if a:
        anomalies.append(a)

if anomalies:
    # 区分预警和正面偏离
    warnings_items = [a for a in anomalies if a.startswith('⚠️')]
    positive_items = [a for a in anomalies if not a.startswith('⚠️')]
    
    for item in warnings_items:
        st.warning(item)
    for item in positive_items:
        st.info(item)


col1, col2, col3, col4 = st.columns(4)

with col1:
    kpi_card("总销售额 (GMV)", fmt_currency(total_gmv), change_gmv, "💰")

with col2:
    kpi_card("总订单量", fmt_number(total_orders), change_orders, "📦")

with col3:
    kpi_card("平均客单价", f"R$ {avg_order_value:,.2f}", change_aov, "🛒")

with col4:
    # 复购率均为0时不触发特殊逻辑
    if repurchase_rate == 0 and not has_prev:
        change_repurchase = {'value': 0, 'text': '▲ 0.0%', 'status': 'normal'}
    kpi_card("复购率", f"{repurchase_rate:.1f}%", change_repurchase, "🔄")

st.divider()


# ==================== 第二行：月度趋势 + 分类 Top10 ====================
st.subheader("📈 销售趋势与品类排行")
col_left, col_right = st.columns(2)

with col_left:
    # 月度销售趋势折线图
    fig_trend = px.line(
        monthly_trend,
        x='purchase_month',
        y='gmv',
        markers=True,
        labels={'purchase_month': '月份', 'gmv': '销售额 (R$)'},
        title='月度销售额趋势'
    )
    fig_trend.update_traces(
        line=dict(color='#1f77b4', width=2),
        marker=dict(size=6)
    )
    fig_trend.update_layout(
        height=380,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode='x unified',
        xaxis=dict(tickangle=45)
    )
    st.plotly_chart(fig_trend, width='stretch')

with col_right:
    # 分类销售额 Top10 条形图
    fig_cat = px.bar(
        category_rank,
        x='sales',
        y='product_category_name_english',
        orientation='h',
        labels={'sales': '销售额 (R$)', 'product_category_name_english': '品类'},
        title='各分类销售额 Top 10',
        text=category_rank['sales'].apply(lambda x: f'R$ {x/1e6:.1f}M')
    )
    fig_cat.update_traces(
        marker_color='#ff7f0e',
        textposition='outside',
        textfont_size=11
    )
    fig_cat.update_layout(
        height=380,
        margin=dict(l=20, r=60, t=40, b=20),
        yaxis=dict(categoryorder='total ascending')
    )
    st.plotly_chart(fig_cat, width='stretch')


# ==================== 第三行：州销售地图 + 支付方式饼图 ====================
st.subheader("🗺️ 区域分布与支付分析")
col_left, col_right = st.columns(2)

with col_left:
    # 巴西各州销售额气泡地图
    if not state_sales.empty:
        state_sales['lat'] = state_sales['customer_state'].map(
            lambda s: BRAZIL_STATE_COORDS.get(s, (None, None))[0]
        )
        state_sales['lon'] = state_sales['customer_state'].map(
            lambda s: BRAZIL_STATE_COORDS.get(s, (None, None))[1]
        )
        state_map = state_sales.dropna(subset=['lat', 'lon']).copy()

        max_sales = state_map['sales'].max()
        sizeref = max_sales / 800 if max_sales > 0 else 1
        state_map['hover_text'] = state_map.apply(lambda r:
            f"<b>{r['customer_state']}</b><br>"
            f"销售额: R$ {r['sales']:,.0f}<br>"
            f"订单量: {r['orders']:,}<br>"
            f"环比: {r['yoy_growth']:+.1f}%"
            if not np.isnan(r['yoy_growth']) else
            f"<b>{r['customer_state']}</b><br>"
            f"销售额: R$ {r['sales']:,.0f}<br>"
            f"订单量: {r['orders']:,}<br>"
            f"环比: 无同期数据"
        , axis=1)

        fig_map = go.Figure(go.Scattergeo(
            lon=state_map['lon'],
            lat=state_map['lat'],
            mode='markers',
            marker=dict(
                size=state_map['sales'].values,
                sizemin=6,
                sizemode='area',
                sizeref=sizeref,
                color=state_map['sales'].values,
                colorscale=[
                    [0.0, '#fee8c8'],
                    [0.5, '#fdbb84'],
                    [1.0, '#e34a33'],
                ],
                colorbar=dict(
                    title=dict(text='销售额 (R$)', font=dict(size=11)),
                    tickprefix='R$ ',
                    thickness=14,
                    len=0.65,
                    x=1.02,
                    tickfont=dict(size=10)
                ),
                line=dict(width=1.5, color='rgba(80,80,80,0.5)'),
                showscale=True
            ),
            text=state_map['hover_text'],
            customdata=state_map[['customer_state']].values,
            hoverinfo='text',
            hoverlabel=dict(
                bgcolor='white',
                font_size=13,
                font_family='Arial',
                bordercolor='#ccc'
            )
        ))

        fig_map.update_geos(
            projection_type='natural earth',
            fitbounds='locations',
            showcountries=True,
            countrycolor='#d0d0d0',
            showcoastlines=True,
            coastlinecolor='#999',
            landcolor='#f5f5f5',
            oceancolor='#eef6fc',
            bgcolor='rgba(0,0,0,0)'
        )

        fig_map.update_layout(
            autosize=True,
            height=440,
            margin=dict(l=10, r=10, t=10, b=10),
            clickmode='event+select',
            dragmode='select',
            selectdirection='any',
            annotations=[
                dict(
                    x=0.01, y=0.02,
                    xref='paper', yref='paper',
                    text='<i>气泡大小=销售额  |  颜色深度=销售额</i>',
                    showarrow=False,
                    font=dict(size=10, color='#888'),
                    bgcolor='rgba(255,255,255,0.7)',
                    borderpad=4
                )
            ],
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)'
        )

        st.markdown("<p style='text-align:center;font-weight:600;margin-bottom:0;'>各州销售额分布</p>",
                    unsafe_allow_html=True)
        st.plotly_chart(
            fig_map,
            key='state_map',
            width='stretch',
            on_select='rerun',
            selection_mode=['points']
        )
    else:
        st.info("当前筛选条件下无州销售数据")

with col_right:
    # 支付方式占比饼图
    if not payment_stats.empty:
        colors_map = {
            'credit_card': '#1f77b4',
            'boleto': '#ff7f0e',
            'voucher': '#2ca02c',
            'debit_card': '#d62728'
        }
        pie_colors = [colors_map.get(t, '#9467bd') for t in payment_stats['payment_type']]

        fig_pie = px.pie(
            payment_stats,
            values='count',
            names='payment_type',
            title='各支付方式订单占比',
            color_discrete_sequence=pie_colors
        )
        fig_pie.update_traces(
            textinfo='label+percent',
            textfont_size=13,
            pull=[0.05] * len(payment_stats)
        )
        fig_pie.update_layout(
            height=420,
            margin=dict(l=20, r=20, t=40, b=20),
            showlegend=True
        )
        st.plotly_chart(fig_pie, width='stretch')
    else:
        st.info("暂无支付数据")


# ==================== 第四行：物流分析 ====================
st.subheader("🚚 物流时效分析")
col_left, col_right = st.columns(2)

with col_left:
    # 物流天数分布直方图
    if len(delivered) > 0:
        fig_hist = px.bar(
            logistics_dist,
            x='物流天数',
            y='订单数',
            labels={'订单数': '订单数'},
            title='物流天数分布',
            color='物流天数',
            color_discrete_sequence=px.colors.sequential.Blues_r
        )
        fig_hist.update_layout(
            height=380,
            margin=dict(l=20, r=20, t=40, b=20),
            showlegend=False,
            xaxis=dict(title='物流天数区间')
        )
        # 在柱子上显示数值
        fig_hist.update_traces(
            text=logistics_dist['订单数'],
            textposition='outside',
            textfont_size=11
        )
        st.plotly_chart(fig_hist, width='stretch')
    else:
        st.info("暂无物流数据")

with col_right:
    # 准时送达率指标
    if len(delivered) > 0:
        # 使用仪表盘风格的指标展示
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=on_time_rate,
            number={'suffix': "%", 'font': {'size': 48}},
            title={'text': "准时送达率（≤14天）", 'font': {'size': 18}},
            delta={'reference': 80, 'increasing': {'color': "green"}},
            gauge={
                'axis': {'range': [0, 100], 'tickwidth': 1},
                'bar': {'color': "#2ca02c" if on_time_rate >= 70 else "#ff7f0e" if on_time_rate >= 50 else "#d62728"},
                'steps': [
                    {'range': [0, 50], 'color': "#ffcccc"},
                    {'range': [50, 70], 'color': "#fff3cc"},
                    {'range': [70, 85], 'color': "#d9f2d9"},
                    {'range': [85, 100], 'color': "#b3e6b3"}
                ],
                'threshold': {
                    'line': {'color': "red", 'width': 2},
                    'thickness': 0.8,
                    'value': on_time_rate
                }
            }
        ))
        fig_gauge.update_layout(height=380, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig_gauge, width='stretch')

        # 补充物流关键指标
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("📦 已完成订单", f"{len(delivered):,}")
        with m2:
            st.metric("⏱️ 平均物流天数", f"{avg_logistics:.1f} 天")
        with m3:
            median_log = delivered['logistics_days'].median()
            st.metric("📊 物流天数中位数", f"{median_log:.0f} 天")
    else:
        st.info("暂无物流数据")


# ==================== 底部信息 ====================
st.divider()
st.caption(f"数据来源：Olist Brazilian E-Commerce Dataset | 宽表行数：{len(df_all):,} | 筛选后行数：{len(df):,}")
