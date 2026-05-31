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

# Replace status badge
html = re.sub(
    r'<div class="status-badge [^"]*"[^>]*>[^<]*</div>',
    badge,
    html,
    count=1,
)

# Update date
html = re.sub(
    r"(最后更新</div>\s*<div style=\"font-weight:600\">)[^<]+",
    rf"\g<1>{r['date']}",
    html,
)

# If crash triggered, inject buy list after signal status card
if r["is_crash"] and r["buy_list"]:
    items = ""
    for etf in r["buy_list"]:
        items += (
            f"<tr><td>{etf['code']}</td><td>{etf['name']}</td>"
            f"<td>{etf['ret_10d']:+.2f}%</td><td>{etf['today_pct']:+.2f}%</td>"
            f"<td><span class=\"tag buy\">BUY</span></td></tr>"
        )

    w = 100 / len(r["buy_list"]) if r["buy_list"] else 0
    flash = (
        f'<div class="signal-flash" style="margin-top:20px">'
        f'<h3>Signal Triggered - {r["date"]}</h3>'
        f'<p class="detail">CSI300 {r["csi300_pct"]:+.2f}% | {r["trend"]} | '
        f'Buy {r["n_buy"]} ETFs ({w:.1f}% each)</p>'
        f'<table style="margin-top:12px">'
        f'<thead><tr><th>Code</th><th>Name</th><th>10d</th><th>Today</th><th></th></tr></thead>'
        f'{items}</table></div>'
    )

    # Insert after signal card's closing table
    html = html.replace(
        "</table>\n          </div>\n\n          <!-- Quick Rules -->",
        f"</table>\n          </div>\n{flash}\n          <!-- Quick Rules -->",
    )

    # ETF ranking table
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
            f'<h2>ETF Rankings (Crash Day: {r["date"]})</h2>'
            f'<table><thead><tr><th>Code</th><th>Name</th>'
            f'<th>10d Return</th><th>Today</th><th>Status</th></tr></thead>'
            f'{rows}</table></div>'
        )
        html = html.replace(
            "</ul>\n          </div>\n        </div>\n        </section>",
            f"</ul>\n          </div>\n        </div>\n        {rank}\n        </section>",
        )

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("Dashboard updated")
