# Olist 电商经营决策看板

基于巴西 Olist 电商数据集，使用 **Streamlit + Plotly** 构建的交互式经营决策看板，支持多维度筛选、自动异常预警和数据导出。

## 功能概览

| 模块 | 内容 |
|---|---|
| **核心 KPI 卡片** | 总销售额(GMV)、订单量、客单价、复购率，含环比变化率与红绿预警 |
| **销售趋势图** | 月度销售趋势折线图，品类销售额 Top 10 条形图 |
| **地理分布** | 巴西各州销售额气泡地图，支持点击联动筛选 |
| **支付分析** | 各支付方式占比饼图 |
| **物流分析** | 物流天数分布直方图 + 准时送达率仪表盘 |
| **自动预警** | KPI 偏离上月 > 15% 时自动弹出警告提示 |

### 四种筛选模式

| 模式 | 说明 |
|---|---|
| 📊 全部数据 | 展示全量历史数据 |
| 🏆 销售巅峰月 | 自动锁定 GMV 最高的单月 |
| 📉 销售低谷月 | 自动锁定 GMV 最低的有效单月 |
| 📅 按月滚动 | 逐月浏览，支持 ◀ ▶ 箭头切换 |

### 数据导出

侧边栏支持将当前筛选条件下的原始数据一键导出为 CSV 文件。

## 项目结构

```
数据看板与监控/
├── app.py                              # Streamlit 看板主程序
├── load_to_sqlite.py                   # 数据加载脚本（CSV → SQLite）
├── monitor.py                          # 每日数据监控脚本（命令行工具）
├── olist_cleaning_feature_engineering.ipynb  # 数据清洗与特征工程
├── olist_kpi_analysis.ipynb            # KPI 指标分析
├── *.csv                               # Olist 原始数据（9张表）
└── requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
pip install streamlit pandas plotly sqlite3
```

### 2. 初始化数据库

```bash
python load_to_sqlite.py
```

### 3. 启动看板

```bash
streamlit run app.py
```

浏览器访问 `http://localhost:8501` 即可使用。

## 监控脚本使用

```bash
python monitor.py
```

每日自动检测：销售额、订单量、物流天数、大额订单、负金额订单等 5 项指标，超出阈值时输出告警。

## 数据来源

[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (Kaggle)

数据集包含约 10 万笔订单，时间跨度 2016-09 至 2018-09，涵盖订单、客户、卖家、支付、物流、评价等维度。
