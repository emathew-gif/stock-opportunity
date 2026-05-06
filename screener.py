#!/usr/bin/env python3
"""
Stock Opportunity of the Week — Broad Market Screener v5
Standalone script for GitHub Actions weekly automation.
Converted from Google Colab v4.

Fixes vs v4:
  - net_margin (usually null) replaced with grossMarginTTM in quality score
  - Cell 10 mid-week refresh bug removed
  - Reads API keys from environment variables (GitHub Secrets)
  - Writes output to docs/index.html for GitHub Pages hosting
"""

import os, json, re, time
import pandas as pd
import numpy as np
import finnhub
import anthropic
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
FINNHUB_API_KEY   = os.environ["FINNHUB_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

HOLDINGS_FILE  = "holdings-daily-us-en-spy.xlsx"
HTML_TEMPLATE  = "stock_opportunity_widget_v2.html"
OUTPUT_HTML    = "docs/index.html"
TOP_N_HOLDINGS = 150
TOP_N_OUTPUT   = 10
API_SLEEP      = 0.5

TODAY      = datetime.today().strftime("%Y-%m-%d")
IN_45_DAYS = (datetime.today() + timedelta(days=45)).strftime("%Y-%m-%d")
WEEK_LABEL = f"Week of {datetime.today().strftime('%d %b %Y')}"

WEIGHTS = {
    "value":     0.20,
    "momentum":  0.20,
    "quality":   0.20,
    "sentiment": 0.20,
    "catalyst":  0.20,
}

SECTOR_MAP = {
    # Information Technology
    "NVDA":"Technology","AAPL":"Technology","MSFT":"Technology","AVGO":"Technology",
    "MU":"Technology","AMD":"Technology","LRCX":"Technology","CSCO":"Technology",
    "AMAT":"Technology","INTC":"Technology","PLTR":"Technology","ORCL":"Technology",
    "KLAC":"Technology","IBM":"Technology","TXN":"Technology","APH":"Technology",
    "ADI":"Technology","CRM":"Technology","ANET":"Technology","QCOM":"Technology",
    "GLW":"Technology","PANW":"Technology","ACN":"Technology","VRT":"Technology",
    "STX":"Technology","SNDK":"Technology","WDC":"Technology","INTU":"Technology",
    "ADBE":"Technology","CRWD":"Technology","NOW":"Technology","SNPS":"Technology",
    "APP":"Technology","PWR":"Technology",
    # Communication Services
    "GOOGL":"Comm Services","GOOG":"Comm Services","META":"Comm Services",
    "NFLX":"Comm Services","DIS":"Comm Services","VZ":"Comm Services",
    "T":"Comm Services","CMCSA":"Comm Services","TMUS":"Comm Services",
    "BKNG":"Comm Services","UBER":"Comm Services",
    # Consumer Discretionary
    "AMZN":"Cons Discretionary","TSLA":"Cons Discretionary","HD":"Cons Discretionary",
    "MCD":"Cons Discretionary","SBUX":"Cons Discretionary","LOW":"Cons Discretionary",
    "TJX":"Cons Discretionary","ORLY":"Cons Discretionary","MAR":"Cons Discretionary",
    "HLT":"Cons Discretionary",
    # Consumer Staples
    "WMT":"Cons Staples","COST":"Cons Staples","PG":"Cons Staples",
    "KO":"Cons Staples","PEP":"Cons Staples","PM":"Cons Staples",
    "MO":"Cons Staples","MDLZ":"Cons Staples",
    # Energy
    "XOM":"Energy","CVX":"Energy","COP":"Energy","SLB":"Energy","EOG":"Energy",
    "WMB":"Energy",
    # Financials
    "JPM":"Financials","V":"Financials","MA":"Financials","BAC":"Financials",
    "GS":"Financials","WFC":"Financials","MS":"Financials","AXP":"Financials",
    "SCHW":"Financials","BLK":"Financials","COF":"Financials","CB":"Financials",
    "PGR":"Financials","SPGI":"Financials","CME":"Financials","ICE":"Financials",
    "PNC":"Financials","USB":"Financials","BK":"Financials","BX":"Financials",
    # Healthcare
    "LLY":"Healthcare","JNJ":"Healthcare","UNH":"Healthcare","ABBV":"Healthcare",
    "MRK":"Healthcare","ABT":"Healthcare","AMGN":"Healthcare","TMO":"Healthcare",
    "GILD":"Healthcare","ISRG":"Healthcare","DHR":"Healthcare","SYK":"Healthcare",
    "BMY":"Healthcare","MDT":"Healthcare","VRTX":"Healthcare","BSX":"Healthcare",
    "PFE":"Healthcare","CVS":"Healthcare","MCK":"Healthcare","REGN":"Healthcare",
    "HCA":"Healthcare",
    # Industrials
    "CAT":"Industrials","GE":"Industrials","RTX":"Industrials","HON":"Industrials",
    "UNP":"Industrials","LMT":"Industrials","BA":"Industrials","DE":"Industrials",
    "ETN":"Industrials","PH":"Industrials","GD":"Industrials","CMI":"Industrials",
    "EMR":"Industrials","FDX":"Industrials","CSX":"Industrials","UPS":"Industrials",
    "ADP":"Industrials","GEV":"Industrials","HWM":"Industrials","TT":"Industrials",
    "JCI":"Industrials","WM":"Industrials","NOC":"Industrials","MMM":"Industrials",
    "CRH":"Industrials",
    # Materials
    "LIN":"Materials","NEM":"Materials","FCX":"Materials","SHW":"Materials",
    # Real Estate
    "WELL":"Real Estate","PLD":"Real Estate","EQIX":"Real Estate","AMT":"Real Estate",
    # Utilities
    "NEE":"Utilities","SO":"Utilities","DUK":"Utilities","CEG":"Utilities",
    "AEP":"Utilities",
}

# ── Clients ───────────────────────────────────────────────────────────────────
fh     = finnhub.Client(api_key=FINNHUB_API_KEY)
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Load SPY holdings
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1 — Loading SPY holdings")
print("=" * 60)

df_holdings = pd.read_excel(HOLDINGS_FILE, sheet_name="holdings", skiprows=4)
df_holdings = df_holdings[["Name", "Ticker", "Weight"]].dropna(subset=["Ticker"])
df_holdings = df_holdings[df_holdings["Ticker"].str.match(r"^[A-Z]{1,5}$")]
df_holdings = (df_holdings
               .sort_values("Weight", ascending=False)
               .head(TOP_N_HOLDINGS)
               .reset_index(drop=True))
df_holdings["spy_rank"] = df_holdings.index + 1
df_holdings["sector"]   = df_holdings["Ticker"].map(SECTOR_MAP).fillna("Other")

print(f"✓ {len(df_holdings)} holdings across {df_holdings['sector'].nunique()} sectors")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Fetch Finnhub data
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 2 — Fetching Finnhub data")
print("=" * 60)

def safe(fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        return result if result else None
    except Exception:
        return None

def fetch_ticker(ticker):
    return {
        "quote":    safe(fh.quote, ticker),
        "metrics":  safe(fh.company_basic_financials, ticker, "all"),
        "profile":  safe(fh.company_profile2, symbol=ticker),
        "rec":      safe(fh.recommendation_trends, ticker),
        "target":   safe(fh.price_target, ticker),
        "earnings": safe(fh.earnings_calendar, _from=TODAY, to=IN_45_DAYS, symbol=ticker),
    }

tickers = df_holdings["Ticker"].tolist()
print(f"Fetching {len(tickers)} tickers (~{len(tickers)*API_SLEEP/60:.1f} min)...\n")

raw    = {}
errors = []
for i, ticker in enumerate(tickers, 1):
    raw[ticker] = fetch_ticker(ticker)
    status = "✓" if raw[ticker]["quote"] else "⚠ no quote"
    print(f"  [{i:03d}/{len(tickers)}] {ticker:6s} {status}")
    if not raw[ticker]["quote"]:
        errors.append(ticker)
    time.sleep(API_SLEEP)

print(f"\n✓ {len(tickers)-len(errors)} ok  |  {len(errors)} errors: {errors}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Parse into DataFrame
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 3 — Parsing data")
print("=" * 60)

def get_metric(metrics_resp, key):
    try:
        return metrics_resp["metric"].get(key)
    except Exception:
        return None

def parse(ticker):
    d   = raw.get(ticker, {})
    q   = d.get("quote")    or {}
    m   = d.get("metrics")  or {}
    p   = d.get("profile")  or {}
    rec = d.get("rec")      or []
    tgt = d.get("target")   or {}
    ear = d.get("earnings") or {}

    price      = q.get("c")
    prev_close = q.get("pc")
    day_chg    = round((price - prev_close) / prev_close * 100, 2) if price and prev_close else None

    pe_ttm       = get_metric(m, "peBasicExclExtraTTM")
    pb           = get_metric(m, "pbAnnual")
    roe          = get_metric(m, "roeTTM")
    gross_margin = get_metric(m, "grossMarginTTM")   # replaces netMarginTTM (often null)
    rev_growth   = get_metric(m, "revenueGrowthTTMYoy")
    eps_growth   = get_metric(m, "epsGrowthTTMYoy")
    w52_high     = get_metric(m, "52WeekHigh")
    w52_low      = get_metric(m, "52WeekLow")

    w52_pos = None
    if w52_high and w52_low and price and w52_high != w52_low:
        w52_pos = (price - w52_low) / (w52_high - w52_low)

    mean_target = tgt.get("targetMean")
    upside_pct  = round((mean_target - price) / price * 100, 1) if mean_target and price else None

    sb = b = h = s = ss = 0
    if rec:
        r  = rec[0]
        sb = r.get("strongBuy",   0)
        b  = r.get("buy",         0)
        h  = r.get("hold",        0)
        s  = r.get("sell",        0)
        ss = r.get("strongSell",  0)

    total         = sb + b + h + s + ss
    analyst_score = (sb*1.0 + b*0.75 + h*0.5 + s*0.25 + ss*0.0) / total if total > 0 else None
    buy_ratio     = (sb + b) / total if total > 0 else None
    has_earnings  = bool(ear.get("earningsCalendar"))

    row    = df_holdings[df_holdings["Ticker"] == ticker]
    sector = row["sector"].values[0] if len(row) > 0 else "Other"

    return {
        "ticker": ticker, "name": p.get("name", ticker), "sector": sector,
        "price": price, "day_chg": day_chg,
        "pe_ttm": pe_ttm, "pb": pb, "roe": roe, "gross_margin": gross_margin,
        "rev_growth": rev_growth, "eps_growth": eps_growth,
        "w52_high": w52_high, "w52_low": w52_low, "w52_pos": w52_pos,
        "mean_target": mean_target, "upside_pct": upside_pct,
        "analyst_score": analyst_score, "buy_ratio": buy_ratio,
        "strong_buy": sb, "buy": b, "hold": h, "sell": s, "strong_sell": ss,
        "total_recs": total, "has_earnings": has_earnings,
    }

valid_tickers = [t for t in tickers if raw.get(t, {}).get("quote")]
df = pd.DataFrame([parse(t) for t in valid_tickers])
print(f"✓ Parsed {len(df)} stocks")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Score
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 4 — Scoring")
print("=" * 60)

def norm(series, invert=False):
    s       = pd.to_numeric(series, errors="coerce")
    mn, mx  = s.min(), s.max()
    if pd.isna(mn) or mn == mx:
        return pd.Series([0.5] * len(s), index=series.index)
    out = (s - mn) / (mx - mn)
    return (1 - out if invert else out).fillna(0.5)

# Value
df["pe_cap"]       = df["pe_ttm"].clip(upper=df["pe_ttm"].quantile(0.90))
df["pb_cap"]       = df["pb"].clip(upper=df["pb"].quantile(0.90))
df["score_value"]  = norm(df["pe_cap"], invert=True)*0.60 + norm(df["pb_cap"], invert=True)*0.40

# Momentum
df["mom_52w"]         = df["w52_pos"].apply(
    lambda x: (1 - abs(x - 0.45) / 0.55) if pd.notna(x) else 0.5).clip(0, 1)
df["score_momentum"]  = df["mom_52w"]*0.50 + norm(df["upside_pct"])*0.50

# Quality — grossMarginTTM instead of netMarginTTM (consistently populated)
df["score_quality"]   = (norm(df["roe"])*0.40 +
                         norm(df["gross_margin"])*0.35 +
                         norm(df["rev_growth"])*0.25)

# Sentiment
df["score_sentiment"] = norm(df["analyst_score"])*0.60 + norm(df["buy_ratio"])*0.40

# Catalyst
df["score_catalyst"]  = (df["has_earnings"].astype(float)*0.40 +
                         norm(df["eps_growth"])*0.60).clip(0, 1)

# Composite
df["score_composite"] = (
    df["score_value"]     * WEIGHTS["value"]     +
    df["score_momentum"]  * WEIGHTS["momentum"]  +
    df["score_quality"]   * WEIGHTS["quality"]   +
    df["score_sentiment"] * WEIGHTS["sentiment"] +
    df["score_catalyst"]  * WEIGHTS["catalyst"]
)

df = df.sort_values("score_composite", ascending=False).reset_index(drop=True)
df["rank"] = df.index + 1
print("✓ Scoring complete")
print(f"\nTop 10:")
cols = ["rank","ticker","sector","score_composite","score_value",
        "score_momentum","score_quality","score_sentiment","score_catalyst"]
print(df.head(10)[cols].round(3).to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Generate theses via Claude
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 5 — Generating investment theses")
print("=" * 60)

SYSTEM_PROMPT = """You are a senior equity analyst writing a concise weekly
stock opportunity brief for a retail investment newsletter. Be direct,
specific, and data-driven. Write in plain English — avoid jargon.
Do not use any markdown formatting, asterisks, or bold markers."""

def build_prompt(row):
    upside = f"{row['upside_pct']:.1f}%" if pd.notna(row['upside_pct']) else "N/A"
    w52    = f"{row['w52_pos']:.0%}"      if pd.notna(row['w52_pos'])    else "N/A"
    gm     = f"{row['gross_margin']:.1f}%" if pd.notna(row['gross_margin']) else "N/A"
    return f"""Stock: {row['ticker']} — {row['name']} ({row['sector']})
Price: ${row['price']:.2f}  |  P/E (TTM): {row['pe_ttm']}  |  P/B: {row['pb']}
ROE: {row['roe']}%  |  Gross margin: {gm}  |  Revenue growth YoY: {row['rev_growth']}%
EPS growth YoY: {row['eps_growth']}%
52-week position: {w52} of range  |  52w high: ${row['w52_high']}  |  52w low: ${row['w52_low']}
Analyst mean target: ${row['mean_target']}  |  Upside: {upside}
Analyst consensus: {row['strong_buy']} strong buy / {row['buy']} buy / {row['hold']} hold / {row['sell']} sell
Earnings in next 45 days: {'Yes' if row['has_earnings'] else 'No'}

Scores (0=worst, 1=best vs full S&P 500 universe):
  Value={row['score_value']:.2f}  Momentum={row['score_momentum']:.2f}  Quality={row['score_quality']:.2f}
  Sentiment={row['score_sentiment']:.2f}  Catalyst={row['score_catalyst']:.2f}
  Composite={row['score_composite']:.3f}

Write exactly 4 labelled sections. Plain English only — no jargon, no markdown.

THESIS: Why this stock stands out this week. 1-2 sentences.
BULL CASE: The single strongest reason it could do well. 1-2 sentences.
BEAR CASE: 2-3 sentences covering: (1) a company-specific risk such as
execution or earnings disappointment; (2) a valuation risk — the stock may
already price in good news; (3) a market risk such as rising interest rates
or economic slowdown. Analyst price targets are estimates and actual results
may differ materially.
RISK TAG: Pick exactly one: Speculative | Growth | Value | Quality | Turnaround"""

def generate_thesis(row):
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(row)}]
    )
    return msg.content[0].text.strip()

def parse_sections(raw_text):
    result = {"thesis": "", "bull": "", "bear": "", "risk_tag": ""}
    patterns = {
        "thesis":   r"THESIS:(.*?)(?=BULL CASE:|BEAR CASE:|RISK TAG:|$)",
        "bull":     r"BULL CASE:(.*?)(?=BEAR CASE:|RISK TAG:|$)",
        "bear":     r"BEAR CASE:(.*?)(?=RISK TAG:|$)",
        "risk_tag": r"RISK TAG:(.*?)$",
    }
    for key, pat in patterns.items():
        m = re.search(pat, raw_text, re.DOTALL | re.IGNORECASE)
        if m:
            result[key] = m.group(1).strip().replace("**", "").strip()
    return result

top_picks = df.head(TOP_N_OUTPUT).copy()

raw_theses = []
for _, row in top_picks.iterrows():
    print(f"  [{int(row['rank']):02d}] {row['ticker']:6s}...", end=" ", flush=True)
    raw_theses.append(generate_thesis(row))
    print("✓")
    time.sleep(0.3)

top_picks["thesis_raw"] = raw_theses
for key in ["thesis", "bull", "bear", "risk_tag"]:
    top_picks[key] = top_picks["thesis_raw"].apply(
        lambda r, k=key: parse_sections(r)[k])

print("✓ Theses generated")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Build output JSON
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 6 — Building output")
print("=" * 60)

def safe_float(v, dp=2):
    try:
        return round(float(v), dp)
    except Exception:
        return None

top_picks = top_picks.copy()
top_picks["is_featured"] = False
top_picks.iloc[0, top_picks.columns.get_loc("is_featured")] = True

output = {
    "generated_at": TODAY,
    "week_label":   WEEK_LABEL,
    "sector":       "Broad Market",
    "universe":     f"SPY Top {TOP_N_HOLDINGS}",
    "weights":      WEIGHTS,
    "picks":        [],
}

for _, row in top_picks.iterrows():
    output["picks"].append({
        "rank":            int(row["rank"]),
        "ticker":          row["ticker"],
        "name":            row["name"],
        "sector":          row["sector"],
        "is_featured":     bool(row["is_featured"]),
        "price":           safe_float(row["price"], 2),
        "day_chg":         safe_float(row["day_chg"], 2),
        "pe_ttm":          safe_float(row["pe_ttm"], 2),
        "pb":              safe_float(row["pb"], 2),
        "roe":             safe_float(row["roe"], 2),
        "net_margin":      safe_float(row["gross_margin"], 2),  # key kept for HTML compatibility
        "rev_growth":      safe_float(row["rev_growth"], 2),
        "w52_pos":         safe_float(row["w52_pos"], 3),
        "w52_high":        safe_float(row["w52_high"], 2),
        "w52_low":         safe_float(row["w52_low"], 2),
        "mean_target":     safe_float(row["mean_target"], 2),
        "upside_pct":      safe_float(row["upside_pct"], 1),
        "has_earnings":    bool(row["has_earnings"]),
        "risk_tag":        row["risk_tag"].replace("**", "").strip(),
        "thesis":          row["thesis"].replace("**", "").strip(),
        "bull_case":       row["bull"].replace("**", "").strip(),
        "bear_case":       row["bear"].replace("**", "").strip(),
        "score_composite": safe_float(row["score_composite"], 3),
        "scores": {
            "value":     safe_float(row["score_value"], 3),
            "momentum":  safe_float(row["score_momentum"], 3),
            "quality":   safe_float(row["score_quality"], 3),
            "sentiment": safe_float(row["score_sentiment"], 3),
            "catalyst":  safe_float(row["score_catalyst"], 3),
        },
        "analyst": {
            "strong_buy":  int(row["strong_buy"]),
            "buy":         int(row["buy"]),
            "hold":        int(row["hold"]),
            "sell":        int(row["sell"]),
            "strong_sell": int(row["strong_sell"]),
            "total":       int(row["total_recs"]),
        },
    })

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Bake into HTML and write output
# ─────────────────────────────────────────────────────────────────────────────
Path("docs").mkdir(exist_ok=True)

with open(HTML_TEMPLATE, "r") as f:
    html = f.read()

match = re.search(r'const DATA = \{.*?\};', html, re.DOTALL)
if not match:
    raise ValueError("Could not find DATA blob in HTML template — check template file")

html_updated = html[:match.start()] + f"const DATA = {json.dumps(output)};" + html[match.end():]

with open(OUTPUT_HTML, "w") as f:
    f.write(html_updated)

featured = top_picks.iloc[0]
print(f"✓ Written to {OUTPUT_HTML}")
print(f"\n  Week     : {WEEK_LABEL}")
print(f"  Featured : {featured['ticker']} — {featured['name']}")
print(f"  Picks    : {', '.join(top_picks['ticker'].tolist())}")
print(f"\nDone.")
