#!/usr/bin/env python3
"""
Investment Dashboard v1 — Daily Market Pulse
Generates HTML pushed to GitHub Pages alongside the stock screener.
Run daily on PythonAnywhere.

Data sources:
  - Finnhub   : all price data (quotes + forex), news, COT, economic calendar
  Note: yfinance removed — PythonAnywhere blocks Yahoo Finance connections.
  US-listed ETF proxies used for international indices.
"""

import json, base64, requests, time
from datetime import datetime, timedelta
import finnhub

from config import FINNHUB_API_KEY, GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO

TODAY     = datetime.today().strftime("%Y-%m-%d")
WEEK_AGO  = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
NEXT_2W   = (datetime.today() + timedelta(days=14)).strftime("%Y-%m-%d")
COT_FROM  = (datetime.today() - timedelta(days=60)).strftime("%Y-%m-%d")
TIMESTAMP = datetime.now().strftime("%d %b %Y · %H:%M")

fh = finnhub.Client(api_key=FINNHUB_API_KEY)

# ── Formatters ────────────────────────────────────────────────────────────────
def fmt(v, dp=2):
    if v is None: return "—"
    return f"{v:,.{dp}f}"

def fmt_chg(v):
    if v is None: return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%"

def chg_cls(v):
    if v is None: return ""
    return "up" if v > 0 else "down"

def arrow(v):
    if v is None: return ""
    return "▲" if v > 0 else "▼"

# ═════════════════════════════════════════════════════════════════════════════
# STEP 1 — PRICE DATA (Finnhub quotes + forex rates)
# ETF proxies used for international indices since yfinance is blocked
# on PythonAnywhere. All data via Finnhub API.
# ═════════════════════════════════════════════════════════════════════════════
print("=" * 60)
print("STEP 1 — Price data (Finnhub)")
print("=" * 60)

def fh_quote(symbol):
    """Fetch current price + daily % change from Finnhub."""
    try:
        q = fh.quote(symbol)
        if not q or not q.get("c"):
            return {"price": None, "chg_pct": None}
        price = q["c"]
        return {
            "price":    round(price, 4 if price < 10 else 2),
            "chg_pct": round(q.get("dp") or 0, 2),
        }
    except Exception:
        return {"price": None, "chg_pct": None}

# ── Index ETF proxies (label, finnhub_symbol, group) ─────────────────────────
# SPY/QQQ/DIA/IWM are the standard US ETFs tracking the major indices.
# EWU/EWG/EWQ etc. are iShares country ETFs — good daily proxies.
# INDY/EPI/SCIF track Indian markets in USD.
INDEX_DEFS = [
    ("S&P 500 (SPY)",     "SPY",   "US Markets"),
    ("Nasdaq 100 (QQQ)",  "QQQ",   "US Markets"),
    ("Dow Jones (DIA)",   "DIA",   "US Markets"),
    ("Russell 2000 (IWM)","IWM",   "US Markets"),
    ("VIX ETF (VIXY)",    "VIXY",  "US Markets"),
    ("Nifty 50 (INDY)",   "INDY",  "India"),
    ("India Broad (EPI)", "EPI",   "India"),
    ("India Small (SCIF)","SCIF",  "India"),
    ("FTSE 100 (EWU)",    "EWU",   "Europe"),
    ("DAX (EWG)",         "EWG",   "Europe"),
    ("CAC 40 (EWQ)",      "EWQ",   "Europe"),
    ("Euro Stoxx (FEZ)",  "FEZ",   "Europe"),
    ("Japan (EWJ)",       "EWJ",   "Asia Pacific"),
    ("Hong Kong (EWH)",   "EWH",   "Asia Pacific"),
    ("China (MCHI)",      "MCHI",  "Asia Pacific"),
    ("Australia (EWA)",   "EWA",   "Asia Pacific"),
]

COMMODITY_DEFS = [
    ("Gold (GLD)",      "GLD"),
    ("Silver (SLV)",    "SLV"),
    ("WTI Oil (USO)",   "USO"),
    ("Brent (BNO)",     "BNO"),
    ("Copper (CPER)",   "CPER"),
    ("Nat Gas (UNG)",   "UNG"),
]

BOND_DEFS = [
    ("20Y+ Bonds (TLT)", "TLT"),
    ("7-10Y Bonds (IEF)","IEF"),
    ("1-3Y Bonds (SHY)", "SHY"),
]

# Fetch all quotes with a small sleep to respect rate limits
print("  Fetching index ETFs...")
index_prices = {}
for label, sym, grp in INDEX_DEFS:
    index_prices[sym] = fh_quote(sym)
    time.sleep(0.12)

print("  Fetching commodities...")
commod_prices = {}
for label, sym in COMMODITY_DEFS:
    commod_prices[sym] = fh_quote(sym)
    time.sleep(0.12)

print("  Fetching bond ETFs...")
bond_prices = {}
for label, sym in BOND_DEFS:
    bond_prices[sym] = fh_quote(sym)
    time.sleep(0.12)

ok = sum(1 for v in {**index_prices, **commod_prices}.values() if v.get("price"))
print(f"  ✓ {ok}/{len(INDEX_DEFS)+len(COMMODITY_DEFS)} instruments fetched")

# ── Forex via Finnhub forex_rates ─────────────────────────────────────────────
print("  Fetching forex rates...")
forex_list = []
try:
    raw_rates = fh.forex_rates(base="USD").get("quote", {})

    # Also fetch UUP (USD bull ETF) for DXY proxy with % change
    uup = fh_quote("UUP")
    time.sleep(0.12)

    FOREX_DISPLAY = [
        ("DXY (UUP proxy)", None,  None,   uup),
        ("USD/INR",         "INR", False,  None),
        ("EUR/USD",         "EUR", True,   None),   # inverse: 1/rate
        ("USD/JPY",         "JPY", False,  None),
        ("GBP/USD",         "GBP", True,   None),   # inverse
        ("AUD/USD",         "AUD", True,   None),   # inverse
        ("USD/CNY",         "CNY", False,  None),
    ]
    for label, currency, inverse, override in FOREX_DISPLAY:
        if override is not None:
            forex_list.append({"label": label, **override})
        elif currency and currency in raw_rates:
            r = raw_rates[currency]
            price = round(1/r, 4) if inverse else round(r, 4)
            forex_list.append({"label": label, "price": price, "chg_pct": None})
        else:
            forex_list.append({"label": label, "price": None, "chg_pct": None})
    print(f"  ✓ Forex: {len([f for f in forex_list if f.get('price')])} rates")
except Exception as e:
    print(f"  ✗ Forex: {e}")
    forex_list = [{"label": l, "price": None, "chg_pct": None}
                  for l in ["DXY","USD/INR","EUR/USD","USD/JPY","GBP/USD","AUD/USD","USD/CNY"]]

# ── Assemble grouped data ─────────────────────────────────────────────────────
def get_group(name):
    return [
        {"label": l, "ticker": t,
         **index_prices.get(t, {"price": None, "chg_pct": None})}
        for l, t, g in INDEX_DEFS if g == name
    ]

indices_us    = get_group("US Markets")
indices_india = get_group("India")
indices_eu    = get_group("Europe")
indices_asia  = get_group("Asia Pacific")

commod_list = [
    {"label": l, "ticker": t, **commod_prices.get(t, {"price": None, "chg_pct": None})}
    for l, t in COMMODITY_DEFS
]

yield_list = [
    {"label": l, "ticker": t, **bond_prices.get(t, {"price": None, "chg_pct": None})}
    for l, t in BOND_DEFS
]

# Bond spread proxy: TLT/SHY price ratio as loose long-short indicator
tlt_p = bond_prices.get("TLT", {}).get("price")
shy_p = bond_prices.get("SHY", {}).get("price")
tlt_c = bond_prices.get("TLT", {}).get("chg_pct")
shy_c = bond_prices.get("SHY", {}).get("chg_pct")
spread_val = round(tlt_c - shy_c, 2) if tlt_c is not None and shy_c is not None else None
spread_str = (("+" if spread_val and spread_val > 0 else "") + f"{spread_val}%") if spread_val is not None else "—"
spread_cls = chg_cls(spread_val)
spread_lbl = ("Long duration outperforming" if spread_val and spread_val > 0
              else "Short end outperforming" if spread_val and spread_val is not None else "—")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 2 — NEWS (Finnhub)
# ═════════════════════════════════════════════════════════════════════════════
print("STEP 2 — News")
news = []
try:
    raw_news = fh.general_news(category="general", min_id=0)
    for n in (raw_news or [])[:18]:
        if not n.get("headline"):
            continue
        ts = n.get("datetime", 0)
        news.append({
            "headline": n.get("headline", ""),
            "summary":  (n.get("summary") or "")[:180],
            "source":   n.get("source", ""),
            "url":      n.get("url", "#"),
            "dt":       datetime.fromtimestamp(ts).strftime("%d %b · %H:%M") if ts else "",
        })
    print(f"  ✓ {len(news)} items")
except Exception as e:
    print(f"  ✗ {e}")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 3 — COT POSITIONING (Finnhub REST)
# ═════════════════════════════════════════════════════════════════════════════
print("STEP 3 — COT data")

# CFTC market codes — use short codes which are URL-safe
# Full names confirmed via search_cot_markets MCP tool
COT_DEFS = [
    ("S&P 500",    "13874+"),   # S&P 500 Consolidated - CME
    ("Nasdaq 100", "20974+"),   # NASDAQ-100 Consolidated - CME
    ("Gold",       "088691"),   # Gold - COMEX
    ("WTI Crude",  "067411"),   # Crude Oil Light Sweet - ICE Europe
    ("EUR/USD",    "099741"),   # Euro FX - CME
    ("10Y T-Note", "043602"),   # 10-Year US Treasury Notes - CBOT
    ("USD Index",  "098662"),   # USD Index - ICE US
]

from urllib.parse import quote

cot_data = []
for label, code in COT_DEFS:
    try:
        url = (f"https://finnhub.io/api/v1/cot/legacy"
               f"?symbol={quote(code)}&from={COT_FROM}&to={TODAY}&token={FINNHUB_API_KEY}")
        r = requests.get(url, timeout=10)
        if not r.text.strip():
            print(f"  ⚠ COT {label}: empty response (status {r.status_code})")
            continue
        d = r.json()
        entries = d if isinstance(d, list) else d.get("data", [])
        if not entries:
            print(f"  ⚠ COT {label}: no entries returned")
            continue
        latest  = entries[-1]
        # Field names from Finnhub COT API
        lng_nc  = int(latest.get("large_spec_long",  latest.get("longNC",  0)) or 0)
        sht_nc  = int(latest.get("large_spec_short", latest.get("shortNC", 0)) or 0)
        net     = int(latest.get("large_spec_net", lng_nc - sht_nc))
        total   = lng_nc + sht_nc
        pct     = round(net / total * 100, 1) if total > 0 else 0
        rdate   = str(latest.get("date", ""))[:10]
        cot_data.append({
            "label":    label,
            "net":      net,
            "pct":      pct,
            "long_nc":  lng_nc,
            "short_nc": sht_nc,
            "date":     rdate,
        })
        time.sleep(0.3)
    except Exception as e:
        print(f"  ⚠ COT {label}: {e}")

print(f"  ✓ {len(cot_data)} symbols")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 4 — ECONOMIC CALENDAR (Finnhub)
# ═════════════════════════════════════════════════════════════════════════════
print("STEP 4 — Economic calendar")
econ_events = []
try:
    cal_url = (f"https://finnhub.io/api/v1/economic_calendar"
               f"?from={TODAY}&to={NEXT_2W}&token={FINNHUB_API_KEY}")
    cal_r = requests.get(cal_url, timeout=10)
    cal   = cal_r.json() if cal_r.text.strip() else {}
    if cal and "economicCalendar" in cal:
        for e in cal["economicCalendar"]:
            if e.get("impact") in ("high", "medium"):
                econ_events.append({
                    "event":    e.get("event", ""),
                    "country":  (e.get("country") or "").upper(),
                    "date":     (e.get("time") or "")[:10],
                    "impact":   e.get("impact", ""),
                    "prev":     str(e.get("prev") or "—"),
                    "estimate": str(e.get("estimate") or "—"),
                    "actual":   str(e.get("actual") or "—"),
                })
    econ_events = sorted(econ_events, key=lambda x: x["date"])[:25]
    print(f"  ✓ {len(econ_events)} events")
except Exception as e:
    print(f"  ✗ {e} (economic calendar may require higher Finnhub tier)")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 5 — BUILD HTML
# ═════════════════════════════════════════════════════════════════════════════
print("STEP 5 — Building HTML")

# ── HTML component builders ───────────────────────────────────────────────────

def mkt_card(title, items):
    rows = ""
    for it in items:
        price = fmt(it["price"], dp=4 if it["price"] and it["price"] < 10 else 2)
        rows += f"""
        <div class="mkt-row">
          <span class="mkt-label">{it['label']}</span>
          <span class="mkt-price">{price}</span>
          <span class="mkt-chg {chg_cls(it['chg_pct'])}">{arrow(it['chg_pct'])} {fmt_chg(it['chg_pct'])}</span>
        </div>"""
    return f"""
    <div class="card">
      <div class="card-title">{title}</div>
      {rows}
    </div>"""

def tbl_row(it):
    price = fmt(it["price"], dp=4 if it["price"] and it["price"] < 10 else 2)
    return f"""<tr>
      <td>{it['label']}</td>
      <td class="mono price-cell">{price}</td>
      <td class="mono {chg_cls(it['chg_pct'])}">{arrow(it['chg_pct'])} {fmt_chg(it['chg_pct'])}</td>
    </tr>"""

def yield_row(it):
    price = (fmt(it["price"], dp=2) + "%") if it["price"] else "—"
    return f"""<tr>
      <td>{it['label']}</td>
      <td class="mono price-cell">{price}</td>
      <td class="mono {chg_cls(it['chg_pct'])}">{arrow(it['chg_pct'])} {fmt_chg(it['chg_pct'])}</td>
    </tr>"""

def cot_bar_html(it):
    bar_w   = min(abs(it["pct"]), 100)
    is_long = it["pct"] >= 0
    sent    = f"NET {'LONG' if is_long else 'SHORT'} {abs(it['pct']):.0f}%"
    cls     = "up" if is_long else "down"
    bar_cls = "bar-long" if is_long else "bar-short"
    sign    = "+" if it["net"] > 0 else ""
    return f"""
    <div class="cot-row">
      <div class="cot-meta">
        <span class="cot-label">{it['label']}</span>
        <span class="cot-badge {cls}">{sent}</span>
        <span class="cot-date">{it['date']}</span>
      </div>
      <div class="cot-track"><div class="cot-bar {bar_cls}" style="width:{bar_w}%"></div></div>
      <div class="cot-nums">
        <span class="up">▲ {it['long_nc']:,} long</span>
        <span class="down">▼ {it['short_nc']:,} short</span>
        <span>Net {sign}{it['net']:,}</span>
      </div>
    </div>"""

def news_card_html(n):
    return f"""
    <a href="{n['url']}" target="_blank" rel="noopener" class="news-card">
      <div class="news-meta">{n['source']} · {n['dt']}</div>
      <div class="news-headline">{n['headline']}</div>
      <div class="news-summary">{n['summary']}</div>
    </a>"""

def cal_row_html(e):
    imp_cls = "impact-high" if e["impact"] == "high" else "impact-med"
    return f"""<tr>
      <td><span class="cbadge">{e['country']}</span></td>
      <td class="edate">{e['date']}</td>
      <td>{e['event']}</td>
      <td><span class="idot {imp_cls}"></span>{e['impact'].title()}</td>
      <td class="mono">{e['prev']}</td>
      <td class="mono">{e['estimate']}</td>
      <td class="mono">{e['actual']}</td>
    </tr>"""

# ── Assemble sections ─────────────────────────────────────────────────────────
markets_html = "".join([
    mkt_card("US Markets",   indices_us),
    mkt_card("India",        indices_india),
    mkt_card("Europe",       indices_eu),
    mkt_card("Asia Pacific", indices_asia),
])

forex_html    = "".join(tbl_row(x) for x in forex_list)
commod_html   = "".join(tbl_row(x) for x in commod_list)
yield_html    = "".join(yield_row(x) for x in yield_list)
cot_html      = "".join(cot_bar_html(x) for x in cot_data) if cot_data else "<p class='empty'>COT data unavailable — check symbol mapping</p>"
news_html     = "".join(news_card_html(x) for x in news) if news else "<p class='empty'>No news available</p>"
cal_html      = "".join(cal_row_html(x) for x in econ_events) if econ_events else "<tr><td colspan='7' class='empty'>No events found — economic calendar may require Finnhub premium</td></tr>"

# ── Full HTML ─────────────────────────────────────────────────────────────────
HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Market Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=Instrument+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
  --ink:    #0a0a0a;
  --ink2:   #3a3a3a;
  --ink3:   #7a7a7a;
  --paper:  #f5f2eb;
  --paper2: #ede9e0;
  --paper3: #e4dfd3;
  --accent: #c8410a;
  --accent2:#1a3a5c;
  --green:  #1a6b3a;
  --red:    #b52525;
  --gold:   #b07d2a;
  --border: rgba(10,10,10,0.12);
  --serif:  'DM Serif Display', Georgia, serif;
  --sans:   'Instrument Sans', sans-serif;
  --mono:   'DM Mono', monospace;
}}

html {{ scroll-behavior: smooth; }}
body {{ font-family: var(--sans); background: var(--paper); color: var(--ink); min-height: 100vh; }}

/* ── MASTHEAD ── */
.masthead {{
  border-bottom: 2px solid var(--ink);
  padding: 0 2rem;
  position: sticky; top: 0;
  background: var(--paper); z-index: 100;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center; gap: 1rem; min-height: 56px;
}}
.masthead-left {{ display: flex; align-items: center; gap: .75rem; }}
.label-pill {{
  font-family: var(--mono); font-size: 10px;
  letter-spacing: .15em; text-transform: uppercase;
  color: var(--ink3); border: 1px solid var(--border);
  padding: 3px 8px; border-radius: 2px;
}}
.masthead-title {{
  font-family: var(--serif); font-size: 22px;
  letter-spacing: -.02em; text-align: center; line-height: 1.1;
}}
.masthead-right {{ display: flex; align-items: center; justify-content: flex-end; gap: .75rem; }}
.nav-link {{
  font-family: var(--mono); font-size: 11px; color: var(--ink3);
  text-decoration: none; letter-spacing: .1em; text-transform: uppercase;
  padding: 4px 10px; border: 1px solid var(--border);
  border-radius: 2px; transition: all .15s;
}}
.nav-link:hover {{ background: var(--ink); color: var(--paper); border-color: var(--ink); }}
.nav-link.active {{ background: var(--ink); color: var(--paper); border-color: var(--ink); }}
.ts {{ font-family: var(--mono); font-size: 10px; color: var(--ink3); }}

/* ── LAYOUT ── */
.page {{ max-width: 1400px; margin: 0 auto; padding: 2rem; }}
.section {{ margin-bottom: 3rem; }}
.section-title {{
  font-family: var(--serif); font-size: 20px;
  letter-spacing: -.01em; margin-bottom: 1.25rem;
  padding-bottom: .6rem; border-bottom: 1px solid var(--border);
  display: flex; align-items: baseline; gap: 1rem;
}}
.section-sub {{ font-family: var(--mono); font-size: 10px; color: var(--ink3); letter-spacing: .1em; }}

/* ── MARKET GRID ── */
.market-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1px; background: var(--border);
  border: 1px solid var(--border);
}}
.card {{ background: var(--paper); padding: 1.25rem 1.5rem; }}
.card-title {{
  font-family: var(--mono); font-size: 10px;
  letter-spacing: .15em; text-transform: uppercase;
  color: var(--ink3); margin-bottom: .75rem;
}}
.mkt-row {{
  display: grid; grid-template-columns: 1fr auto auto;
  gap: .5rem; padding: .35rem 0;
  border-bottom: 1px solid var(--border); align-items: center;
}}
.mkt-row:last-child {{ border-bottom: none; }}
.mkt-label {{ font-size: 13px; color: var(--ink2); }}
.mkt-price {{ font-family: var(--mono); font-size: 13px; font-weight: 500; text-align: right; }}
.mkt-chg {{ font-family: var(--mono); font-size: 12px; min-width: 72px; text-align: right; }}

/* ── TWO-COL DATA TABLES ── */
.two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
@media (max-width: 700px) {{ .two-col {{ grid-template-columns: 1fr; }} }}

.dtable {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.dtable th {{
  font-family: var(--mono); font-size: 10px; letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink3);
  padding: .4rem .6rem; text-align: left;
  border-bottom: 1px solid var(--ink);
}}
.dtable td {{ padding: .45rem .6rem; border-bottom: 1px solid var(--border); }}
.dtable tr:hover td {{ background: var(--paper2); }}
.price-cell {{ font-weight: 500; }}

/* ── YIELD PANEL ── */
.yield-panel {{
  display: grid; grid-template-columns: 1fr auto; gap: 2rem;
  background: var(--paper2); border: 1px solid var(--border); padding: 1.5rem;
  align-items: start;
}}
@media (max-width: 600px) {{ .yield-panel {{ grid-template-columns: 1fr; }} }}
.spread-box {{
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: .5rem; min-width: 180px;
}}
.spread-lbl {{ font-family: var(--mono); font-size: 10px; color: var(--ink3); letter-spacing: .1em; text-transform: uppercase; text-align: center; }}
.spread-val {{ font-family: var(--serif); font-size: 40px; line-height: 1; }}
.spread-desc {{ font-family: var(--mono); font-size: 10px; color: var(--ink3); text-align: center; }}

/* ── COT ── */
.cot-list {{ display: flex; flex-direction: column; gap: .75rem; }}
.cot-row {{
  background: var(--paper2); padding: 1rem 1.25rem;
  border: 1px solid var(--border);
}}
.cot-meta {{ display: flex; align-items: center; gap: .75rem; margin-bottom: .5rem; flex-wrap: wrap; }}
.cot-label {{ font-size: 14px; font-weight: 600; }}
.cot-badge {{
  font-family: var(--mono); font-size: 10px;
  letter-spacing: .08em; padding: 2px 7px;
  border-radius: 2px; font-weight: 500;
}}
.cot-badge.up  {{ background: rgba(26,107,58,.12); color: var(--green); }}
.cot-badge.down {{ background: rgba(181,37,37,.10); color: var(--red); }}
.cot-date {{ font-family: var(--mono); font-size: 10px; color: var(--ink3); margin-left: auto; }}
.cot-track {{
  height: 6px; background: var(--paper3);
  border-radius: 3px; overflow: hidden; margin-bottom: .5rem;
}}
.cot-bar {{ height: 100%; border-radius: 3px; }}
.bar-long  {{ background: var(--green); }}
.bar-short {{ background: var(--red); }}
.cot-nums {{ display: flex; gap: 1.25rem; font-family: var(--mono); font-size: 11px; color: var(--ink3); flex-wrap: wrap; }}

/* ── ECONOMIC CALENDAR ── */
.cal-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.cal-table th {{
  font-family: var(--mono); font-size: 10px; letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink3);
  padding: .4rem .75rem; text-align: left;
  border-bottom: 1px solid var(--ink);
}}
.cal-table td {{ padding: .5rem .75rem; border-bottom: 1px solid var(--border); }}
.cal-table tr:hover td {{ background: var(--paper2); }}
.cbadge {{
  font-family: var(--mono); font-size: 10px;
  background: var(--ink); color: var(--paper);
  padding: 2px 5px; border-radius: 2px;
}}
.edate {{ font-family: var(--mono); font-size: 12px; color: var(--ink3); white-space: nowrap; }}
.idot {{
  display: inline-block; width: 7px; height: 7px;
  border-radius: 50%; margin-right: 4px; vertical-align: middle;
}}
.impact-high {{ background: var(--red); }}
.impact-med  {{ background: var(--gold); }}

/* ── NEWS ── */
.news-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1px; background: var(--border); border: 1px solid var(--border);
}}
.news-card {{
  background: var(--paper); padding: 1.25rem 1.5rem;
  text-decoration: none; color: inherit; display: block;
  transition: background .15s;
}}
.news-card:hover {{ background: var(--paper2); }}
.news-meta {{
  font-family: var(--mono); font-size: 10px; color: var(--ink3);
  letter-spacing: .08em; text-transform: uppercase; margin-bottom: .4rem;
}}
.news-headline {{ font-size: 14px; font-weight: 500; line-height: 1.4; margin-bottom: .4rem; }}
.news-summary  {{ font-size: 12px; color: var(--ink3); line-height: 1.5; }}

/* ── UTILITIES ── */
.up   {{ color: var(--green); }}
.down {{ color: var(--red); }}
.mono {{ font-family: var(--mono); }}
.empty {{ color: var(--ink3); font-size: 13px; padding: 1rem; font-family: var(--mono); font-style: italic; }}

/* ── FOOTER ── */
.footer {{
  border-top: 1px solid var(--border); margin-top: 3rem;
  padding: 1.5rem 2rem;
  font-family: var(--mono); font-size: 11px; color: var(--ink3); text-align: center;
}}
</style>
</head>
<body>

<header class="masthead">
  <div class="masthead-left">
    <span class="label-pill">Daily</span>
    <span class="label-pill">v1</span>
  </div>
  <h1 class="masthead-title">Market Pulse</h1>
  <div class="masthead-right">
    <a href="./" class="nav-link">Screener</a>
    <a href="./dashboard.html" class="nav-link active">Dashboard</a>
    <span class="ts">{TIMESTAMP}</span>
  </div>
</header>

<main class="page">

  <!-- ── MARKET SNAPSHOT ── -->
  <section class="section">
    <h2 class="section-title">
      Market Snapshot
      <span class="section-sub">Indices · 1-day change</span>
    </h2>
    <div class="market-grid">
      {markets_html}
    </div>
  </section>

  <!-- ── FOREX & COMMODITIES ── -->
  <section class="section">
    <h2 class="section-title">
      Forex &amp; Commodities
      <span class="section-sub">Spot / front-month futures</span>
    </h2>
    <div class="two-col">
      <table class="dtable">
        <thead><tr><th>Pair</th><th>Rate</th><th>1D Change</th></tr></thead>
        <tbody>{forex_html}</tbody>
      </table>
      <table class="dtable">
        <thead><tr><th>Commodity</th><th>Price</th><th>1D Change</th></tr></thead>
        <tbody>{commod_html}</tbody>
      </table>
    </div>
  </section>

  <!-- ── YIELD CURVE ── -->
  <section class="section">
    <h2 class="section-title">
      US Treasury Bond ETFs
      <span class="section-sub">Price moves INVERSE to yield · TLT=long, IEF=mid, SHY=short</span>
    </h2>
    <div class="yield-panel">
      <table class="dtable">
        <thead><tr><th>Tenor</th><th>Yield</th><th>1D Change</th></tr></thead>
        <tbody>{yield_html}</tbody>
      </table>
      <div class="spread-box">
        <div class="spread-lbl">TLT vs SHY (1D)</div>
        <div class="spread-val {spread_cls}">{spread_str}</div>
        <div class="spread-desc">{spread_lbl}</div>
      </div>
    </div>
  </section>

  <!-- ── COT POSITIONING ── -->
  <section class="section">
    <h2 class="section-title">
      COT — Speculative Positioning
      <span class="section-sub">Non-commercial (speculator) net longs · CFTC weekly</span>
    </h2>
    <div class="cot-list">
      {cot_html}
    </div>
  </section>

  <!-- ── ECONOMIC CALENDAR ── -->
  <section class="section">
    <h2 class="section-title">
      Economic Calendar
      <span class="section-sub">Next 14 days · high &amp; medium impact</span>
    </h2>
    <table class="cal-table">
      <thead>
        <tr>
          <th>Country</th><th>Date</th><th>Event</th><th>Impact</th>
          <th>Previous</th><th>Estimate</th><th>Actual</th>
        </tr>
      </thead>
      <tbody>{cal_html}</tbody>
    </table>
  </section>

  <!-- ── NEWS ── -->
  <section class="section">
    <h2 class="section-title">
      Market News
      <span class="section-sub">via Finnhub</span>
    </h2>
    <div class="news-grid">
      {news_html}
    </div>
  </section>

</main>

<footer class="footer">
  Data: Finnhub · Yahoo Finance &nbsp;·&nbsp;
  Generated {TIMESTAMP} &nbsp;·&nbsp;
  For personal research only — not financial advice
</footer>

</body>
</html>"""

print("  ✓ HTML built")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 6 — PUSH TO GITHUB PAGES
# ═════════════════════════════════════════════════════════════════════════════
print("STEP 6 — Pushing to GitHub")

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

def push_file(path, content, commit_msg):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    r   = requests.get(url, headers=HEADERS)
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {
        "message": commit_msg,
        "content": base64.b64encode(content.encode()).decode(),
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, json=payload, headers=HEADERS)
    return r.status_code in (200, 201), r.json().get("message", "")

ok, msg = push_file(
    "docs/dashboard.html",
    HTML,
    f"Dashboard update: {TODAY}"
)

if ok:
    print(f"\n✓ Pushed successfully")
    print(f"  Live at: https://{GITHUB_OWNER}.github.io/{GITHUB_REPO}/dashboard.html")
else:
    print(f"\n✗ Push failed: {msg}")
    raise RuntimeError("GitHub push failed")
