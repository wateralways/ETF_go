import os
import pickle
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import matplotlib
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import akshare as ak
import efinance as ef

# ============================================================
# 参数
# ============================================================
CRASH_THRESHOLD = -0.7
OVERHEAT_LOOKBACK = 10
OVERHEAT_PERCENTILE = 50
FOLLOW_DROP_THRESHOLD = -0.3
HOLD_PERIODS = [2, 5, 8, 10]

FULL_START = "2025-01-01"
FULL_END = "2026-05-30"
SPRING_START = "2026-03-01"
SPRING_END = "2026-05-31"
APR_MAY_START = "2026-04-01"

# 趋势过滤：只在大盘弱势/震荡时做（CSI300 < MA60）
TREND_FILTER = True
TREND_MA = 60

CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

ETF_POOL = {
    "512710": "军工龙头ETF",
    "512670": "国防ETF",
    "515880": "通信ETF",
    "515050": "5GETF",
    "159819": "人工智能ETF",
    "515070": "AIETF",
    "512480": "半导体ETF",
    "159995": "芯片ETF",
    "561910": "电池ETF",
    "159840": "锂电池ETF",
    "516070": "碳中和ETF",
    "159790": "碳中和50ETF",
    "159611": "电力ETF",
    "561560": "电力ETF",
    "516510": "云计算ETF",
}


# ============================================================
# 数据获取
# ============================================================

def _cache_path(key):
    return os.path.join(CACHE_DIR, f"ef_{key}.pkl")


def _read_cache(key, start, end):
    p = _cache_path(key)
    if os.path.exists(p):
        with open(p, "rb") as f:
            df = pickle.load(f)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        mask = (df["trade_date"] >= start) & (df["trade_date"] <= end)
        if mask.sum() > 100:
            return df[mask].reset_index(drop=True)
    return None


def _write_cache(key, df):
    with open(_cache_path(key), "wb") as f:
        pickle.dump(df, f)


def fetch_index_daily(start, end):
    """沪深300 - akshare (已缓存)"""
    key = "hs300"
    cached = _read_cache(key, start, end)
    if cached is not None:
        return cached

    print("  [akshare] 沪深300...", end=" ")
    df = ak.stock_zh_index_daily(symbol="sh000300")
    df = df.rename(columns={"date": "trade_date"})
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").reset_index(drop=True)
    df["close"] = df["close"].astype(float)
    df["pct_chg"] = df["close"].pct_change() * 100
    _write_cache(key, df)
    print(f"{len(df)} rows OK")
    mask = (df["trade_date"] >= start) & (df["trade_date"] <= end)
    return df[mask].reset_index(drop=True)


def fetch_etf_daily(code, start, end):
    """ETF via efinance"""
    key = f"etf_{code}"
    cached = _read_cache(key, start, end)
    if cached is not None:
        return cached

    df = ef.fund.get_quote_history(code, pz=5000)
    cols = list(df.columns)
    # cols[0]=日期, cols[1]=单位净值, cols[2]=累计净值, cols[3]=涨跌幅
    df = df.iloc[:, [0, 1, 3]]
    df.columns = ["trade_date", "close", "pct_chg"]

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    # 涨跌幅: replace '--' with NaN, then drop or fill
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    df = df.dropna(subset=["close", "pct_chg"])
    df["close"] = df["close"].astype(float)
    df["pct_chg"] = df["pct_chg"].astype(float)
    df = df.sort_values("trade_date").reset_index(drop=True)
    result = df[["trade_date", "pct_chg", "close"]]
    _write_cache(key, result)

    # 截取回测区间
    mask = (result["trade_date"] >= start) & (result["trade_date"] <= end)
    return result[mask].reset_index(drop=True)


# ============================================================
# 信号
# ============================================================

def find_crash_days(benchmark_df):
    crash = benchmark_df[benchmark_df["pct_chg"] <= CRASH_THRESHOLD]
    return list(crash["trade_date"])


def compute_overheat_rank(etf_df, crash_date):
    rows = etf_df[etf_df["trade_date"] <= crash_date]
    if len(rows) < OVERHEAT_LOOKBACK:
        return None, None
    window = rows.iloc[-OVERHEAT_LOOKBACK:]
    if window.iloc[-1]["trade_date"] != crash_date:
        return None, None
    cum_ret = (1 + window["pct_chg"] / 100).prod() - 1
    crash_day_pct = window.iloc[-1]["pct_chg"]
    return cum_ret * 100, crash_day_pct


def generate_signals(etf_data, crash_dates):
    signals = []
    for crash_date in crash_dates:
        etf_metrics = {}
        for code, df in etf_data.items():
            cum_ret, crash_pct = compute_overheat_rank(df, crash_date)
            if cum_ret is not None:
                etf_metrics[code] = (cum_ret, crash_pct)

        if len(etf_metrics) < 3:
            continue

        ranked = sorted(etf_metrics.items(), key=lambda x: x[1][0])
        cutoff = max(1, int(len(ranked) * OVERHEAT_PERCENTILE / 100))
        cold_etfs = ranked[:cutoff]

        buy_list = [
            code for code, (cum_ret, crash_pct) in cold_etfs
            if crash_pct <= FOLLOW_DROP_THRESHOLD
        ]

        if buy_list:
            signals.append({"crash_date": crash_date, "buy_list": buy_list,
                            "cold_details": {c: v for c, v in cold_etfs}})
    return signals


# ============================================================
# 交易
# ============================================================

def find_sell_price(etf_df, crash_date, hold_days):
    idxs = etf_df[etf_df["trade_date"] == crash_date].index
    if len(idxs) == 0:
        return None
    sell_idx = idxs[0] + hold_days
    if sell_idx >= len(etf_df):
        return None
    return (etf_df.iloc[sell_idx]["close"] / etf_df.iloc[idxs[0]]["close"] - 1) * 100


def run_backtest(signals, etf_data):
    trades = []
    for sig in signals:
        cd = sig["crash_date"]
        for code in sig["buy_list"]:
            for hold in HOLD_PERIODS:
                ret = find_sell_price(etf_data[code], cd, hold)
                if ret is not None:
                    trades.append({
                        "crash_date": cd,
                        "etf_code": code,
                        "etf_name": ETF_POOL[code],
                        "hold_days": hold,
                        "return_pct": round(ret, 2),
                    })
    return pd.DataFrame(trades)


# ============================================================
# 报告
# ============================================================

def compute_stats(trades_df):
    stats = []
    for hold in HOLD_PERIODS:
        sub = trades_df[trades_df["hold_days"] == hold]
        rets = sub["return_pct"]
        if len(rets) == 0:
            stats.append({"持有天数": hold, "交易次数": 0, "胜率(%)": "-",
                          "平均收益(%)": "-", "中位数收益(%)": "-",
                          "最大单笔收益(%)": "-", "最大单笔亏损(%)": "-",
                          "累计收益(%)": "-"})
        else:
            stats.append({
                "持有天数": hold,
                "交易次数": len(rets),
                "胜率(%)": round((rets > 0).sum() / len(rets) * 100, 1),
                "平均收益(%)": round(rets.mean(), 2),
                "中位数收益(%)": round(rets.median(), 2),
                "最大单笔收益(%)": round(rets.max(), 2),
                "最大单笔亏损(%)": round(rets.min(), 2),
                "累计收益(%)": round(rets.sum(), 2),
            })
    return pd.DataFrame(stats)


def plot_results(trades_df, title_suffix=""):
    if trades_df.empty:
        return
    fig, ax = plt.subplots(figsize=(14, 7))
    for hold in HOLD_PERIODS:
        sub = trades_df[trades_df["hold_days"] == hold].copy()
        if sub.empty:
            continue
        sub = sub.sort_values("crash_date")
        sub["cum_return"] = sub["return_pct"].cumsum()
        ax.plot(sub["crash_date"], sub["cum_return"], marker="o",
                linewidth=1.5, markersize=5, label=f"T+{hold}")
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
    ax.set_title(f"Cumulative Return {title_suffix}", fontsize=14)
    ax.set_xlabel("Crash Date")
    ax.set_ylabel("Cumulative Return (%)")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=45)
    plt.tight_layout()
    fn = f"cumulative_return{title_suffix}.png"
    plt.savefig(fn, dpi=150)
    print(f"  Chart: {fn}")
    # plt.show()  # skip interactive display


def print_report(trades_df, label):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    if trades_df.empty:
        print("  (no trades)")
        return None
    n_sig = trades_df.groupby("crash_date").ngroups
    avg_n = trades_df.groupby("crash_date")["etf_code"].nunique().mean()
    print(f"  Signals: {n_sig}  Avg ETFs/signal: {avg_n:.1f}\n")
    stats = compute_stats(trades_df)
    print(stats.to_string(index=False))
    print()
    for hold in HOLD_PERIODS:
        sub = trades_df[trades_df["hold_days"] == hold]
        if sub.empty:
            continue
        best = sub.loc[sub["return_pct"].idxmax()]
        worst = sub.loc[sub["return_pct"].idxmin()]
        print(f"  T+{hold} best:  {best['etf_name']} {best['crash_date'].strftime('%Y-%m-%d')} {best['return_pct']:+.2f}%")
        print(f"  T+{hold} worst: {worst['etf_name']} {worst['crash_date'].strftime('%Y-%m-%d')} {worst['return_pct']:+.2f}%")
        print()
    return stats


def save_trade_details(trades_df, filename="trade_details.csv"):
    """保存完整交易明细"""
    trades_df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"  Trade details saved: {filename}")
    return trades_df


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("  Crash-Rebound Strategy Backtest")
    print("=" * 70)
    print(f"\nParams: CSI300<={CRASH_THRESHOLD}%, lookback={OVERHEAT_LOOKBACK}d, "
          f"cold_rank={OVERHEAT_PERCENTILE}%, follow<={FOLLOW_DROP_THRESHOLD}%")
    print(f"ETFs: {len(ETF_POOL)}  Hold: {HOLD_PERIODS}d")

    # ---- 1. Data ----
    print(f"\n[1/4] Data")
    print("-" * 70)

    benchmark_df = fetch_index_daily(FULL_START, FULL_END)
    print(f"  CSI 300: {len(benchmark_df)} rows "
          f"({benchmark_df['trade_date'].iloc[0].strftime('%Y-%m-%d')} ~ "
          f"{benchmark_df['trade_date'].iloc[-1].strftime('%Y-%m-%d')})")

    etf_data = {}
    failed = []
    for code, name in ETF_POOL.items():
        try:
            df = fetch_etf_daily(code, FULL_START, FULL_END)
            etf_data[code] = df
            print(f"  [OK] {name} ({code}): {len(df)} rows")
        except Exception as e:
            failed.append((code, name, str(e)[:80]))
            print(f"  [FAIL] {name} ({code})")

    print(f"\n  Total: {len(etf_data)}/{len(ETF_POOL)} ETFs loaded")
    if failed:
        for c, n, e in failed:
            print(f"    - {n}: {e}")

    if len(etf_data) < 3:
        print("\n  *** Not enough ETF data ***")
        return

    # ---- 2. Signals ----
    print(f"\n[2/4] Signals")
    print("-" * 70)
    crash_dates = find_crash_days(benchmark_df)
    print(f"  Crash days (raw): {len(crash_dates)}")

    # ---- 趋势过滤 ----
    benchmark_df["ma"] = benchmark_df["close"].rolling(TREND_MA).mean()
    filtered_dates = []
    skipped_trend = []
    for cd in crash_dates:
        row = benchmark_df[benchmark_df["trade_date"] == cd]
        if len(row) == 0:
            continue
        close = row["close"].values[0]
        ma = row["ma"].values[0]
        pct = row["pct_chg"].values[0]
        if TREND_FILTER and pd.notna(ma) and close > ma:
            skipped_trend.append((cd, pct, close, ma))
        else:
            filtered_dates.append(cd)

    for cd in filtered_dates:
        pct = benchmark_df[benchmark_df["trade_date"] == cd]["pct_chg"].values[0]
        trend_label = ""
        if pd.notna(benchmark_df[benchmark_df["trade_date"] == cd]["ma"].values[0]):
            if benchmark_df[benchmark_df["trade_date"] == cd]["close"].values[0] <= benchmark_df[benchmark_df["trade_date"] == cd]["ma"].values[0]:
                trend_label = " [弱势]"
            else:
                trend_label = " [强势]"
        print(f"    {cd.strftime('%Y-%m-%d')}  ({pct:+.2f}%){trend_label}")

    if skipped_trend:
        print(f"\n  [趋势过滤] 跳过 {len(skipped_trend)} 次强势市急跌 (CSI300 > MA{TREND_MA}):")
        for cd, pct, close, ma in skipped_trend:
            print(f"    {cd.strftime('%Y-%m-%d')}  ({pct:+.2f}%)  close={close:.0f} > ma={ma:.0f}")

    crash_dates = filtered_dates
    print(f"\n  Crash days (after filter): {len(crash_dates)}")

    signals = generate_signals(etf_data, crash_dates)
    print(f"  Valid signals: {len(signals)}")
    for sig in signals:
        cd = sig["crash_date"]
        names = [ETF_POOL[c] for c in sig["buy_list"]]
        detal_str = ", ".join([f"{ETF_POOL[c]}(10d:{v[0]:+.1f}% today:{v[1]:+.1f}%)"
                               for c, v in sig.get("cold_details", {}).items()
                               if c in sig["buy_list"]])
        print(f"    {cd.strftime('%Y-%m-%d')} buy {len(sig['buy_list'])}: {detal_str}")

    # ---- 3. Backtest ----
    print(f"\n[3/4] Backtest")
    print("-" * 70)
    trades_df = run_backtest(signals, etf_data)
    print(f"  Total trades: {len(trades_df)}")
    if trades_df.empty:
        print("  No trades.")
        return

    # ---- Save trade details ----
    save_trade_details(trades_df)

    # ---- 4. Report ----
    print(f"\n[4/4] Results")
    print("=" * 70)
    print_report(trades_df, "Full Period (2025-01 ~ 2026-05)")

    mask = (trades_df["crash_date"] >= SPRING_START) & (trades_df["crash_date"] <= SPRING_END)
    spring = trades_df[mask].copy()
    if len(spring) > 0:
        print_report(spring, "2026 March-May")

    mask_am = (trades_df["crash_date"] >= APR_MAY_START) & (trades_df["crash_date"] <= SPRING_END)
    apr_may = trades_df[mask_am].copy()
    if len(apr_may) > 0:
        print_report(apr_may, "2026 April-May (DETAIL)")

        # Per-signal detail for April-May
        print(f"\n  --- Per-Signal Detail (T+8) ---")
        for cd in sorted(apr_may["crash_date"].unique()):
            sub = apr_may[apr_may["crash_date"] == cd]
            t8 = sub[sub["hold_days"] == 8]
            if t8.empty:
                continue
            wins = (t8["return_pct"] > 0).sum()
            total = len(t8)
            avg_r = t8["return_pct"].mean()
            mark = "[GREAT]" if avg_r > 3 else ("[OK]" if avg_r > 0 else "[BAD]")
            print(f"    {cd.strftime('%Y-%m-%d')}  T+8: {wins}/{total} win, avg={avg_r:+.2f}%  {mark}")
            for _, r in t8.iterrows():
                print(f"      {r['etf_name']:12s} {r['return_pct']:+.2f}%")

    # ---- 5. Charts ----
    print(f"\n[Charts]")
    print("-" * 70)
    plot_results(trades_df, title_suffix=" (2025-now)")
    if len(spring) > 0:
        plot_results(spring, title_suffix=" (2026-Mar-May)")

    print(f"\n{'='*70}")
    print("  Done!")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
