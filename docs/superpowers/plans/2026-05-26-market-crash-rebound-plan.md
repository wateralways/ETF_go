# 大盘急跌-非过热板块超跌反弹策略 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现A股大盘急跌后非过热板块ETF超跌反弹的量化回测，用Tushare数据验证策略有效性。

**Architecture:** 单文件 Python 脚本 `backtest.py`，按数据获取→信号生成→模拟交易→结果输出四个阶段线性执行。所有参数集中在顶部常量区，方便调参迭代。

**Tech Stack:** Python 3.x, tushare, pandas, matplotlib

---

### Task 1: 项目初始化

**Files:**
- Create: `requirements.txt`
- Create: `.env`

- [ ] **Step 1: 创建 requirements.txt**

```
tushare>=1.4.0
pandas>=2.0.0
matplotlib>=3.7.0
numpy>=1.24.0
python-dotenv>=1.0.0
```

- [ ] **Step 2: 创建 .env 文件**

```
TUSHARE_TOKEN=701a94c30c5d1c7af41602c8ebd47b1ca7a2c49bfdd5419379f40c8d
```

- [ ] **Step 3: 安装依赖**

Run: `pip install -r requirements.txt`

---

### Task 2: 数据获取模块

**Files:**
- Create: `backtest.py` (数据获取部分)

```python
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from dotenv import load_dotenv
import tushare as ts

load_dotenv()
ts.set_token(os.getenv("TUSHARE_TOKEN"))
pro = ts.pro_api()

# ============================================================
# 参数配置
# ============================================================
CRASH_THRESHOLD = -0.7        # 大盘急跌阈值 (%)
OVERHEAT_LOOKBACK = 10        # 过热度回顾天数
OVERHEAT_PERCENTILE = 50      # 非过热排名后50%
FOLLOW_DROP_THRESHOLD = -0.3  # 跟跌确认阈值 (%)
HOLD_PERIODS = [2, 5, 8, 10]  # 持有天数
BENCHMARK_INDEX = "000300.SH" # 沪深300
START_DATE = "20250101"
END_DATE = "20260526"

# ETF候选池
ETF_POOL = {
    "512710.SH": "军工龙头ETF",
    "512670.SH": "国防ETF",
    "515880.SH": "通信ETF",
    "515050.SH": "5GETF",
    "159819.SZ": "人工智能ETF",
    "515070.SH": "AIETF",
    "512480.SH": "半导体ETF",
    "159995.SZ": "芯片ETF",
    "561910.SH": "电池ETF",
    "159840.SZ": "锂电池ETF",
    "516070.SH": "碳中和ETF",
    "159790.SZ": "碳中和50ETF",
    "159611.SZ": "电力ETF",
    "561560.SH": "电力ETF",
    "516510.SH": "云计算ETF",
}


def fetch_index_daily(ts_code, start, end):
    """拉取指数日线数据"""
    df = pro.index_daily(ts_code=ts_code, start_date=start, end_date=end)
    df = df.sort_values("trade_date").reset_index(drop=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["pct_chg"] = df["pct_chg"].astype(float)
    return df[["trade_date", "pct_chg", "close"]]


def fetch_fund_daily(ts_code, start, end):
    """拉取ETF日线数据"""
    df = pro.fund_daily(ts_code=ts_code, start_date=start, end_date=end)
    df = df.sort_values("trade_date").reset_index(drop=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["pct_chg"] = df["pct_chg"].astype(float)
    return df[["trade_date", "pct_chg", "close"]]
```

---

### Task 3: 信号生成模块

**Files:**
- Modify: `backtest.py` (追加信号生成部分)

```python
def find_crash_days(benchmark_df):
    """找出大盘急跌日"""
    crash = benchmark_df[benchmark_df["pct_chg"] <= CRASH_THRESHOLD].copy()
    return crash["trade_date"].tolist()


def compute_overheat_rank(etf_df, crash_date, lookback=OVERHEAT_LOOKBACK):
    """
    计算急跌日前 lookback 天的累计涨跌幅，
    返回该ETF在所有候选ETF中的排名百分位（值越大越热）
    """
    end_idx = etf_df[etf_df["trade_date"] <= crash_date].index
    if len(end_idx) == 0:
        return None, None
    end_idx = end_idx[-1]
    start_idx = max(0, end_idx - lookback + 1)

    if end_idx - start_idx + 1 < lookback:
        return None, None

    window = etf_df.iloc[start_idx:end_idx + 1]
    cum_ret = (1 + window["pct_chg"] / 100).prod() - 1
    crash_day_pct = etf_df.iloc[end_idx]["pct_chg"]
    return cum_ret * 100, crash_day_pct


def generate_signals(benchmark_df, etf_data, crash_dates):
    """
    生成买入信号:
    - crash_date: 急跌日
    - buy_list: 当日可买入的ETF代码列表
    """
    signals = []

    for crash_date in crash_dates:
        # 计算每只ETF的10日累计收益 + 急跌日涨跌幅
        etf_metrics = {}
        for code, df in etf_data.items():
            cum_ret, crash_pct = compute_overheat_rank(df, crash_date)
            if cum_ret is not None:
                etf_metrics[code] = (cum_ret, crash_pct)

        if len(etf_metrics) < 5:
            continue  # 数据不足，跳过

        # 按10日累计收益排序，取后50%
        ranked = sorted(etf_metrics.items(), key=lambda x: x[1][0])
        cutoff = int(len(ranked) * OVERHEAT_PERCENTILE / 100)
        cold_etfs = ranked[:cutoff]

        # 跟跌确认：急跌日至少跌 -0.3%
        buy_list = [
            code for code, (cum_ret, crash_pct) in cold_etfs
            if crash_pct <= FOLLOW_DROP_THRESHOLD
        ]

        if buy_list:
            signals.append({
                "crash_date": crash_date,
                "buy_list": buy_list,
            })

    return signals
```

---

### Task 4: 模拟交易模块

**Files:**
- Modify: `backtest.py` (追加交易模拟部分)

```python
def find_sell_price(etf_df, crash_date, hold_days):
    """找到持有hold_days后的收盘价，返回收益率"""
    crash_idx = etf_df[etf_df["trade_date"] == crash_date].index
    if len(crash_idx) == 0:
        return None
    crash_idx = crash_idx[0]
    sell_idx = crash_idx + hold_days
    if sell_idx >= len(etf_df):
        return None
    buy_close = etf_df.iloc[crash_idx]["close"]
    sell_close = etf_df.iloc[sell_idx]["close"]
    return (sell_close / buy_close - 1) * 100


def run_backtest(signals, etf_data):
    """
    执行回测，返回所有交易记录
    记录格式: (crash_date, etf_code, hold_period, return_pct)
    """
    trades = []

    for sig in signals:
        crash_date = sig["crash_date"]
        buy_list = sig["buy_list"]

        for hold in HOLD_PERIODS:
            period_returns = []
            for code in buy_list:
                ret = find_sell_price(etf_data[code], crash_date, hold)
                if ret is not None:
                    period_returns.append(ret)
                    trades.append({
                        "crash_date": crash_date,
                        "etf_code": code,
                        "etf_name": ETF_POOL[code],
                        "hold_days": hold,
                        "return_pct": ret,
                    })

    return pd.DataFrame(trades)
```

---

### Task 5: 结果输出与可视化

**Files:**
- Modify: `backtest.py` (追加输出和可视化部分)

```python
def compute_stats(trades_df):
    """计算各持有期的统计指标"""
    stats = []
    for hold in HOLD_PERIODS:
        sub = trades_df[trades_df["hold_days"] == hold]
        returns = sub["return_pct"]
        stats.append({
            "持有天数": hold,
            "交易次数": len(returns),
            "胜率(%)": round((returns > 0).sum() / len(returns) * 100, 1) if len(returns) > 0 else 0,
            "平均收益(%)": round(returns.mean(), 2),
            "中位数收益(%)": round(returns.median(), 2),
            "最大单笔收益(%)": round(returns.max(), 2),
            "最大单笔亏损(%)": round(returns.min(), 2),
            "累计收益(%)": round(returns.sum(), 2),
        })
    return pd.DataFrame(stats)


def plot_results(trades_df, title_suffix=""):
    """画累计收益曲线"""
    fig, ax = plt.subplots(figsize=(12, 6))

    for hold in HOLD_PERIODS:
        sub = trades_df[trades_df["hold_days"] == hold]
        sub = sub.sort_values("crash_date")
        sub["cum_return"] = sub["return_pct"].cumsum()
        ax.plot(sub["crash_date"], sub["cum_return"], marker="o", label=f"T+{hold}")

    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
    ax.set_title(f"累计收益曲线 {title_suffix}", fontsize=14)
    ax.set_xlabel("急跌日期")
    ax.set_ylabel("累计收益率 (%)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(f"累计收益曲线{title_suffix}.png", dpi=150)
    plt.show()


def print_report(trades_df, period_label):
    """打印完整报告"""
    print(f"\n{'='*60}")
    print(f"   {period_label}")
    print(f"{'='*60}")
    stats = compute_stats(trades_df)
    print(stats.to_string(index=False))
    return stats
```

---

### Task 6: 主流程整合

**Files:**
- Modify: `backtest.py` (追加main函数)

```python
def main():
    print("=" * 60)
    print("  大盘急跌-非过热板块超跌反弹策略 回测")
    print("=" * 60)
    print(f"\n参数: 急跌阈值≤{CRASH_THRESHOLD}%, 过热度回顾{OVERHEAT_LOOKBACK}日, "
          f"排名后{OVERHEAT_PERCENTILE}%, 跟跌阈值≤{FOLLOW_DROP_THRESHOLD}%")
    print(f"候选池: {len(ETF_POOL)}只ETF")
    print(f"持有期: {HOLD_PERIODS}")

    # 1. 拉数据
    print("\n>>> 拉取数据...")
    benchmark_df = fetch_index_daily(BENCHMARK_INDEX, START_DATE, END_DATE)
    print(f"  沪深300: {len(benchmark_df)} 条日线")

    etf_data = {}
    for code, name in ETF_POOL.items():
        try:
            df = fetch_fund_daily(code, START_DATE, END_DATE)
            if len(df) > 0:
                etf_data[code] = df
                print(f"  {name} ({code}): {len(df)} 条日线")
        except Exception as e:
            print(f"  {name} ({code}): 获取失败 - {e}")

    print(f"  成功获取 {len(etf_data)}/{len(ETF_POOL)} 只ETF数据")

    # 2. 找信号
    print("\n>>> 生成交易信号...")
    crash_dates = find_crash_days(benchmark_df)
    print(f"  急跌日数: {len(crash_dates)}")
    for cd in crash_dates:
        print(f"    {cd.strftime('%Y-%m-%d')}")

    signals = generate_signals(benchmark_df, etf_data, crash_dates)
    print(f"  交易信号数: {len(signals)}")

    # 3. 回测
    print("\n>>> 执行回测...")
    trades_df = run_backtest(signals, etf_data)

    # 4. 全量报告
    print_report(trades_df, "全量回测 (2025-01 ~ 至今)")

    # 5. 2026年3-5月单独报告
    mask = (trades_df["crash_date"] >= "2026-03-01") & (trades_df["crash_date"] <= "2026-05-31")
    spring_2026 = trades_df[mask]
    if len(spring_2026) > 0:
        print_report(spring_2026, "2026年3-5月 回测")
    else:
        print("\n2026年3-5月: 无交易信号")

    # 6. 画图
    print("\n>>> 生成图表...")
    plot_results(trades_df, title_suffix="(2025-至今)")
    if len(spring_2026) > 0:
        plot_results(spring_2026, title_suffix="(2026年3-5月)")

    print("\n回测完成!")


if __name__ == "__main__":
    main()
```

- [ ] **Step 1: 运行完整回测**

Run: `python backtest.py`

---

### Task 7: 提交代码

- [ ] **Step 1: Git add and commit**

```bash
git add .
git commit -m "feat: 大盘急跌-非过热板块超跌反弹策略回测系统"
```
