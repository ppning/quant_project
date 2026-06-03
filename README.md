# A 股首板涨停预测系统

一个基于 AkShare 的 A 股首板涨停预测项目。当前版本聚焦“低位启动、首次涨停”场景：用日线量价信号筛选 T 日收盘后的候选股，并在历史样本中回看 T+1 是否涨停。

## 项目思路

当前采用日线首板模型：

1. 从 AkShare 拉取 A 股日线行情，并用 CSV 做本地缓存。
2. 计算涨幅、放量、均线、低位分位、近 20 日涨停次数等首板特征。
3. 计算市场上涨占比、涨停/首板数量、炸板率等短线情绪特征。
4. 对“低位启动、放量突破、尚未涨停”的股票打首板分。
5. 结合实时换手率、市值、热点板块和尾盘信号做增强打分。
6. 输出最新首板候选，并回看历史候选次日涨停命中率。
7. 只生成 HTML 报告，不再生成 CSV 报告。

这不是实盘系统，而是研究框架。真实交易前还需要加入停牌、涨跌停、复权一致性、手续费滑点、成交约束、行业/市值中性化、幸存者偏差处理等模块。

## 目录

```text
.
├── data/
│   ├── __init__.py
│   ├── loader.py
│   ├── raw/
│   └── processed/
├── factors/
│   ├── __init__.py
│   └── calculator.py
├── strategy/
│   ├── __init__.py
│   ├── first_board.py
│   └── scoring.py
├── backtest/
│   ├── __init__.py
│   └── engine.py
├── utils/
│   ├── __init__.py
│   ├── config.py
│   └── sample_config.toml
├── reports/
├── main.py
└── README.md
```

## 快速开始

确认当前 Mac 已安装 AkShare、pandas、numpy：

```bash
python3 -c "import akshare, pandas, numpy"
```

运行首板预测：

```bash
python3 main.py --config utils/sample_config.toml
```

首次全量运行会覆盖沪深 300 和中证 500 成分股，约 800 只股票。调试时可以先限制股票数量：

```bash
python3 main.py --config utils/sample_config.toml --max-symbols 100
```

如果东方财富接口不稳定，可以直接切到腾讯备用源：

```toml
[data]
provider = "tencent"
```

默认配置是 `provider = "auto"`，会先尝试东方财富接口，失败后自动尝试腾讯接口。

输出文件默认在 `reports/`：

- `index.html`: 首板涨停预测报告

## 首板特征

- `pct_change > 5`: 当日已有明显资金异动。
- `pct_change < limit_up_threshold`: 当日尚未涨停，避免把已经首板的股票混入。
- `volume_ratio_5_display >= 2`: 今日成交量超过前 5 日均量 2 倍。
- `close_above_ma20`: 收盘价站上 20 日均线。
- `limit_up_count_20d == 0`: 近 20 日无涨停，偏向首次启动。
- `low_position_60`: 价格处于 60 日区间较低位置。
- `intraday_strength`: 收盘价接近日内高位，代表日内承接较强。
- `market_sentiment_score`: 用市场上涨占比、涨停数量、首板数量和炸板率衡量短线情绪。
- `near_limit_touch`: 当日最高价接近理论涨停价，表示资金已经试探涨停区。
- `broken_limit_touch`: 盘中接近涨停但收盘未涨停，作为炸板/近板失败惩罚项。

## 回看口径

当前采用规则信号回看：每天只取首板候选中分数最高的 Top N，观察这些股票 T+1 是否涨停。报告中重点看：

- `历史信号数`: 历史上触发首板候选并进入 Top N 的样本数量。
- `次日涨停数`: Top N 候选中 T+1 涨停的数量。
- `命中率`: 次日涨停数 / 历史信号数。
- `平均次日收益`: Top N 候选 T+1 平均涨跌幅。
- `平均首板分`: 历史 Top N 候选的平均规则分。

## 后续可扩展方向

- 股票池：沪深 300、中证 500、自定义白名单/黑名单。
- 数据：换手率、流通市值、行业/概念板块涨幅排名。
- 分时：14:30 后尾盘放量、VWAP 强度、收盘接近日内高点。
- 盘口：大单主动买入、买卖盘失衡、连续扫单。
- 回测：涨停买不到、一字板过滤、滑点和次日开盘买入约束。
- 存储：从 CSV 切换到 DuckDB 或 SQLite。
