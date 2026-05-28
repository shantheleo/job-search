#!/usr/bin/env python3
"""
Daily Job Search — Shan The Leo
Pulls mid-level marketing roles from RemoteOK + Jobicy, emails a curated digest.
"""

import html
import json
import os
import smtplib
import subprocess
import sys
import time as time_mod
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import requests

# ── CONFIG ────────────────────────────────────────────────────────────────────
GMAIL_SENDER = "shannawallace123@gmail.com"
TO_EMAIL     = "shannawallace123@gmail.com"
# ──────────────────────────────────────────────────────────────────────────────

INCLUDE_TITLE_KW = [
    "experiential", "sponsorship", "social media", "content", "brand",
    "partnership", "marketing", "community", "influencer", "campaign",
    "creative", "communications", "pr ", "public relations",
]
INCLUDE_LEVEL_KW = [
    "specialist", "manager", "coordinator", "lead", "strategist",
    "copywriter", "content writer", "content creator",
]
EXCLUDE_LEVEL_KW = [
    "director", "vp ", "vice president", "chief", "intern",
    "junior", "entry level", "assistant", "svp", "c-suite", "head of",
]
# Clearly non-marketing roles that share level keywords (engineer, data scientist, etc.)
EXCLUDE_TECH_KW = [
    "engineering manager",
    "technical program manager",
    "data science manager",
    "data engineer",
    "software engineer",
    "machine learning",
    "backend engineer",
    "frontend engineer",
    "devops",
    "security engineer",
    "infrastructure engineer",
    "sourcing manager",
    "sourcing, manager",
    "solutions engineer",
    "cloud engineer",
]
FOOD_KW = [
    "food", "bev", "beverage", "restaurant", "dining", "culinary",
    "fmcg", "cpg", "snack", "drink", "grocery", "hospitality",
    "spirits", "wine", "beer", "coffee", "farm", "flavor",
]

LOCK_FILE = Path(__file__).parent / ".last_run"
SENT_FILE = Path(__file__).parent / "sent_jobs.json"
HEADERS   = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# Companies confirmed non-US that evade location filters — add here as discovered
BLOCKED_COMPANIES = {
    "giddyup",   # UK-based despite "Remote" location
    "onelocal",  # Canadian
    "keywords studios",  # Irish/UK
    "vn+",       # Barbados
}

# Household names / Fortune 500 / well-known brands — matched case-insensitively
KNOWN_COMPANIES = {
    # Food & Beverage
    "coca-cola", "pepsi", "pepsico", "nestle", "unilever", "kraft", "heinz",
    "kraft heinz", "general mills", "kellogg", "mars", "mondelez", "hershey",
    "campbell", "conagra", "tyson", "dannon", "danone", "red bull", "monster",
    "anheuser-busch", "ab inbev", "molson coors", "diageo", "bacardi",
    "brown-forman", "constellation brands", "modelo", "corona", "heineken",
    "starbucks", "dunkin", "mcdonald", "chipotle", "shake shack", "sweetgreen",
    "whole foods", "trader joe", "kroger", "target", "walmart", "costco",
    "chobani", "oatly", "beyond meat", "impossible foods",
    # Tech / Media
    "google", "meta", "amazon", "apple", "microsoft", "netflix", "spotify",
    "hulu", "disney", "warner", "nbcuniversal", "comcast", "viacom",
    "conde nast", "hearst", "buzzfeed", "vox media", "new york times",
    "washington post", "time", "forbes", "bloomberg", "hubspot", "salesforce",
    "adobe", "slack", "twilio", "shopify", "squarespace", "wix", "mailchimp",
    "hootsuite", "sprout social", "later", "buffer", "canva", "dropbox",
    "airbnb", "uber", "lyft", "doordash", "instacart", "grubhub",
    # Retail / Fashion / Consumer
    "nike", "adidas", "lululemon", "under armour", "gap", "h&m", "zara",
    "nordstrom", "macy", "sephora", "ulta", "glossier", "fenty",
    "procter & gamble", "p&g", "colgate", "johnson & johnson", "l'oreal",
    "estee lauder", "revlon", "coty",
    # Hospitality / Travel
    "marriott", "hilton", "hyatt", "intercontinental", "ihg", "airbnb",
    "expedia", "booking.com", "tripadvisor", "delta", "united", "american airlines",
    "southwest", "royal caribbean", "carnival",
    # Agencies / Marketing
    "edelman", "weber shandwick", "ogilvy", "wpp", "publicis", "ipg",
    "omnicom", "dentsu", "grey", "bbdo", "ddb", "mccann", "leo burnett",
    "havas", "droga5", "r/ga", "huge", "razorfish",
    # Sports / Events
    "nba", "nfl", "mlb", "nhl", "espn", "live nation", "ticketmaster",
    "anschutz", "aeg", "wmg", "iheartmedia", "pandora", "sirius",
    # Other well-known
    "red cross", "ymca", "national geographic", "discovery", "viacomcbs",
    "iherb", "brandwatch", "pinterest", "linkedin", "twitter", "tiktok",
    "snapchat", "reddit", "tumblr", "ge ", "general electric", "3m",
    "american express", "visa", "mastercard", "paypal", "stripe",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def already_ran_today():
    if not LOCK_FILE.exists():
        return False
    return LOCK_FILE.read_text().strip() == datetime.now().strftime("%Y-%m-%d")

def mark_ran():
    LOCK_FILE.write_text(datetime.now().strftime("%Y-%m-%d"))

def load_sent():
    if not SENT_FILE.exists():
        return {}
    try:
        return json.loads(SENT_FILE.read_text())
    except Exception:
        return {}

def save_sent(sent):
    SENT_FILE.write_text(json.dumps(sent))

ONSITE_SIGNALS = [
    "on-site", "onsite", "on site", "in-office", "in office",
    "in person", "in-person", "office only", "must be local",
    "must relocate", "no remote", "not remote",
]

# Signals that reveal a job is actually UK/non-US despite saying "Remote"
NON_US_DESC_SIGNALS = [
    "£", "gbp", "€", "cad", "aud",
    "based in the uk", "based in uk", "uk based", "uk resident",
    "right to work in the uk", "must be based in the uk",
    "london", "manchester", "edinburgh", "birmingham",
    "based in canada", "canadian", "right to work in canada",
    "toronto", "vancouver", "montreal",
    "based in ireland", "dublin", "irish",
    "based in australia", "sydney", "melbourne",
]

def is_remote_or_hybrid(location, tags=None, description=""):
    """Reject jobs explicitly requiring full in-office attendance."""
    combined = (location + " " + (description or "")).lower()
    if tags:
        combined += " " + " ".join(tags).lower()
    return not any(sig in combined for sig in ONSITE_SIGNALS)

def has_remote_or_hybrid_signal(location):
    """Stricter check for sources that list all jobs (remote AND on-site).
    Requires an explicit remote/hybrid keyword — city-only strings like
    'New York City, NY' are rejected since they're likely in-office."""
    loc = (location or "").lower().strip()
    if not loc:
        return True  # no restriction listed = open/remote
    if "remote" in loc or "hybrid" in loc:
        return True
    if any(kw in loc for kw in EXPLICIT_US):
        return True  # e.g. "USA", "United States" — location-agnostic
    if any(kw in loc for kw in WORLDWIDE):
        return True
    return False

def description_is_us_compatible(description):
    """Catch jobs hiding non-US restrictions in the description."""
    if not description:
        return True
    d = description.lower()
    return not any(sig in d for sig in NON_US_DESC_SIGNALS)

def work_arrangement(location):
    """Return a display label for the work arrangement."""
    loc = (location or "").lower()
    if "hybrid" in loc:
        return "Hybrid"
    if any(k in loc for k in EXPLICIT_US):
        return "Remote (US)"
    if "remote" in loc:
        return "Remote"
    if not loc:
        return "Remote"
    return location

def is_relevant_title(title):
    t = title.lower()
    if any(kw in t for kw in EXCLUDE_TECH_KW):
        return False
    if not any(kw in t for kw in INCLUDE_LEVEL_KW):
        return False
    if any(kw in t for kw in EXCLUDE_LEVEL_KW):
        return False
    return True

def is_marketing_title(title):
    return any(kw in title.lower() for kw in INCLUDE_TITLE_KW)

def is_food_adjacent(title, company):
    return any(kw in (title + " " + company).lower() for kw in FOOD_KW)

def is_known_company(company):
    c = company.lower()
    return any(known in c for known in KNOWN_COMPANIES)

def is_blocked_company(company):
    c = company.lower()
    return any(blocked in c for blocked in BLOCKED_COMPANIES)

EXPLICIT_US = [
    "usa", "united states", "us only", "u.s.", "remote, us", "us remote",
    "remote usa", "north america", "america",
]
WORLDWIDE = ["worldwide", "anywhere", "global", "any country", "international"]
BARE_REMOTE = {"remote", "remote only", "remote work", "fully remote", "100% remote"}

# Major US cities / state names that appear in location strings
US_GEO = [
    "new york", "los angeles", "chicago", "houston", "phoenix", "philadelphia",
    "san antonio", "san diego", "dallas", "san jose", "austin", "jacksonville",
    "san francisco", "columbus", "indianapolis", "seattle", "denver", "boston",
    "nashville", "portland", "las vegas", "memphis", "atlanta", "miami",
    "minneapolis", "new orleans", "cleveland", "pittsburgh", "raleigh",
    "st. louis", "tampa", "cincinnati", "kansas city", "sacramento",
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas",
    "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming", " dc", "washington dc",
]

def is_us_compatible(location):
    """Allowlist approach — only pass explicitly US, worldwide, or empty locations."""
    if not location or not location.strip():
        return True  # no restriction
    loc = location.lower().strip()
    if any(kw in loc for kw in EXPLICIT_US):
        return True
    if any(kw in loc for kw in WORLDWIDE):
        return True
    if loc in BARE_REMOTE:
        return True  # ambiguous — description check will catch non-US
    if any(kw in loc for kw in US_GEO):
        return True
    return False  # specific foreign or unrecognized location — reject

def salary_ok(salary_min, salary_max):
    """Return True if salary is >=100k, or not listed (0 / None = no data)."""
    lo = float(salary_min or 0)
    hi = float(salary_max or 0)
    if lo == 0 and hi == 0:
        return True  # no salary listed — don't exclude
    cap = hi if hi > 0 else lo
    return cap >= 100_000

def is_ascii(text):
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False

def epoch_within_days(epoch, days=7):
    if not epoch:
        return True
    return (time_mod.time() - float(epoch)) <= days * 86400

def iso_within_days(iso_str, days=7):
    if not iso_str:
        return True
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (datetime.now(dt.tzinfo) - dt).days <= days
    except Exception:
        return True


# ── Sources ───────────────────────────────────────────────────────────────────

REMOTEOK_TAGS = ["marketing", "content", "brand", "digital", "strategy", "copywriting"]

# Public Greenhouse job boards — no API key required; 404 slugs are skipped silently
GREENHOUSE_COMPANIES = {
    # Tech / Media / Marketing
    "spotify":           "Spotify",
    "airbnb":            "Airbnb",
    "doordash":          "DoorDash",
    "discord":           "Discord",
    "figma":             "Figma",
    "instacart":         "Instacart",
    "reddit":            "Reddit",
    "pinterest":         "Pinterest",
    "dropbox":           "Dropbox",
    "canva":             "Canva",
    "chime":             "Chime",
    "yelp":              "Yelp",
    "eventbrite":        "Eventbrite",
    "tripadvisor":       "TripAdvisor",
    "duolingo":          "Duolingo",
    "nextdoor":          "Nextdoor",
    "poshmark":          "Poshmark",
    "thumbtack":         "Thumbtack",
    "voxmedia":          "Vox Media",
    "buzzfeed":          "BuzzFeed",
    "theathleticmedia":  "The Athletic",
    "morningbrew":       "Morning Brew",
    "hubspot":           "HubSpot",
    "sproutsocial":      "Sprout Social",
    "hootsuite":         "Hootsuite",
    "later":             "Later",
    "buffer":            "Buffer",
    # Marketing / Martech Platforms
    "klaviyo":           "Klaviyo",
    "braze":             "Braze",
    "attentive":         "Attentive",
    "yotpo":             "Yotpo",
    "amplitude":         "Amplitude",
    "typeform":          "Typeform",
    "airtable":          "Airtable",
    "intercom":          "Intercom",
    "twilio":            "Twilio",
    "asana":             "Asana",
    # Agencies / PR
    "webershandwick":    "Weber Shandwick",
    # Tickets / Events / Sports
    "seatgeek":          "SeatGeek",
    # Food / Bev / Delivery
    "sweetgreen":        "Sweetgreen",
    "grubhub":           "Grubhub",
    "gopuff":            "GoPuff",
    "beyondmeat":        "Beyond Meat",
    "oatly":             "Oatly",
    "drizly":            "Drizly",
    "snackpass":         "Snackpass",
}


def fetch_remoteok():
    """Remote OK — free JSON API, no key. Searches multiple tags and deduplicates."""
    seen, jobs = set(), []

    for tag in REMOTEOK_TAGS:
        try:
            resp = requests.get(
                f"https://remoteok.com/api?tag={tag}",
                headers=HEADERS, timeout=20
            )
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            print(f"  [!] RemoteOK ({tag}) error: {e}")
            continue

        for item in raw:
            if not isinstance(item, dict) or not item.get("position"):
                continue
            link    = item.get("url") or item.get("apply_url") or ""
            title   = html.unescape(item["position"])
            company = html.unescape(item.get("company", ""))

            if link in seen:
                continue
            if not is_ascii(title) or not is_ascii(company):
                continue
            raw_loc = item.get("location", "")
            if is_blocked_company(company):
                continue
            if not is_us_compatible(raw_loc):
                continue
            if not is_remote_or_hybrid(raw_loc, tags=item.get("tags", [])):
                continue
            if not description_is_us_compatible(item.get("description", "")):
                continue
            if not is_relevant_title(title):
                continue
            if not is_marketing_title(title):
                continue
            if not salary_ok(item.get("salary_min"), item.get("salary_max")):
                continue

            s_min = float(item.get("salary_min") or 0)
            s_max = float(item.get("salary_max") or 0)
            if s_min > 0 and s_max > 0:
                salary = f"${int(s_min/1000)}k – ${int(s_max/1000)}k"
            elif s_max > 0:
                salary = f"Up to ${int(s_max/1000)}k"
            elif s_min > 0:
                salary = f"From ${int(s_min/1000)}k"
            else:
                salary = ""

            seen.add(link)
            jobs.append({
                "title":    title,
                "company":  company,
                "location": work_arrangement(raw_loc),
                "link":     link.replace("remoteOK.com", "remoteok.com"),
                "source":   "RemoteOK",
                "food":     is_food_adjacent(title, company),
                "known":    is_known_company(company),
                "salary":   salary,
            })

    print(f"  RemoteOK → {len(jobs)} matches")
    return jobs


def fetch_remotive():
    """Remotive — free JSON API, no key. Remote-only board with US location filter."""
    jobs = []

    for category in ["marketing", "copywriting"]:
        try:
            resp = requests.get(
                f"https://remotive.com/api/remote-jobs?category={category}&limit=100",
                headers=HEADERS, timeout=20
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [!] Remotive ({category}) error: {e}")
            continue

        for item in data.get("jobs", []):
            title   = (item.get("title") or "").strip()
            company = (item.get("company_name") or "").strip()
            raw_loc = (item.get("candidate_required_location") or "").strip()
            link    = (item.get("url") or "").strip()

            if not title or not link:
                continue
            if not is_ascii(title) or not is_ascii(company):
                continue
            if is_blocked_company(company):
                continue
            if not is_us_compatible(raw_loc):
                continue
            if not description_is_us_compatible(item.get("description", "")):
                continue
            if not is_relevant_title(title):
                continue
            if not is_marketing_title(title):
                continue

            jobs.append({
                "title":    title,
                "company":  company,
                "location": work_arrangement(raw_loc) if raw_loc else "Remote",
                "link":     link,
                "source":   "Remotive",
                "food":     is_food_adjacent(title, company),
                "known":    is_known_company(company),
                "salary":   item.get("salary", ""),
            })

    print(f"  Remotive → {len(jobs)} matches")
    return jobs


def fetch_greenhouse():
    """Query public Greenhouse job boards for known companies — no API key needed."""
    jobs = []
    seen_titles = set()  # dedupe same title at same company (multiple open reqs)

    for slug, company_name in GREENHOUSE_COMPANIES.items():
        try:
            resp = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                headers=HEADERS, timeout=15
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
        except Exception as e:
            print(f"  [!] Greenhouse ({slug}) error: {e}")
            continue

        company_count = 0
        for item in data.get("jobs", []):
            if company_count >= 4:  # cap per company so one org can't dominate
                break
            title   = (item.get("title") or "").strip()
            raw_loc = ((item.get("location") or {}).get("name") or "").strip()
            link    = (item.get("absolute_url") or "").strip()

            if not title or not link:
                continue
            if not is_ascii(title):
                continue
            if not is_relevant_title(title):
                continue
            if not is_marketing_title(title):
                continue
            if not is_us_compatible(raw_loc):
                continue
            if not has_remote_or_hybrid_signal(raw_loc):
                continue

            title_key = f"{title.lower()}|{company_name.lower()}"
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            jobs.append({
                "title":    title,
                "company":  company_name,
                "location": work_arrangement(raw_loc),
                "link":     link,
                "source":   "Greenhouse",
                "food":     is_food_adjacent(title, company_name),
                "known":    is_known_company(company_name),
                "salary":   "",
            })
            company_count += 1

        time_mod.sleep(0.4)  # polite crawl rate

    print(f"  Greenhouse → {len(jobs)} matches")
    return jobs


# Public Lever job boards — no API key required; missing slugs return empty list
LEVER_COMPANIES = {
    # Tech / Media / Consumer
    "netflix":          "Netflix",
    "lyft":             "Lyft",
    "stripe":           "Stripe",
    "twitch":           "Twitch",
    "patreon":          "Patreon",
    "medium":           "Medium",
    "substack":         "Substack",
    "redfin":           "Redfin",
    "warbyparker":      "Warby Parker",
    "allbirds":         "Allbirds",
    "glossier":         "Glossier",
    "headspace":        "Headspace",
    "calm":             "Calm",
    "noom":             "Noom",
    "peloton":          "Peloton",
    "classpass":        "ClassPass",
    "bumble":           "Bumble",
    "draftkings":       "DraftKings",
    "fanduel":          "FanDuel",
    "rover":            "Rover",
    "angi":             "Angi",
    "wayfair":          "Wayfair",
    "zola":             "Zola",
    # Food / Bev / CPG
    "chobani":          "Chobani",
    "daily-harvest":    "Daily Harvest",
    "imperfect-foods":  "Imperfect Foods",
    "thrive-market":    "Thrive Market",
    "athletic-brewing": "Athletic Brewing",
    "liquid-death":     "Liquid Death",
    "olipop":           "Olipop",
    "poppi":            "Poppi",
    "fishwife":         "Fishwife",
    # Sports / Entertainment
    "livenation":       "Live Nation",
    "draftkings":       "DraftKings",
    "nba":              "NBA",
    # Agencies / Marketing
    "edelman":          "Edelman",
    "golin":            "Golin",
    "praytell":         "Praytell",
    "crossmedia":       "Crossmedia",
}


def fetch_lever():
    """Query public Lever job boards for known companies — no API key needed."""
    jobs = []
    seen_titles = set()

    for slug, company_name in LEVER_COMPANIES.items():
        try:
            resp = requests.get(
                f"https://api.lever.co/v0/postings/{slug}?mode=json",
                headers=HEADERS, timeout=15
            )
            if resp.status_code != 200:
                continue
            postings = resp.json()
            if not isinstance(postings, list):
                continue
        except Exception as e:
            print(f"  [!] Lever ({slug}) error: {e}")
            continue

        company_count = 0
        for item in postings:
            if company_count >= 4:
                break
            title   = (item.get("text") or "").strip()
            cats    = item.get("categories") or {}
            raw_loc = (cats.get("location") or "").strip()
            link    = (item.get("hostedUrl") or "").strip()

            if not title or not link:
                continue
            if not is_ascii(title):
                continue
            if not is_relevant_title(title):
                continue
            if not is_marketing_title(title):
                continue
            if not has_remote_or_hybrid_signal(raw_loc):
                continue

            title_key = f"{title.lower()}|{company_name.lower()}"
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            jobs.append({
                "title":    title,
                "company":  company_name,
                "location": work_arrangement(raw_loc) if raw_loc else "Remote",
                "link":     link,
                "source":   "Lever",
                "food":     is_food_adjacent(title, company_name),
                "known":    is_known_company(company_name),
                "salary":   "",
            })
            company_count += 1

        time_mod.sleep(0.3)

    print(f"  Lever → {len(jobs)} matches")
    return jobs


# ── Email ─────────────────────────────────────────────────────────────────────

def build_html(jobs, date_str):
    count_line = f"{len(jobs)} listings" if jobs else "No new listings"

    if not jobs:
        rows = (
            "<tr><td style='padding:28px;color:#999;text-align:center;font-size:14px;'>"
            "No new listings today. Check back tomorrow!</td></tr>"
        )
    else:
        rows = ""
        for job in jobs:
            food_badge = (
                "<span style='background:#fff3cd;color:#856404;font-size:11px;"
                "padding:2px 8px;border-radius:10px;margin-left:6px;'>Food/Bev</span>"
            ) if job["food"] else ""
            known_badge = (
                "<span style='background:#e8f4ea;color:#2d6a35;font-size:11px;"
                "padding:2px 8px;border-radius:10px;margin-left:6px;'>⭐ Known Brand</span>"
            ) if job["known"] else ""
            source_note = f"<span style='font-size:10px;color:#ccc;margin-left:6px;'>via {job['source']}</span>"
            rows += f"""
            <tr>
              <td style="padding:20px 24px;border-bottom:1px solid #eef0f3;">
                <div style="font-size:16px;font-weight:600;color:#1C2B3A;line-height:1.3;">
                  {job['title']}{food_badge}{known_badge}
                </div>
                <div style="font-size:13px;color:#6B7E8F;margin-top:3px;">
                  {job['company']}{source_note}
                </div>
                <div style="font-size:12px;color:#bbb;margin-top:2px;">{job['location']}{(' &nbsp;·&nbsp; <span style="color:#2d6a35;font-weight:600;">' + job['salary'] + '</span>') if job.get('salary') else ''}</div>
                <a href="{job['link']}"
                   style="display:inline-block;margin-top:12px;padding:8px 18px;
                          background:#2B4C7E;color:#fff;text-decoration:none;
                          border-radius:5px;font-size:13px;font-weight:500;">
                  View &amp; Apply →
                </a>
              </td>
            </tr>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#EEF3F8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:600px;margin:30px auto;border-radius:10px;overflow:hidden;box-shadow:0 3px 14px rgba(0,0,0,0.1);background:#fff;">
    <div style="background:#2B4C7E;padding:28px 24px;">
      <div style="font-size:22px;font-weight:700;color:#fff;">Your Daily Job Digest</div>
      <div style="font-size:13px;color:#8DA9C4;margin-top:5px;">{date_str} &nbsp;·&nbsp; {count_line}</div>
    </div>
    <table style="width:100%;border-collapse:collapse;">{rows}</table>
    <div style="padding:16px 24px;background:#f7f9fc;font-size:12px;color:#bbb;text-align:center;line-height:1.7;">
      Searching: experiential · sponsorships · social media · content creation<br>
      Filters: remote/hybrid · Specialist or Manager level
    </div>
  </div>
</body></html>"""


def get_gmail_password():
    """Read Gmail App Password from env var (GitHub Actions) or macOS Keychain (local)."""
    pw = os.environ.get("GMAIL_PASSWORD")
    if pw:
        return pw
    result = subprocess.run(
        ["security", "find-internet-password", "-s", "smtp.gmail.com",
         "-a", GMAIL_SENDER, "-w"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("ERROR: Set GMAIL_PASSWORD env var or store in macOS Keychain.")
        sys.exit(1)
    return result.stdout.strip()


def send_email(html, date_str, count):
    password = get_gmail_password()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Job Digest ({count} listings) — {date_str}"
    msg["From"]    = GMAIL_SENDER
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_SENDER, password)
        server.sendmail(GMAIL_SENDER, TO_EMAIL, msg.as_string())

    print(f"Email sent: {count} jobs — {date_str}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if already_ran_today():
        print(f"Already ran today ({datetime.now().strftime('%Y-%m-%d')}), skipping.")
        return

    print(f"Job search starting — {datetime.now()}")
    sent = load_sent()

    all_jobs, seen_links, seen_titles = [], set(), set()
    all_sources = fetch_remoteok() + fetch_remotive() + fetch_greenhouse()
    for job in all_sources:
        link       = job["link"]
        title_key  = f"{job['title'].lower()}|{job['company'].lower()}"
        if link in seen_links or link in sent or title_key in seen_titles:
            continue
        seen_links.add(link)
        seen_titles.add(title_key)
        all_jobs.append(job)

    # Sort: known+food → known → food → rest
    all_jobs.sort(key=lambda j: (
        0 if j["known"] and j["food"] else
        1 if j["known"] else
        2 if j["food"] else
        3,
        j["title"].lower()
    ))
    all_jobs = all_jobs[:10]

    date_str = datetime.now().strftime("%B %d, %Y")
    html = build_html(all_jobs, date_str)
    send_email(html, date_str, len(all_jobs))

    # Record sent jobs so they don't repeat
    save_sent({**sent, **{j["link"]: datetime.now().isoformat() for j in all_jobs}})
    mark_ran()


if __name__ == "__main__":
    main()
