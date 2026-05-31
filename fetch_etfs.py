"""
后台数据采集脚本：每 65 分钟拉取 1 只 ETF，缓存到 cache/。
运行一晚上即可凑齐全部 15 只 ETF 数据。

用法: python fetch_etfs.py
"""
import os
import sys
import time
import pickle
import pandas as pd
from dotenv import load_dotenv
import tushare as ts

load_dotenv()
ts.set_token(os.getenv("TUSHARE_TOKEN"))
pro = ts.pro_api()

CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

ETF_LIST = [
    ("512710.SH", "军工龙头ETF"),
    ("512670.SH", "国防ETF"),
    ("515880.SH", "通信ETF"),
    ("515050.SH", "5GETF"),
    ("159819.SZ", "人工智能ETF"),
    ("515070.SH", "AIETF"),
    ("512480.SH", "半导体ETF"),
    ("159995.SZ", "芯片ETF"),
    ("561910.SH", "电池ETF"),
    ("159840.SZ", "锂电池ETF"),
    ("516070.SH", "碳中和ETF"),
    ("159790.SZ", "碳中和50ETF"),
    ("159611.SZ", "电力ETF"),
    ("561560.SH", "电力ETF"),
    ("516510.SH", "云计算ETF"),
]

START = "20250101"
END = "20260526"


def cache_path(code):
    return os.path.join(CACHE_DIR, f"etf_{code.replace('.', '_')}.pkl")


def already_cached(code):
    p = cache_path(code)
    if os.path.exists(p):
        df = pickle.load(open(p, "rb"))
        if len(df) > 200:
            return True
    return False


def fetch_one(code, name):
    p = cache_path(code)
    print(f"\n[{time.strftime('%H:%M:%S')}] Fetching {name} ({code})...")
    try:
        df = pro.fund_daily(ts_code=code, start_date=START, end_date=END)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df["close"] = df["close"].astype(float)
        df["pct_chg"] = df["pct_chg"].astype(float)
        df = df.sort_values("trade_date").reset_index(drop=True)
        result = df[["trade_date", "pct_chg", "close"]]
        pickle.dump(result, open(p, "wb"))
        print(f"  -> Cached {len(result)} rows")
        return True
    except Exception as e:
        print(f"  -> FAIL: {e}")
        return False


def main():
    total = len(ETF_LIST)
    cached = sum(1 for c, _ in ETF_LIST if already_cached(c))
    print(f"Status: {cached}/{total} cached")

    for code, name in ETF_LIST:
        if already_cached(code):
            print(f"  [SKIP] {name} ({code}): already cached")
            continue

        success = fetch_one(code, name)
        if success:
            cached += 1
            print(f"  Progress: {cached}/{total}")

        if cached >= total:
            print("\nAll done!")
            break

        # tushare fund_daily: 1 req/hour. Wait 65 min to be safe.
        remaining = total - cached
        if remaining > 0:
            print(f"  {remaining} remaining. Next fetch in 65 min...")
            time.sleep(65 * 60)

    print(f"\nFinal: {cached}/{total} ETFs cached")


if __name__ == "__main__":
    main()
