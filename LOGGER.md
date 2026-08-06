# SharpFlow Edge Logger — public track record

Automatically logs every Polymarket sports edge signal (de-vigged sportsbook
odds vs. Polymarket ask), resolves each one against final Polymarket prices,
and publishes a running hit-rate / ROI page. The git commit history is the
audit trail: signals are timestamped by GitHub's servers when committed, so
the record can't be back-filled or cherry-picked after the fact.

## Setup (10 minutes, free)

1. **Create a new public GitHub repo** (public = the whole point; the record
   must be inspectable).
2. **Upload everything in this folder** to the repo root (keep the
   `.github/workflows/log.yml` path intact).
3. **Enable the schedule:** go to the repo's **Actions** tab and click
   "enable workflows" if prompted. The logger runs hourly at :15 UTC and can
   be run manually via *Actions → edge-logger → Run workflow*.
4. **Publish the page:** *Settings → Pages → Deploy from branch →*
   branch `main`, folder `/docs`. Your track record goes live at
   `https://<you>.github.io/<repo>/`.

That's it. No servers, no keys, no cost.

## What counts as a signal

- Polymarket sports market matched by team/player name to a pre-game
  sportsbook line (DraftKings via ESPN's public feed).
- Book moneyline → implied probability → de-vigged (both sides normalized to
  sum to 100%).
- Signal fires when `fair probability − Polymarket best ask ≥ 2¢`
  (change with `--min-edge` in `log.yml`).
- O/U markets only match when the book total and Polymarket line are
  identical. Asks below 3¢ / above 97¢ are skipped.
- **One signal per market+side, ever** — no re-firing to pad the count.

## Scoring

- Flat $100 stake per signal. WON pays `100 × (1 − ask) / ask`; LOST is −$100.
- Resolution comes from Polymarket's own final prices (outcome at 0.99+/0.01−
  on a closed market). Ambiguous resolutions stay OPEN for manual review.
- The page shows hit rate **next to break-even** (the average price paid).
  Hit rate above break-even = profitable; below = not. Both numbers stay up
  whether they're flattering or not.

## Honest limitations

- DraftKings is one book; a stale line can fire a false signal.
- "Fair" assumes the book is right — it often is, sometimes isn't.
- Fills at the logged ask are assumed; real fills on thin books can be worse.
- Expect the record to need **months and 100+ resolved signals** before the
  hit rate means anything. Small samples will swing hard both ways.

Informational only. Not financial advice.

## Files

| Path | What |
|---|---|
| `edge_logger.py` | The whole bot (stdlib Python, no dependencies) |
| `.github/workflows/log.yml` | Hourly schedule + auto-commit |
| `data/signals.jsonl` | Append-only signal log (one JSON per line) |
| `data/track_record.json` | Machine-readable summary |
| `docs/index.html` | The public track-record page (auto-generated) |

Test offline: `python edge_logger.py --fixtures tests/fixtures --dry-run`
