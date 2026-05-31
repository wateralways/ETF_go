import base64
import pandas as pd
import numpy as np
import matplotlib
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO

# ============================================================
# Load data
# ============================================================
df = pd.read_csv("trade_details.csv")
df["crash_date"] = pd.to_datetime(df["crash_date"])

HOLD_PERIODS = [2, 5, 8, 10]
SPRING_START = "2026-03-01"
SPRING_END = "2026-05-31"

# ============================================================
# Helper: stats table
# ============================================================
def build_stats(trades):
    rows = []
    for hold in HOLD_PERIODS:
        sub = trades[trades["hold_days"] == hold]
        rets = sub["return_pct"]
        if len(rets) == 0:
            rows.append(dict(持有天数=hold, 交易次数=0, 胜率="-", 平均收益="-",
                             中位数收益="-", 最大盈利="-", 最大亏损="-", 累计收益="-"))
        else:
            rows.append(dict(
                持有天数=hold, 交易次数=len(rets),
                胜率=f"{(rets > 0).sum() / len(rets) * 100:.1f}%",
                平均收益=f"{rets.mean():.2f}%",
                中位数收益=f"{rets.median():.2f}%",
                最大盈利=f"{rets.max():.2f}%",
                最大亏损=f"{rets.min():.2f}%",
                累计收益=f"{rets.sum():.2f}%",
            ))
    return pd.DataFrame(rows)

def build_best_worst(trades):
    lines = []
    for hold in HOLD_PERIODS:
        sub = trades[trades["hold_days"] == hold]
        if sub.empty:
            continue
        best = sub.loc[sub["return_pct"].idxmax()]
        worst = sub.loc[sub["return_pct"].idxmin()]
        lines.append(f"<tr><td>T+{hold}</td>"
                     f"<td class='pos'>{best['etf_name']} {best['crash_date'].strftime('%Y-%m-%d')} {best['return_pct']:+.2f}%</td>"
                     f"<td class='neg'>{worst['etf_name']} {worst['crash_date'].strftime('%Y-%m-%d')} {worst['return_pct']:+.2f}%</td></tr>")
    return "\n".join(lines)

# ============================================================
# Chart: generate & embed
# ============================================================
def chart_to_b64(fig):
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()

def make_cumulative_chart(trades, title):
    fig, ax = plt.subplots(figsize=(12, 5.5))
    for hold in HOLD_PERIODS:
        sub = trades[trades["hold_days"] == hold].copy()
        if sub.empty:
            continue
        sub = sub.sort_values("crash_date")
        sub["cum_return"] = sub["return_pct"].cumsum()
        ax.plot(sub["crash_date"], sub["cum_return"], marker="o", linewidth=1.5, markersize=4, label=f"T+{hold}")
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_xlabel("Crash Date")
    ax.set_ylabel("Cumulative Return (%)")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=45)
    return chart_to_b64(fig)

# ============================================================
# Build charts
# ============================================================
chart_full = make_cumulative_chart(df, "Full Period (2025-01 ~ 2026-05)")
spring_mask = (df["crash_date"] >= SPRING_START) & (df["crash_date"] <= SPRING_END)
spring_df = df[spring_mask].copy()
chart_spring = make_cumulative_chart(spring_df, "2026 March - May") if len(spring_df) > 0 else ""

# ============================================================
# Stats
# ============================================================
full_stats = build_stats(df)
spring_stats = build_stats(spring_df) if len(spring_df) > 0 else None
best_worst_full = build_best_worst(df)
best_worst_spring = build_best_worst(spring_df) if len(spring_df) > 0 else ""

# Signal summary
signals = df.groupby("crash_date")
n_signals = signals.ngroups
avg_etfs = signals["etf_code"].nunique().mean()

spring_signals = spring_df.groupby("crash_date")
n_spring = spring_signals.ngroups
avg_spring = spring_signals["etf_code"].nunique().mean() if n_spring > 0 else 0

# ============================================================
# Trade detail table rows (all 1099 trades)
# ============================================================
def trade_rows(trades):
    rows = []
    for _, t in trades.iterrows():
        cls = "pos" if t["return_pct"] > 0 else "neg"
        rows.append(f"<tr><td>{t['crash_date'].strftime('%Y-%m-%d')}</td>"
                    f"<td>{t['etf_name']}</td><td>{t['etf_code']}</td>"
                    f"<td>T+{int(t['hold_days'])}</td>"
                    f"<td class='{cls}'>{t['return_pct']:+.2f}%</td></tr>")
    return "\n".join(rows)

detail_rows_full = trade_rows(df.sort_values(["crash_date", "hold_days"]))
detail_rows_spring = trade_rows(spring_df.sort_values(["crash_date", "hold_days"])) if len(spring_df) > 0 else ""

# Per-signal trade detail
def signal_detail_table(trades):
    """Group trades by crash_date, show per-signal breakdown"""
    rows = []
    for crash_date, group in trades.groupby("crash_date", sort=True):
        cd_str = crash_date.strftime('%Y-%m-%d') if hasattr(crash_date, 'strftime') else crash_date
        n_etfs = group["etf_code"].nunique()
        for hold in HOLD_PERIODS:
            sub = group[group["hold_days"] == hold]
            if sub.empty:
                continue
            avg_ret = sub["return_pct"].mean()
            win_rate = (sub["return_pct"] > 0).sum() / len(sub) * 100
            cls = "pos" if avg_ret > 0 else "neg"
            etf_names = ", ".join(sub["etf_name"].unique())
            rows.append(f"<tr><td>{cd_str}</td><td>T+{hold}</td><td>{n_etfs}</td>"
                        f"<td>{len(sub)}</td><td>{win_rate:.0f}%</td>"
                        f"<td class='{cls}'>{avg_ret:+.2f}%</td>"
                        f"<td style='font-size:11px;max-width:300px'>{etf_names}</td></tr>")
    return "\n".join(rows)

signal_rows_full = signal_detail_table(df)
signal_rows_spring = signal_detail_table(spring_df) if len(spring_df) > 0 else ""

# ============================================================
# HTML Template
# ============================================================
html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>大盘急跌-非过热板块超跌反弹策略 回测报告</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Microsoft YaHei', 'SimHei', 'Segoe UI', sans-serif; background: #f5f6fa; color: #2d3436; line-height: 1.6; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}

/* Header */
.header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); color: white; padding: 40px 30px; border-radius: 12px; margin-bottom: 24px; }}
.header h1 {{ font-size: 28px; margin-bottom: 8px; }}
.header .subtitle {{ opacity: 0.8; font-size: 14px; }}

/* Cards */
.card {{ background: white; border-radius: 10px; padding: 24px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
.card h2 {{ font-size: 20px; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 2px solid #0f3460; }}
.card h3 {{ font-size: 16px; margin: 16px 0 10px; color: #0f3460; }}

/* Summary boxes */
.summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; margin-bottom: 20px; }}
.summary-box {{ background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 18px; border-radius: 8px; text-align: center; }}
.summary-box .num {{ font-size: 32px; font-weight: bold; }}
.summary-box .label {{ font-size: 13px; opacity: 0.9; margin-top: 4px; }}
.summary-box.green {{ background: linear-gradient(135deg, #11998e, #38ef7d); }}
.summary-box.red {{ background: linear-gradient(135deg, #eb3349, #f45c43); }}
.summary-box.blue {{ background: linear-gradient(135deg, #4facfe, #00f2fe); }}

/* Tables */
table {{ width: 100%; border-collapse: collapse; font-size: 14px; margin: 12px 0; }}
th {{ background: #0f3460; color: white; padding: 10px 12px; text-align: left; font-weight: 600; }}
td {{ padding: 8px 12px; border-bottom: 1px solid #e9ecef; }}
tr:hover {{ background: #f8f9fa; }}
.pos {{ color: #e74c3c; font-weight: 600; }}
.neg {{ color: #27ae60; font-weight: 600; }}

/* Chart */
.chart-img {{ width: 100%; border-radius: 8px; margin: 12px 0; }}

/* Nav tabs */
.tabs {{ display: flex; gap: 4px; margin-bottom: 16px; flex-wrap: wrap; }}
.tab-btn {{ padding: 8px 18px; border: none; background: #e9ecef; cursor: pointer; border-radius: 6px 6px 0 0; font-size: 14px; font-family: inherit; }}
.tab-btn.active {{ background: #0f3460; color: white; }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}

/* Scrollable table */
.scroll-table {{ max-height: 600px; overflow-y: auto; border: 1px solid #e9ecef; border-radius: 6px; }}
.scroll-table table {{ margin: 0; }}
.scroll-table thead th {{ position: sticky; top: 0; z-index: 1; }}

/* Footer */
.footer {{ text-align: center; padding: 30px; color: #999; font-size: 13px; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>大盘急跌-非过热板块超跌反弹策略</h1>
  <div class="subtitle">回测报告 | 2025-01-02 ~ 2026-05-30 | 生成于 2026-05-31</div>
</div>

<!-- ==================== Strategy Summary ==================== -->
<div class="card">
  <h2>策略参数</h2>
  <table>
    <tr><th>参数</th><th>值</th><th>说明</th></tr>
    <tr><td>大盘指数</td><td>沪深300 (000300.SH)</td><td>急跌判定基准</td></tr>
    <tr><td>急跌阈值</td><td>&le; -0.7%</td><td>沪深300单日跌幅触发</td></tr>
    <tr><td>过热度回顾</td><td>10 个交易日</td><td>统计窗口</td></tr>
    <tr><td>非过热判定</td><td>10日累计涨幅排名后 50%</td><td>取涨幅垫底的一半ETF</td></tr>
    <tr><td>跟跌确认</td><td>急跌日 ETF 跌幅 &le; -0.3%</td><td>确保恐慌跟跌</td></tr>
    <tr><td>持有期</td><td>T+2 / T+5 / T+8 / T+10</td><td>分别统计对比</td></tr>
    <tr><td>仓位</td><td>等权买入，满仓</td><td>符合条件的 ETF 均分资金</td></tr>
    <tr><td>止盈/止损</td><td>无</td><td>纯持有到期</td></tr>
    <tr><td>ETF 候选池</td><td>15 只</td><td>科技+制造方向（军工/通信/AI/半导体/电池/碳中和/电力/云计算）</td></tr>
  </table>
</div>

<!-- ==================== Key Metrics ==================== -->
<div class="card">
  <h2>核心指标</h2>
  <div class="summary-grid">
    <div class="summary-box green">
      <div class="num">48</div><div class="label">急跌信号</div>
    </div>
    <div class="summary-box blue">
      <div class="num">5.9</div><div class="label">平均每次买入ETF数</div>
    </div>
    <div class="summary-box">
      <div class="num">1099</div><div class="label">总交易笔数</div>
    </div>
    <div class="summary-box green">
      <div class="num">62.2%</div><div class="label">T+8 胜率</div>
    </div>
    <div class="summary-box">
      <div class="num">+2.10%</div><div class="label">T+8 平均收益</div>
    </div>
  </div>
</div>

<!-- ==================== Full Period ==================== -->
<div class="card">
  <h2>全量回测 (2025-01 ~ 2026-05)</h2>
  <p style="color:#666;margin-bottom:12px">{n_signals} 次急跌信号 | 平均每次买入 {avg_etfs:.1f} 只 ETF | 共 {len(df)} 笔交易</p>
  {full_stats.to_html(index=False, border=0, classes='stats-table', justify='center')}
  <h3>各持有期极值</h3>
  <table>{best_worst_full}</table>
  <img class="chart-img" src="data:image/png;base64,{chart_full}" alt="Cumulative Return Full">
</div>

<!-- ==================== 2026 Spring ==================== -->
<div class="card">
  <h2>2026年3-5月 单独回测</h2>
  <p style="color:#666;margin-bottom:12px">{n_spring} 次急跌信号 | 平均每次买入 {avg_spring:.1f} 只 ETF | 共 {len(spring_df)} 笔交易</p>
  {spring_stats.to_html(index=False, border=0, classes='stats-table', justify='center')}
  <h3>各持有期极值</h3>
  <table>{best_worst_spring}</table>
  <img class="chart-img" src="data:image/png;base64,{chart_spring}" alt="Cumulative Return Spring">
</div>

<!-- ==================== Trade Details ==================== -->
<div class="card">
  <h2>交易明细</h2>
  <div class="tabs">
    <button class="tab-btn active" onclick="showTab('signal-full')">按信号汇总 (全量)</button>
    <button class="tab-btn" onclick="showTab('signal-spring')">按信号汇总 (2026春)</button>
    <button class="tab-btn" onclick="showTab('trade-full')">逐笔交易 (全量, {len(df)}笔)</button>
    <button class="tab-btn" onclick="showTab('trade-spring')">逐笔交易 (2026春, {len(spring_df)}笔)</button>
  </div>

  <div id="signal-full" class="tab-content active">
    <div class="scroll-table">
      <table>
        <thead><tr><th>急跌日期</th><th>持有期</th><th>买入ETF数</th><th>交易数</th><th>胜率</th><th>平均收益</th><th>买入ETF</th></tr></thead>
        <tbody>{signal_rows_full}</tbody>
      </table>
    </div>
  </div>

  <div id="signal-spring" class="tab-content">
    <div class="scroll-table">
      <table>
        <thead><tr><th>急跌日期</th><th>持有期</th><th>买入ETF数</th><th>交易数</th><th>胜率</th><th>平均收益</th><th>买入ETF</th></tr></thead>
        <tbody>{signal_rows_spring}</tbody>
      </table>
    </div>
  </div>

  <div id="trade-full" class="tab-content">
    <div class="scroll-table">
      <table>
        <thead><tr><th>急跌日期</th><th>ETF名称</th><th>代码</th><th>持有期</th><th>收益率</th></tr></thead>
        <tbody>{detail_rows_full}</tbody>
      </table>
    </div>
  </div>

  <div id="trade-spring" class="tab-content">
    <div class="scroll-table">
      <table>
        <thead><tr><th>急跌日期</th><th>ETF名称</th><th>代码</th><th>持有期</th><th>收益率</th></tr></thead>
        <tbody>{detail_rows_spring}</tbody>
      </table>
    </div>
  </div>
</div>

<!-- ==================== Conclusions ==================== -->
<div class="card">
  <h2>结论与分析</h2>
  <ol style="padding-left:20px;line-height:2">
    <li><strong>T+8 是最优持有期</strong>：累计收益最高 (+566%)，平均单笔收益最高 (+2.10%)，胜率 62.2%。T+10 胜率稍高(64.8%)但累计收益略低。</li>
    <li><strong>ETF 候选池越大越好</strong>：15 只 ETF 的全量回测结果远优于此前 5 只的初步测试（T+8: +566% vs +131%），说明策略的有效性依赖于足够多的候选标的来筛选"真正冷门"的板块。</li>
    <li><strong>2026年春季收益依然可观</strong>：3-5 月 T+8 累计 +136%，虽低于全周期水平但策略远未失效。胜率略降至 53-59%，反映市场波动加剧。</li>
    <li><strong>不设止损的风险可控</strong>：T+8 最大单笔亏损仅 -8.74%（芯片 ETF 在 2026-03-19），T+10 最大亏损 -18%（通信 ETF 在 2025-03-21）。极端情况出现频率低，但单次影响大。</li>
    <li><strong>短期持有(T+2)不如中长期</strong>：T+2 胜率高(63%)但平均收益低(+0.71%)，说明恐慌后 1-2 天的反弹幅度有限，真正的修复需要 1-2 周。</li>
  </ol>
</div>

<div class="footer">
  Generated by Crash-Rebound Backtest Engine | Data: efinance + akshare | 仅供参考，不构成投资建议
</div>

</div>

<script>
function showTab(id) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  event.target.classList.add('active');
}}
</script>
</body>
</html>"""

# Write
with open("回测报告.html", "w", encoding="utf-8") as f:
    f.write(html)

print("Report generated: 回测报告.html")
print(f"  Full stats: {len(full_stats)} periods, {len(df)} trades")
print(f"  Spring stats: {len(spring_stats) if spring_stats is not None else 0} periods, {len(spring_df)} trades")
