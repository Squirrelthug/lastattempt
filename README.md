# lastattempt.net

Static site for **Last Attempt** — the Warcraft media project around the Last Attempt Guildcast.
Python builds it; Cloudflare Pages hosts it. No CMS, no database.

## Layout

```
site.json                 names, URLs, socials, nav, contact emails, analytics token
build.py                  the whole build: fetch feed → render → dist/
content/articles/*.md     editorial articles (front matter + Markdown)
content/episodes/*.json   notes_NNN.json from the LAPod notes pipeline (drives episode pages)
content/pages/*.md        about, legal, ... (any file here becomes /<name>/)
content/cast.json         host, co-hosts, recurring guests
templates/                Jinja2 templates
static/                   copied as-is (css, img, _headers, _redirects, robots.txt)
data/feed.xml             cached podcast RSS — refreshed on every online build, committed so
                          offline builds and failed fetches still work
tools/import_notes.py     copy an episode's notes JSON in from G:\My Drive\LAVods
tools/make_brand_assets.py  regenerate logo-full / mark / favicons / og banner from the master
dist/                     build output (gitignored)
```

## Build locally

```
pip install -r requirements.txt
python build.py              # fetches the feed, falls back to data/feed.xml
python build.py --offline    # no network
python build.py --drafts     # include draft: true articles
```

Preview: `cd dist && python -m http.server 8471` → http://127.0.0.1:8471/

## Weekly routine

1. Record and publish the episode as usual (Spotify is the source of truth for audio).
2. `python tools/import_notes.py NNN` — pulls `notes_NNN.json` into `content/episodes/`.
3. Commit + push. Cloudflare builds and deploys. The feed is also re-fetched twice a day on a
   schedule, so an episode published to Spotify appears on the site without a commit.

## Writing an article

Create `content/articles/<slug>.md`:

```
---
title: What "Forever" Actually Means
date: 2026-09-22
author: Squirrelthug
summary: One-paragraph standfirst shown on cards, in the feed, and under the headline.
tags: WoW Forever, BlizzCon 2026
hero: /img/articles/forever-roadmap.jpg
hero_alt: The World of Warcraft: Forever roadmap slide
hero_credit: Image: Blizzard Entertainment, BlizzCon 2026 press kit
draft: false
---

Body in Markdown. House-style call-outs (rendered as coloured boxes):

!!! know "What Blizzard confirmed"
    Facts from the presentation, patch notes, or press kit.

!!! think "What we think"
    Our reaction and reasoning.

!!! community "What the community is saying"
    Reactions and discoveries from Discords, forums, creators.

!!! open "What nobody knows yet"
    Questions only live players can answer — and who is likely to answer them.
```

Article images go in `static/img/articles/`. **Every Blizzard asset gets a credit line** (in
`hero_credit` or a figure caption). Only use official press-kit material or our own livestream
screenshots; never another site's captures.

## Deploying

The site is a Cloudflare **Worker with static assets**, built from this repo by Cloudflare's Git
integration (project `lastattempt`, account Squirrelthug). Every push to `main` triggers a build:

- Build command: `pip install -r requirements.txt && python build.py`
- Deploy command: `npx wrangler deploy` (reads `wrangler.jsonc`, which serves `dist/`)
- Build variable: `PYTHON_VERSION=3.12`
- Domains: `lastattempt.net`, `www.lastattempt.net` (Worker → Domains tab)
- Fallback URL: https://lastattempt.squirrelthug.workers.dev

No API tokens live in GitHub. `.github/workflows/deploy.yml` only runs on a schedule (twice a day):
it rebuilds, and if the cached podcast feed or Raider.IO data changed it commits `data/`, which in
turn triggers a Cloudflare build. `gh workflow run deploy.yml` forces a refresh.

Build logs: Cloudflare dashboard → Workers & Pages → lastattempt → Deployments.

## Site config to fill in

In `site.json`: social URLs (blank entries are hidden), and `analytics_token` from
Cloudflare → Web Analytics → add site → copy the token from the snippet. Contact addresses are
`hello@` and `press@` — set up **Cloudflare Email Routing** on the zone to forward them to Gmail.
