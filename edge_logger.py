#!/usr/bin/env python3
"""
SharpFlow edge logger — public track record for Polymarket sports edge signals.

Every run:
  1. Pulls active Polymarket sports markets (Gamma API) and pre-game sportsbook
     moneylines (ESPN/DraftKings free feed).
  2. De-vigs the book odds into fair probabilities, compares to Polymarket asks,
     and appends any new signal with edge >= --min-edge to data/signals.jsonl.
  3. Re-checks previously logged signals whose games have ended and marks them
     WON / LOST from final Polymarket resolution prices.
  4. Renders docs/index.html — the public track-record page (stats + full log).

Run it from GitHub Actions on a schedule and commit data/ + docs/ each run:
the git history is the tamper-evident audit trail.

Stdlib only. No keys, no auth.
"""
import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = timezone(timedelta(hours=-5))

GAMMA = "https://gamma-api.polymarket.com"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
LEAGUES = ["baseball/mlb", "basketball/nba", "basketball/wnba",
           "football/nfl", "hockey/nhl"]
ROOT = Path(__file__).resolve().parent
SIGNALS = ROOT / "data" / "signals.jsonl"
SUMMARY = ROOT / "data" / "track_record.json"
PAGE = ROOT / "docs" / "record.html"

FIXTURES = None  # set by --fixtures for offline testing


# ---------------------------------------------------------------- fetch layer
def http_json(url, timeout=20):
    if FIXTURES is not None:
        return _fixture_for(url)
    req = urllib.request.Request(url, headers={"User-Agent": "sharpflow-edge-log/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _fixture_for(url):
    if "gamma-api" in url and "/events" in url:
        p = FIXTURES / "gamma_events.json"
    elif "gamma-api" in url and "/markets" in url:
        p = FIXTURES / "gamma_markets.json"
    elif "espn.com" in url:
        p = FIXTURES / "espn.json"
    else:
        raise ValueError(f"no fixture for {url}")
    return json.loads(p.read_text()) if p.exists() else []


# ------------------------------------------------------------------ odds math
def am_prob(ml):
    """American moneyline -> implied probability (with vig)."""
    try:
        ml = float(ml)
    except (TypeError, ValueError):
        return None
    if ml == 0:
        return None
    return (-ml / (-ml + 100)) if ml < 0 else (100 / (ml + 100))


def devig(pa, pb):
    s = (pa or 0) + (pb or 0)
    if not pa or not pb or s <= 0:
        return None
    return pa / s, pb / s


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def name_eq(a, b):
    a, b = norm(a), norm(b)
    return a == b or (len(a) > 3 and len(b) > 3 and (a in b or b in a))


# ------------------------------------------------------------------- markets
def fetch_markets():
    evs = http_json(f"{GAMMA}/events?tag_slug=sports&active=true&closed=false"
                    f"&order=volume24hr&ascending=false&limit=60")
    rows = []
    for ev in evs or []:
        for m in ev.get("markets", []):
            if m.get("enableOrderBook") is False:
                continue
            try:
                out = json.loads(m.get("outcomes") or "[]")
                tok = json.loads(m.get("clobTokenIds") or "[]")
            except (json.JSONDecodeError, TypeError):
                continue
            if len(out) < 2 or len(tok) < 2:
                continue
            rows.append({
                "q": m.get("question"), "cid": m.get("conditionId"),
                "ev_title": ev.get("title"), "slug": ev.get("slug"),
                "out": out, "tok": tok,
                "bb": m.get("bestBid"), "ba": m.get("bestAsk"),
                "sp": m.get("spread"), "end": m.get("endDate"),
            })
    return rows


def fetch_book_games():
    games = []
    today = datetime.now(ET)
    for lg in LEAGUES:
        for d in (today, today + timedelta(days=1)):
            url = f"{ESPN}/{lg}/scoreboard?dates={d:%Y%m%d}&limit=40"
            try:
                j = http_json(url, timeout=12)
            except Exception:
                continue
            for ev in (j or {}).get("events", []):
                comps = ev.get("competitions") or []
                if not comps:
                    continue
                c = comps[0]
                state = (((c.get("status") or {}).get("type")) or {}).get("state")
                if state and state != "pre":
                    continue
                home = away = None
                for t in c.get("competitors", []):
                    name = (t.get("team") or {}).get("displayName")
                    if t.get("homeAway") == "home":
                        home = name
                    elif t.get("homeAway") == "away":
                        away = name
                odds = (c.get("odds") or [])
                if not (home and away and odds):
                    continue
                o = odds[0]
                ml_away = (o.get("awayTeamOdds") or {}).get("moneyLine")
                ml_home = (o.get("homeTeamOdds") or {}).get("moneyLine")
                games.append({
                    "away": away, "home": home,
                    "ml_away": ml_away, "ml_home": ml_home,
                    "ou": o.get("overUnder"),
                    "over_odds": o.get("overOdds"), "under_odds": o.get("underOdds"),
                    "provider": (o.get("provider") or {}).get("name") or "book",
                    "start": ev.get("date"),
                })
        if FIXTURES is not None:
            break  # one league is enough in fixture mode
    return games


# -------------------------------------------------------------- edge signals
def compute_edges(markets, games, min_edge):
    found = []
    for m in markets:
        ask = [m.get("ba"), (1 - m["bb"]) if m.get("bb") is not None else None]
        if ask[0] is None and ask[1] is None:
            continue
        ou = re.search(r"O/U (\d+(?:\.\d+)?)", m["q"] or "")
        if ou:
            parts = re.split(r" vs\.? ", m.get("ev_title") or "", flags=re.I)
            if len(parts) < 2:
                continue
            ta, tb = re.sub(r"^.*: ", "", parts[0]), parts[1]
        else:
            ta, tb = m["out"][0], m["out"][1]
        g = next((g for g in games
                  if (name_eq(g["away"], ta) and name_eq(g["home"], tb))
                  or (name_eq(g["away"], tb) and name_eq(g["home"], ta))), None)
        if not g:
            continue
        if ou:
            if g.get("ou") is None or float(ou.group(1)) != float(g["ou"]):
                continue
            dv = devig(am_prob(g.get("over_odds")), am_prob(g.get("under_odds")))
            if not dv:
                continue
            fair = list(dv)                     # [Over, Under]
        else:
            dv = devig(am_prob(g.get("ml_away")), am_prob(g.get("ml_home")))
            if not dv:
                continue
            away_is_0 = name_eq(g["away"], m["out"][0])
            fair = [dv[0], dv[1]] if away_is_0 else [dv[1], dv[0]]
        for i in (0, 1):
            a = ask[i]
            if a is None or a <= 0.03 or a >= 0.97:   # skip near-resolved/junk
                continue
            edge = fair[i] - a
            if edge >= min_edge:
                found.append({
                    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "market": m["q"], "cid": m["cid"], "side": m["out"][i],
                    "side_idx": i, "ask": round(a, 4),
                    "fair": round(fair[i], 4), "edge": round(edge, 4),
                    "source": g["provider"], "game_start": g.get("start"),
                    "market_end": m.get("end"), "spread": m.get("sp"),
                    "status": "OPEN", "result": None, "profit_100": None,
                })
    return found


def load_signals():
    if not SIGNALS.exists():
        return []
    return [json.loads(line) for line in SIGNALS.read_text().splitlines() if line.strip()]


def save_signals(signals):
    SIGNALS.parent.mkdir(parents=True, exist_ok=True)
    SIGNALS.write_text("\n".join(json.dumps(s) for s in signals) + ("\n" if signals else ""))


def append_new(signals, found):
    open_keys = {f"{s['cid']}|{s['side_idx']}" for s in signals if s["status"] == "OPEN"}
    done_keys = {f"{s['cid']}|{s['side_idx']}" for s in signals if s["status"] != "OPEN"}
    added = 0
    for f in found:
        k = f"{f['cid']}|{f['side_idx']}"
        if k in open_keys or k in done_keys:   # one signal per market+side, ever
            continue
        signals.append(f)
        open_keys.add(k)
        added += 1
    return added


# -------------------------------------------------------------- resolution
def resolve_signals(signals):
    """Mark OPEN signals WON/LOST from final Polymarket prices."""
    open_sigs = [s for s in signals if s["status"] == "OPEN"]
    if not open_sigs:
        return 0
    resolved = 0
    cids = sorted({s["cid"] for s in open_sigs})
    for i in range(0, len(cids), 10):
        chunk = cids[i:i + 10]
        qs = "&".join(f"condition_ids={c}" for c in chunk)
        try:
            markets = http_json(f"{GAMMA}/markets?{qs}&limit={len(chunk)}")
        except Exception:
            continue
        by_cid = {m.get("conditionId"): m for m in markets or []}
        for s in open_sigs:
            m = by_cid.get(s["cid"])
            if not m:
                continue
            try:
                px = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if len(px) < 2 or not m.get("closed"):
                continue
            p = px[s["side_idx"]]
            if p >= 0.99:
                s["status"] = "RESOLVED"
                s["result"] = "WON"
                s["profit_100"] = round(100 * (1 - s["ask"]) / s["ask"], 2)
                resolved += 1
            elif p <= 0.01:
                s["status"] = "RESOLVED"
                s["result"] = "LOST"
                s["profit_100"] = -100.0
                resolved += 1
            # anything else (e.g. weird resolution) stays OPEN for manual review
    return resolved


# ------------------------------------------------------------------ reporting
def summarize(signals):
    done = [s for s in signals if s["status"] == "RESOLVED"]
    wins = [s for s in done if s["result"] == "WON"]
    staked = 100 * len(done)
    profit = round(sum(s["profit_100"] or 0 for s in done), 2)
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signals_total": len(signals),
        "open": sum(1 for s in signals if s["status"] == "OPEN"),
        "resolved": len(done),
        "wins": len(wins),
        "losses": len(done) - len(wins),
        "hit_rate": round(len(wins) / len(done), 4) if done else None,
        "avg_ask": round(sum(s["ask"] for s in done) / len(done), 4) if done else None,
        "avg_edge_cents": round(100 * sum(s["edge"] for s in signals) / len(signals), 2) if signals else None,
        "flat_stake_roi": round(profit / staked, 4) if staked else None,
        "profit_per_100_flat": profit,
    }


def render_page(signals, summary):
    def pct(x, dash="—"):
        return f"{x * 100:.1f}%" if x is not None else dash

    rows = []
    for s in sorted(signals, key=lambda x: x["ts"], reverse=True)[:400]:
        if s["status"] == "RESOLVED":
            cls = "won" if s["result"] == "WON" else "lost"
            res = s["result"]
            pl = f"{'+' if (s['profit_100'] or 0) >= 0 else '−'}${abs(s['profit_100'] or 0):.0f}"
        else:
            cls, res, pl = "open", "OPEN", "—"
        rows.append(
            f"<tr><td class='num'>{s['ts'][:16].replace('T', ' ')}</td>"
            f"<td><b>{s['side']}</b><div class='sub'>{s['market']}</div></td>"
            f"<td class='num'>{s['ask'] * 100:.1f}¢</td>"
            f"<td class='num'>{s['fair'] * 100:.1f}¢</td>"
            f"<td class='num pos'>+{s['edge'] * 100:.1f}¢</td>"
            f"<td>{s['source']}</td>"
            f"<td class='{cls}'>{res}</td>"
            f"<td class='num {cls}'>{pl}</td></tr>")

    hit = pct(summary["hit_rate"])
    be = pct(summary["avg_ask"], dash="—")  # break-even hit rate = avg price paid
    roi = pct(summary["flat_stake_roi"]) if summary["flat_stake_roi"] is not None else "—"
    roi_cls = "won" if (summary["flat_stake_roi"] or 0) > 0 else ("lost" if (summary["flat_stake_roi"] or 0) < 0 else "")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SharpFlow — Public Track Record</title>
<style>
:root{{color-scheme:dark}}
body{{background:#0d0d0d;color:#c3c2b7;font:14px/1.5 system-ui,sans-serif;max-width:1000px;margin:0 auto;padding:30px 18px}}
h1{{color:#fff;font-size:22px}} h1 span{{color:#3987e5}}
.lede{{color:#898781;margin:4px 0 20px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:22px}}
.tile{{background:#1a1a19;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:12px 14px}}
.tile .k{{font-size:11px;color:#898781;text-transform:uppercase;letter-spacing:.05em}}
.tile .v{{font-size:22px;font-weight:700;color:#fff;margin-top:2px}}
table{{width:100%;border-collapse:collapse;background:#1a1a19;border:1px solid rgba(255,255,255,.1);border-radius:8px;overflow:hidden}}
th{{font-size:11px;color:#898781;text-transform:uppercase;text-align:left;padding:8px 10px;border-bottom:1px solid #383835}}
td{{padding:8px 10px;border-bottom:1px solid #2c2c2a;font-size:13px}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.sub{{font-size:11.5px;color:#898781}}
.won{{color:#0ca30c;font-weight:600}} .lost{{color:#d03b3b;font-weight:600}} .open{{color:#fab219}} .pos{{color:#0ca30c}}
footer{{color:#898781;font-size:11.5px;margin-top:20px;line-height:1.6}}
</style></head><body>
<h1>Sharp<span>Flow</span> — Public Track Record</h1>
<p class="lede"><a href="index.html" style="color:#3987e5;text-decoration:none">← back to the dashboard</a> ·
every edge signal this bot has ever fired, logged automatically and resolved against final Polymarket prices.
Log lives in git — history is the audit trail. Updated {summary["generated"][:16].replace("T", " ")} UTC.</p>
<div class="tiles">
<div class="tile"><div class="k">Signals</div><div class="v">{summary["signals_total"]}</div></div>
<div class="tile"><div class="k">Resolved</div><div class="v">{summary["resolved"]}</div></div>
<div class="tile"><div class="k">Record</div><div class="v">{summary["wins"]}–{summary["losses"]}</div></div>
<div class="tile"><div class="k">Hit rate</div><div class="v">{hit}</div></div>
<div class="tile"><div class="k">Break-even</div><div class="v">{be}</div></div>
<div class="tile"><div class="k">Flat-stake ROI</div><div class="v {roi_cls}">{roi}</div></div>
</div>
{"<table><thead><tr><th>Logged (UTC)</th><th>Signal</th><th>Ask</th><th>Fair</th><th>Edge</th><th>Source</th><th>Result</th><th>P/L per $100</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>" if rows else "<p style='background:#1a1a19;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:22px;text-align:center;color:#898781'>No signals logged yet. The bot only fires when Polymarket prices diverge from de-vigged sportsbook odds — that's rare by design.</p>"}
<footer>Method: DraftKings moneylines (ESPN public feed) → implied probability → de-vig → compare to Polymarket best ask.
A signal is logged once per market+side when edge ≥ threshold; it is scored WON/LOST from Polymarket's final resolution prices, flat $100 stakes, no compounding, no cherry-picking, losses included.
Hit rate must beat the break-even column (average price paid) for the strategy to be profitable.
Informational only — not financial advice.</footer>
</body></html>"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(html)


# ----------------------------------------------------------------------- main
def main():
    global FIXTURES
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-edge", type=float, default=2.0, help="minimum edge in cents")
    ap.add_argument("--fixtures", type=Path, default=None, help="offline test fixtures dir")
    ap.add_argument("--dry-run", action="store_true", help="compute but do not write")
    args = ap.parse_args()
    FIXTURES = args.fixtures

    signals = load_signals()
    n_resolved = resolve_signals(signals)

    try:
        markets = fetch_markets()
    except Exception as e:
        print(f"WARN: gamma fetch failed ({e}); logging skipped this run", file=sys.stderr)
        markets = []
    games = fetch_book_games()
    found = compute_edges(markets, games, args.min_edge / 100.0)
    n_new = append_new(signals, found)

    summary = summarize(signals)
    if not args.dry_run:
        save_signals(signals)
        SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY.write_text(json.dumps(summary, indent=2))
        render_page(signals, summary)

    print(f"markets={len(markets)} book_games={len(games)} "
          f"new_signals={n_new} resolved_now={n_resolved} "
          f"total={summary['signals_total']} record={summary['wins']}-{summary['losses']} "
          f"hit={summary['hit_rate']} roi={summary['flat_stake_roi']}")


if __name__ == "__main__":
    main()
