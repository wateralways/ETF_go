"""
尾盘信号扫描脚本
用法: python signal_today.py
时机: 每个交易日 14:50
数据: 新浪实时行情 (盘中) + 本地缓存 (历史)
"""
import warnings
warnings.filterwarnings("ignore")

import pickle, os, time
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta

# ============================================================
# 策略参数
# ============================================================
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


# ============================================================
# 实时数据 (新浪)
# ============================================================

def fetch_realtime_quotes():
    """从新浪获取 CSI300 + 15只ETF 实时行情"""
    # 构建 code 列表
    index_code = "s_sh000300"
    etf_codes = []
    for c in ETF_POOL:
        prefix = "sh" if c.startswith(("5", "6", "9")) else "sz"  # ETF 代码在上海/深圳
        # 实际上:
        # 510xxx, 512xxx, 515xxx, 516xxx, 561xxx -> sh
        # 159xxx -> sz
        if c.startswith("159"):
            prefix = "sz"
        else:
            prefix = "sh"
        etf_codes.append(f"{prefix}{c}")

    all_codes = [index_code] + etf_codes
    url = f"http://hq.sinajs.cn/list={','.join(all_codes)}"
    headers = {"Referer": "https://finance.sina.com.cn"}
    r = requests.get(url, headers=headers, timeout=10)
    r.encoding = "gbk"
    return r.text


def parse_index_quote(line):
    """解析CSI300: var hq_str_s_sh000300="沪深300,4892.12,-22.09,-0.45,3325186,94223649"""
    data = line.split('"')[1].split(",")
    return {
        "name": data[0],
        "price": float(data[1]),
        "change": float(data[2]),
        "pct_chg": float(data[3]),
    }


def parse_etf_quote(line):
    """解析ETF: var hq_str_sh512710="军工龙头ETF基金,0.720,0.720,0.690,0.724,0.686,..."
    字段: name, open, prev_close, price, high, low, ...
    """
    data = line.split('"')[1].split(",")
    return {
        "name": data[0],
        "open": float(data[1]),
        "prev_close": float(data[2]),
        "price": float(data[3]),
        "high": float(data[4]),
        "low": float(data[5]),
    }


# ============================================================
# 历史数据 (缓存)
# ============================================================

def load_index_history():
    """沪深300日线"""
    for f in ["cache/ef_hs300.pkl", "cache/hs300.pkl"]:
        if os.path.exists(f):
            df = pd.read_pickle(f)
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            return df.sort_values("trade_date").reset_index(drop=True)
    raise RuntimeError("No cache. Run backtest.py first.")


def load_etf_history(code):
    """ETF日线"""
    cache_file = f"cache/ef_etf_{code}.pkl"
    if os.path.exists(cache_file):
        df = pd.read_pickle(cache_file)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df.sort_values("trade_date").reset_index(drop=True)
    raise RuntimeError(f"No cache for {code}. Run backtest.py first.")


# ============================================================
# 计算
# ============================================================

def compute_10d_return_intraday(etf_hist, intraday_pct_chg):
    """
    用过去9天历史 + 今天盘中涨跌幅, 合成10日累计收益
    """
    if len(etf_hist) < OVERHEAT_LOOKBACK - 1:
        return None
    # 过去9天
    past_9 = etf_hist["pct_chg"].iloc[-(OVERHEAT_LOOKBACK - 1):]
    all_10 = list(past_9) + [intraday_pct_chg]
    return (np.prod(1 + np.array(all_10) / 100) - 1) * 100


def check_trend_intraday(index_hist, intraday_price):
    """CSI300 vs MA60 (用盘中价代替收盘)"""
    closes = list(index_hist["close"].iloc[-(TREND_MA - 1):]) + [intraday_price]
    ma60 = np.mean(closes)
    above = intraday_price > ma60
    label = "强势" if above else "弱势/震荡"
    return label, above, ma60


# ============================================================
# 主流程
# ============================================================

def main():
    now = datetime.now()
    print("=" * 60)
    print("  大盘急跌信号扫描 (盘中实时)")
    print(f"  {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ---- Step 1: 实时行情 ----
    print("\n[1/4] 获取实时行情 (新浪)...")
    rt_text = fetch_realtime_quotes()
    lines = rt_text.strip().split("\n")

    # 解析指数
    index_quote = parse_index_quote(lines[0])
    # 解析ETF
    etf_quotes = {}
    for line in lines[1:]:
        q = parse_etf_quote(line)
        # 匹配代码
        for code in ETF_POOL:
            prefix = "sz" if code.startswith("159") else "sh"
            if f"{prefix}{code}" in line:
                etf_quotes[code] = q
                break

    csi300_pct = index_quote["pct_chg"]
    print(f"  沪深300: {index_quote['price']:.0f}  ({csi300_pct:+.2f}%)")
    print(f"  ETF实时: {len(etf_quotes)}/{len(ETF_POOL)} 只")

    # ---- Step 2: 急跌判断 ----
    print(f"\n[2/4] 急跌判断")
    is_crash = csi300_pct <= CRASH_THRESHOLD
    print(f"  盘中涨跌: {csi300_pct:+.2f}%  阈值: <= {CRASH_THRESHOLD}%")
    if is_crash:
        print(f"  >>> 盘中触发急跌!")
    else:
        # 还在跌但是没到阈值
        if csi300_pct < 0:
            print(f"  >>> 未触发 (距阈值还差 {abs(csi300_pct - CRASH_THRESHOLD):.2f}%)")
        else:
            print(f"  >>> 未触发 (大盘上涨中)")
        print(f"\n  [提示] 距收盘还有约 {60 - now.minute} 分钟, 尾盘可能变化")
        print(f"         建议 14:55 再跑一次确认")
        print("\n" + "=" * 60)
        return

    # ---- Step 3: 趋势 ----
    print(f"\n[3/4] 趋势过滤 + 过热度")

    index_hist = load_index_history()
    trend_label, is_strong, ma60 = check_trend_intraday(index_hist, index_quote["price"])
    print(f"  CSI300 {index_quote['price']:.0f} vs MA60 {ma60:.0f} → {trend_label}")

    if is_strong:
        print(f"\n  *** 强势中急跌 — 历史数据: 胜率46%, 平均+0.5% ***")
        print(f"  *** 建议减半仓位 或 跳过 ***")

    # ---- Step 4: ETF筛选 ----
    etf_scores = []
    for code, name in ETF_POOL.items():
        if code not in etf_quotes:
            continue
        try:
            hist = load_etf_history(code)
            q = etf_quotes[code]
            # 盘中涨跌幅 = (现价 - 昨收) / 昨收 * 100
            intraday_pct = (q["price"] - q["prev_close"]) / q["prev_close"] * 100
            # 10日累计
            ret10 = compute_10d_return_intraday(hist, intraday_pct)
            if ret10 is None:
                continue
            etf_scores.append((code, name, ret10, intraday_pct))
        except Exception:
            continue

    if len(etf_scores) < 3:
        print("  数据不足")
        return

    etf_scores.sort(key=lambda x: x[2])
    cutoff = max(1, int(len(etf_scores) * OVERHEAT_PERCENTILE / 100))
    cold = etf_scores[:cutoff]
    buy_list = [(c, n, r, t) for c, n, r, t in cold if t <= FOLLOW_DROP_THRESHOLD]

    print(f"\n  {'ETF':12s} {'10日':>7s} {'盘中':>7s} {'状态':>12s}")
    print(f"  {'-'*44}")
    for code, name, ret10, pct in etf_scores:
        status = ""
        if (code, name, ret10, pct) in buy_list:
            status = "<< 买入"
        elif (code, name, ret10, pct) in cold:
            status = "(未跟跌)"
        print(f"  {name:12s} {ret10:+6.2f}% {pct:+6.2f}%  {status}")

    # ---- 输出 ----
    print(f"\n{'='*60}")
    print(f"  买入清单 (盘中, 14:50) — 收盘前确认")
    print(f"{'='*60}")

    if not buy_list:
        print("  无符合条件的ETF")
        return

    weight = 100 / len(buy_list)
    print(f"\n  {len(buy_list)} 只 ETF, 各 {weight:.1f}%:\n")
    for code, name, ret10, pct in buy_list:
        print(f"    {code}  {name:12s}  10日:{ret10:+.2f}%  盘中:{pct:+.2f}%")

    today = datetime.now()
    sell_date = today + timedelta(days=11)
    print(f"\n  操作: {today.strftime('%Y-%m-%d')} 尾盘竞价买入")
    print(f"  卖出: {sell_date.strftime('%Y-%m-%d')} 前后 (T+8)")
    if is_strong:
        print(f"  [警告] 强势市信号, 建议减半")
    print(f"\n  >>> 请收盘前自行确认后执行 <<<")


if __name__ == "__main__":
    main()
