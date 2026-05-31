"""
GitHub Actions 每日分析脚本
运行: python daily_analysis.py
输出: signal_result.json + signal_status.html
"""
import warnings
warnings.filterwarnings("ignore")

import os, json, pickle
import pandas as pd
import numpy as np
from datetime import datetime
import efinance as ef

# ========== Config ==========
CRASH_THRESHOLD = -0.7
OVERHEAT_LOOKBACK = 10
OVERHEAT_PERCENTILE = 50
FOLLOW_DROP_THRESHOLD = -0.3
TREND_MA = 60

ETF_POOL = {
    "512710": "军工龙头ETF", "512670": "国防ETF",
    "515880": "通信ETF",     "515050": "5GETF",
    "159819": "人工智能ETF",  "515070": "AIETF",
    "512480": "半导体ETF",    "159995": "芯片ETF",
    "561910": "电池ETF",      "159840": "锂电池ETF",
    "516070": "碳中和ETF",    "159790": "碳中和50ETF",
    "159611": "电力ETF",      "561560": "电力ETF",
    "516510": "云计算ETF",
}

CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)


# ============================================================
# Data
# ============================================================

def load_or_fetch_etf(code):
    cache_file = os.path.join(CACHE_DIR, f"ef_etf_{code}.pkl")
    if os.path.exists(cache_file):
        df = pd.read_pickle(cache_file)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        if len(df) > 300:
            return df.sort_values("trade_date").reset_index(drop=True)
    try:
        df = ef.fund.get_quote_history(code, pz=5000)
        cols = list(df.columns)
        df = df.iloc[:, [0, 1, 3]]
        df.columns = ["trade_date", "close", "pct_chg"]
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
        df = df.dropna(subset=["close", "pct_chg"])
        df = df.sort_values("trade_date").reset_index(drop=True)
        with open(cache_file, "wb") as f:
            pickle.dump(df, f)
        return df
    except Exception:
        return None


def load_or_fetch_index():
    cache_file = os.path.join(CACHE_DIR, "ef_hs300.pkl")
    if os.path.exists(cache_file):
        df = pd.read_pickle(cache_file)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        if len(df) > 300:
            return df.sort_values("trade_date").reset_index(drop=True)
    # Try efinance first
    try:
        df = ef.stock.get_quote_history("000300", pz=500)
        df = df.rename(columns={"日期": "trade_date", "收盘": "close", "涨跌幅": "pct_chg"})
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
        df = df.dropna(subset=["close", "pct_chg"])
        df = df.sort_values("trade_date").reset_index(drop=True)
        with open(cache_file, "wb") as f:
            pickle.dump(df, f)
        return df
    except Exception:
        pass
    # Fallback: akshare sina source
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol="sh000300")
        df = df.rename(columns={"date": "trade_date"})
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df["close"] = df["close"].astype(float)
        df["pct_chg"] = df["close"].pct_change() * 100
        df = df.sort_values("trade_date").reset_index(drop=True)
        with open(cache_file, "wb") as f:
            pickle.dump(df, f)
        return df
    except Exception as e:
        raise RuntimeError(f"Cannot fetch index data: {e}")


# ============================================================
# Analysis
# ============================================================

def main():
    print("=" * 60)
    print("  Daily Signal Analysis")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # Index
    print("\nFetching index...")
    index_df = load_or_fetch_index()
    latest = index_df["trade_date"].max()
    today_row = index_df[index_df["trade_date"] == latest]
    csi300_pct = float(today_row["pct_chg"].values[0])
    csi300_close = float(today_row["close"].values[0])
    print(f"  Latest: {latest.strftime('%Y-%m-%d')}  CSI300: {csi300_close:.0f} ({csi300_pct:+.2f}%)")

    # Trend
    index_df["ma60"] = index_df["close"].rolling(60).mean()
    ma60_val = float(index_df["ma60"].iloc[-1])
    is_strong = csi300_close > ma60_val if pd.notna(ma60_val) else True
    trend = "强势" if is_strong else "弱势/震荡"
    print(f"  MA60: {ma60_val:.0f}  Trend: {trend}")

    # Crash check
    is_crash = csi300_pct <= CRASH_THRESHOLD
    print(f"  Crash: {'YES' if is_crash else 'NO'} (threshold: <= {CRASH_THRESHOLD}%)")

    # ETF analysis
    buy_list = []
    etf_scores = []

    if is_crash:
        print(f"\nCrash triggered! Analyzing {len(ETF_POOL)} ETFs...")
        for code, name in ETF_POOL.items():
            df = load_or_fetch_etf(code)
            if df is None or len(df) < 15:
                continue
            rows = df[df["trade_date"] <= latest]
            if len(rows) < OVERHEAT_LOOKBACK:
                continue
            window = rows.iloc[-OVERHEAT_LOOKBACK:]
            if window.iloc[-1]["trade_date"] != latest:
                continue
            cum_ret = float((np.prod(1 + window["pct_chg"] / 100) - 1) * 100)
            today_pct = float(window.iloc[-1]["pct_chg"])
            etf_scores.append((code, name, cum_ret, today_pct))

        if len(etf_scores) >= 3:
            etf_scores.sort(key=lambda x: x[2])
            cutoff = max(1, int(len(etf_scores) * OVERHEAT_PERCENTILE / 100))
            cold = etf_scores[:cutoff]
            buy_list = [(c, n, r, t) for c, n, r, t in cold if t <= FOLLOW_DROP_THRESHOLD]
            print(f"  Buy list: {len(buy_list)} ETFs")
        else:
            print(f"  Not enough ETF data: {len(etf_scores)}")
    else:
        print("\nNo crash signal. No ETF analysis needed.")

    # Build result
    result = {
        "date": latest.strftime("%Y-%m-%d"),
        "csi300_close": round(csi300_close, 2),
        "csi300_pct": round(csi300_pct, 2),
        "is_crash": bool(is_crash),
        "trend": trend,
        "is_strong": bool(is_strong),
        "ma60": round(ma60_val, 2) if pd.notna(ma60_val) else None,
        "buy_list": [
            {"code": c, "name": n, "ret_10d": round(r, 2), "today_pct": round(t, 2)}
            for c, n, r, t in buy_list[:10]
        ],
        "all_etfs": [
            {"code": c, "name": n, "ret_10d": round(r, 2), "today_pct": round(t, 2),
             "cold": (c, n, r, t) in buy_list}
            for c, n, r, t in etf_scores[:20]
        ],
        "n_buy": len(buy_list),
        "analysis_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

    with open("signal_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nResult saved: signal_result.json")

    # Status badge
    if is_crash and buy_list:
        badge = f'<div class="status-badge active">● 触发信号 — {len(buy_list)}只ETF待买</div>'
    elif is_crash:
        badge = '<div class="status-badge wait">● 急跌但无符合条件的ETF</div>'
    else:
        gap = abs(csi300_pct - CRASH_THRESHOLD)
        badge = f'<div class="status-badge off">● 未触发 (距阈值差 {gap:.2f}%)</div>'

    with open("signal_status.html", "w", encoding="utf-8") as f:
        f.write(badge)

    return result


if __name__ == "__main__":
    main()
