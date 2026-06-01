# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A daily job search script that queries multiple public job board APIs, filters results for mid-level marketing roles, and emails a digest to `shannawallace123@gmail.com` via Resend. Runs automatically every day at 9am ET via GitHub Actions.

## Running it

```bash
# Force a run (clears the daily lock first)
rm -f .last_run && /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 job_search.py
```

The script self-locks via `.last_run` (date string). Delete it to force a re-run locally. GitHub Actions deletes it automatically before each run.

## Email delivery

- **Local:** Resend API key is stored in macOS Keychain (`security find-generic-password -s resend-api -a job_search -w`). No env var needed.
- **GitHub Actions:** `RESEND_API_KEY` secret on the repo. From address: `jobs@shantheleo.com`. To: `shannawallace123@gmail.com`.

## Dedup logic

`sent_jobs.json` tracks every link ever sent — no expiry, jobs are never repeated. To reset (intentionally re-send old jobs), clear the file: `echo '{}' > sent_jobs.json` and commit it.

## Job sources

All three sources hit **public APIs with no auth** and link directly to company career pages:

| Source | API pattern | Notes |
|--------|-------------|-------|
| RemoteOK | `remoteok.com/api?tag={tag}` | Searches 6 marketing tags |
| Remotive | `remotive.com/api/remote-jobs?category={category}` | Searches marketing + copywriting |
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{slug}/jobs` | ~50 named companies |

Lever and other ATS platforms were tested and found to return 404s or empty results for the target companies — don't re-add without testing slugs first.

## Filter logic

Jobs pass through several sequential filters:

1. **Title level** — must match `INCLUDE_LEVEL_KW` (specialist, manager, coordinator, lead, etc.) and not match `EXCLUDE_LEVEL_KW` (director, VP, intern, etc.)
2. **Title category** — must match `INCLUDE_TITLE_KW` (marketing, social media, content, brand, etc.)
3. **Tech exclusion** — `EXCLUDE_TECH_KW` blocks engineering/data roles that share level keywords
4. **Agency exclusion** — `BLOCKED_AGENCIES` blocks ad/PR agencies; corporate-side only
5. **Location** — `is_us_compatible()` allowlist; `has_remote_or_hybrid_signal()` for Greenhouse (stricter — city-only locations rejected)
6. **Salary** — if listed, must be ≥ $100k; unlisted salaries pass through
7. **Description** — `NON_US_DESC_SIGNALS` catches jobs hiding UK/Canada restrictions

## Adding new Greenhouse companies

Test the slug before adding:
```bash
curl -s "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs" | python3 -m json.tool | head -20
```
A 200 with a non-empty `jobs` array means the slug works. Add to `GREENHOUSE_COMPANIES` dict in `job_search.py`.

## Deployment

Push to `main` on `shantheleo/job-search` (GitHub). The Actions workflow runs automatically. `sent_jobs.json` is committed back after each run to persist dedup history.
