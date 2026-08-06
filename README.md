# SharpFlow — deployable site

One repo, one free GitHub Pages site, three pages:

| URL | What |
|---|---|
| `/` | The live dashboard (markets, top picks, edge, whale feed, charts, alerts) |
| `/guide.html` | User guide |
| `/record.html` | Public track record — auto-updated hourly by the signal logger |

The dashboard is pure client-side (every visitor's browser calls Polymarket/ESPN
directly — your site never proxies data, so it costs nothing and never rate-limits).
The logger runs on GitHub Actions and commits every signal to git, which is the
tamper-evident audit trail behind the track record.

## Deploy (15 minutes, $0)

1. **Create a public GitHub repo** — name it `sharpflow` (or anything).
2. **Upload everything in this folder** to the repo root. Keep the
   `.github/workflows/log.yml` path intact. (Easiest: repo → *Add file →
   Upload files* → drag the folder contents in, or `git init && git add -A &&
   git commit -m init && git push`.)
3. **Actions tab** → enable workflows if prompted. The logger now runs hourly
   (`:15` UTC) and can be triggered manually via *Run workflow*.
4. **Settings → Pages** → *Deploy from a branch* → branch `main`, folder
   `/docs` → Save.
5. Your site is live in ~2 minutes at `https://<username>.github.io/<repo>/`.

### Optional: custom domain (~$10/yr)

Buy a domain (Cloudflare Registrar / Namecheap / Porkbun), then:
- *Settings → Pages → Custom domain* → enter it → GitHub creates the check.
- At your DNS provider add a `CNAME` record pointing `www` (or the apex via
  `ALIAS`/`ANAME`) to `<username>.github.io`.
- Tick *Enforce HTTPS* once the cert issues (minutes to an hour).

### Alternative hosts

Cloudflare Pages or Netlify also serve the `docs/` folder free — but the
hourly logger commit + GitHub Pages redeploy loop is simplest kept on GitHub.

## Operating it

- **Edge threshold:** change `--min-edge 2` in `.github/workflows/log.yml`.
- **The record page is the product.** Link `record.html` in your X bio and in
  every post. Don't screenshot the dashboard's picks without the record link —
  unverifiable picks are what everyone else posts.
- **`LAUNCH.md`** has the launch thread, daily post templates, and channel list.
- Logger details, scoring rules, and honest limitations: see `LOGGER.md`.

Informational tool — not financial advice, and say so wherever you post it.
