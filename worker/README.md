# Logger Worker

Lets the dashboard write. The site is static HTML on GitHub Pages, so it cannot
save anything; this Worker accepts an entry from the page and appends it to the
matching `data/*.json` in the repo. The next rebuild renders it like any other
logged data.

```
phone  ──POST──▶  Worker  ──GitHub Contents API──▶  data/nutrition.json
                    │                                       │
              app token                              commit triggers
              (in browser)                           rebuild + deploy
                    │
              GitHub token
              (secret, server-side only)
```

## Why two tokens

The GitHub token can write to your repo, so it must never reach the browser. It
lives only as a Worker secret. The browser holds a separate **app token** whose
only power is "may call this Worker" — if it leaks, rotate `APP_TOKEN` and
nothing else is exposed.

Note the app token does sit in the browser's `localStorage`, which is fine for a
personal dashboard on your own devices but is not a login system. Anyone with
that token and the Worker URL can add entries to your training data.

## Deploy

You need a free Cloudflare account. Run these yourself — they involve your own
credentials.

1. Install the CLI and sign in:

```bash
npm install -g wrangler && wrangler login
```

2. Create a **fine-grained** GitHub personal access token at
   https://github.com/settings/personal-access-tokens/new
   - Repository access: **only** `garmin-dashboard`
   - Permissions: **Contents → Read and write** (nothing else)
   - Give it a short expiry and diarise the renewal

3. Make an app token — any long random string, e.g.

```bash
openssl rand -hex 24
```

4. From this `worker/` directory, set both secrets and deploy:

```bash
wrangler secret put GITHUB_TOKEN
```

```bash
wrangler secret put APP_TOKEN
```

```bash
wrangler deploy
```

5. Wrangler prints the Worker URL. On the dashboard, open **Settings** in the
   top bar, paste the URL and the app token, and save. They are stored on that
   device only, so repeat once per device.

## Check it works

```bash
curl -X POST "$WORKER_URL" -H "Authorization: Bearer $APP_TOKEN" -H 'Content-Type: application/json' -d '{"kind":"food","entry":{"date":"2026-08-14","meal":"snack","description":"test entry","calories":100}}'
```

A `200` with `{"ok":true,...}` means it committed. Delete the test entry from
`data/nutrition.json` afterwards.

## What it accepts

| kind | file | required | optional |
| --- | --- | --- | --- |
| `food` | `nutrition.json` | date, meal, description | calories, protein_g, carbs_g, fat_g, grams |
| `body` | `body_comp.json` | date | weight_kg, body_fat_pct, muscle_mass_kg, water_pct, visceral_fat, bmr |
| `training` | `trainings.json` | date, type | subtype, notes, duration_min, muscle_groups, exercises |
| `lifestyle` | `lifestyle.json` | date | alcohol_units, cannabis, cigarettes, notes |

Entries are rebuilt field by field from this schema rather than passed through,
so unknown fields are dropped, dates must be `YYYY-MM-DD`, numbers must be
non-negative, and muscle intensities must be 0–1. The Worker only ever appends
to these four files and cannot be pointed at any other path.
