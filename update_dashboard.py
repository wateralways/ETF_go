"""
Update index.html with latest signal results.
Called by GitHub Actions after daily_analysis.py.
"""
import json, re

with open("signal_result.json", "r", encoding="utf-8") as f:
    r = json.load(f)

with open("signal_status.html", "r", encoding="utf-8") as f:
    badge = f.read().strip()

with open("index.html", "r", encoding="utf-8") as f:
    html = f.read()

# ---- 1. Replace header status badge ----
html = re.sub(
    r'<div class="status-badge [^"]*"[^>]*>[^<]*</div>',
    badge,
    html,
    count=1,
)

# ---- 2. Update date in header ----
html = re.sub(
    r"(最后更新</div>\s*<div style=\"font-weight:600\">)[^<]+",
    rf"\g<1>{r['date']}",
    html,
)

# ---- 3. Generate signal status card ----
direction = "down" if r["csi300_pct"] < 0 else "up"
advice = "等待下一个急跌日"

if r["is_crash"]:
    if r["n_buy"] > 0:
        strength = "触发"
        advice = f"尾盘等权买入 {r['n_buy']} 只 ETF (各 {100/r['n_buy']:.1f}%)"
    else:
        strength = "触发但无符合条件的ETF"
else:
    strength = f"未触发 (距阈值差 {abs(r['csi300_pct'] - (-0.7)):.2f}%)"

trend_desc = f"{r['trend']} (CSI300 {r['csi300_close']:.0f}"
if r["ma60"]:
    trend_desc += f" vs MA60 {r['ma60']:.0f}"
trend_desc += ")"

signal_card = f"""  <!-- Signal Status -->
  <div class="card">
    <h2>Signal Status (auto-updated)</h2>
    <table>
      <tr><td style="color:var(--muted)">Latest trading day</td><td><strong>{r['date']}</strong></td></tr>
      <tr><td style="color:var(--muted)">CSI 300</td><td><span class="{direction}">{r['csi300_pct']:+.2f}%</span></td></tr>
      <tr><td style="color:var(--muted)">Crash triggered?</td><td><span class="status-badge {'active' if r['is_crash'] else 'off'}">{strength}</span></td></tr>
      <tr><td style="color:var(--muted)">Market trend</td><td>{trend_desc}</td></tr>
      <tr><td style="color:var(--muted)">Advice</td><td>{advice}</td></tr>
    </table>
  </div>"""

html = html.replace("<!-- SIGNAL_STATUS_CARD -->", signal_card)

# ---- 4. If crash, inject ETF ranking ----
if r["is_crash"] and r["buy_list"]:
    items = ""
    for etf in r["buy_list"]:
        items += (
            f"<tr><td>{etf['code']}</td><td>{etf['name']}</td>"
            f"<td>{etf['ret_10d']:+.2f}%</td><td>{etf['today_pct']:+.2f}%</td>"
            f"<td><span class=\"tag buy\">BUY</span></td></tr>"
        )
    w = 100 / len(r["buy_list"])
    buy_flash = (
        f'<div class="signal-flash" style="margin-top:20px">'
        f'<h3>SIGNAL TRIGGERED - {r["date"]}</h3>'
        f'<p class="detail">CSI300 {r["csi300_pct"]:+.2f}% | {r["trend"]} | '
        f'Buy {r["n_buy"]} ETFs ({w:.1f}% each)</p>'
        f'<table style="margin-top:12px">'
        f'<thead><tr><th>Code</th><th>Name</th><th>10d</th><th>Today</th><th></th></tr></thead>'
        f'{items}</table></div>'
    )
    html = html.replace(
        "<!-- Quick Rules -->",
        f"{buy_flash}\n          <!-- Quick Rules -->",
    )

    if r["all_etfs"]:
        rows = ""
        for etf in r["all_etfs"]:
            tag = '<span class="tag buy">BUY</span>' if etf["cold"] else ""
            rows += (
                f"<tr><td>{etf['code']}</td><td>{etf['name']}</td>"
                f"<td>{etf['ret_10d']:+.2f}%</td><td>{etf['today_pct']:+.2f}%</td>"
                f"<td>{tag}</td></tr>"
            )
        rank = (
            f'<div class="card" style="margin-top:16px">'
            f'<h2>ETF Rankings (Crash: {r["date"]})</h2>'
            f'<table><thead><tr><th>Code</th><th>Name</th>'
            f'<th>10d Ret</th><th>Today</th><th>Status</th></tr></thead>'
            f'{rows}</table></div>'
        )
        html = html.replace(
            "</ul>\n          </div>\n        </div>\n        </section>",
            f"</ul>\n          </div>\n        </div>\n        {rank}\n        </section>",
        )

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("Dashboard updated")
