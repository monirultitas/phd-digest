#!/usr/bin/env python3
"""Daily PhD and grant opportunity digest — Monirul Islam."""

import os
import smtplib
import textwrap
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import feedparser

# ---------------------------------------------------------------------------
# Config — override via environment variables (GitHub Secrets)
# ---------------------------------------------------------------------------
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "monirtitas@gmail.com")
SENDER_EMAIL    = os.environ.get("SENDER_EMAIL", "monirtitas@gmail.com")
SMTP_PASSWORD   = os.environ["SMTP_PASSWORD"]          # required; set as Secret
SMTP_HOST       = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.environ.get("SMTP_PORT", "587"))

# How many hours back to look for new items (48h covers missed weekend runs)
LOOKBACK_HOURS  = int(os.environ.get("LOOKBACK_HOURS", "48"))

# ---------------------------------------------------------------------------
# Keywords — tuned to your research profile
# ---------------------------------------------------------------------------
HIGH_PRIORITY = [
    "remote sensing", "earth observation", "satellite image",
    "flood mapping", "flood susceptibility", "flood modelling",
    "SAR", "Sentinel-1", "Sentinel-2", "synthetic aperture",
    "GeoAI", "geospatial AI", "geospatial machine learning",
    "hydrology", "hydrological", "hydrological modelling",
    "LULC", "land use land cover", "land cover change",
]

MEDIUM_PRIORITY = [
    "GIS", "geospatial", "geomatics", "spatial data",
    "drone", "UAV", "unmanned aerial",
    "machine learning remote", "deep learning remote",
    "climate change", "disaster risk", "disaster management",
    "Bangladesh", "South Asia", "haor", "wetland",
    "lidar", "hyperspectral", "multispectral",
    "environmental monitoring", "land degradation",
]

# Entries containing any of these AND no funding keyword are lower value
SELF_FUNDED_FLAGS = [
    "self-funded only", "self-funded students only",
    "no funding available", "unfunded",
]

# Skip entries whose title/summary is dominated by these (irrelevant fields)
EXCLUDE_TERMS = [
    "pharmaceutical", "clinical trial", "drug delivery", "oncology",
    "neuroscience", "psychology", "sociology", "literature", "history",
    "architecture", "mechanical engineering", "electrical engineering",
    "law", "economics", "business administration", "accounting",
    "music", "art history", "theology",
]

# ---------------------------------------------------------------------------
# RSS feed sources
# ---------------------------------------------------------------------------
FEEDS = [
    # FindAPhD — broad remote sensing
    ("FindAPhD", "Remote Sensing PhD",
     "https://www.findaphd.com/phds/rss/?Keywords=remote+sensing&Submit=Search"),
    ("FindAPhD", "Flood GIS PhD",
     "https://www.findaphd.com/phds/rss/?Keywords=flood+GIS&Submit=Search"),
    ("FindAPhD", "Earth Observation PhD",
     "https://www.findaphd.com/phds/rss/?Keywords=earth+observation&Submit=Search"),
    ("FindAPhD", "Hydrology PhD",
     "https://www.findaphd.com/phds/rss/?Keywords=hydrology+machine+learning&Submit=Search"),
    # jobs.ac.uk
    ("jobs.ac.uk", "Remote Sensing",
     "https://www.jobs.ac.uk/search/?keywords=remote+sensing+phd&rss=1"),
    ("jobs.ac.uk", "Hydrology GIS",
     "https://www.jobs.ac.uk/search/?keywords=hydrology+GIS+phd&rss=1"),
    ("jobs.ac.uk", "Earth Observation",
     "https://www.jobs.ac.uk/search/?keywords=earth+observation+phd&rss=1"),
    # EURAXESS — European research positions
    ("EURAXESS", "Remote Sensing",
     "https://euraxess.ec.europa.eu/jobs/rss.xml?keywords=remote+sensing"),
    ("EURAXESS", "Flood Hydrology",
     "https://euraxess.ec.europa.eu/jobs/rss.xml?keywords=flood+hydrology"),
    # Academic Positions
    ("Academic Positions", "Remote Sensing",
     "https://academicpositions.com/jobs/rss?q=remote+sensing"),
    ("Academic Positions", "GeoAI",
     "https://academicpositions.com/jobs/rss?q=GeoAI+geospatial"),
    # Nature Careers
    ("Nature Careers", "Remote Sensing",
     "https://www.nature.com/naturecareers/jobs.rss?term=remote+sensing"),
    # Google Alerts — RSS feeds (created 2026-10-16)
    ("Google Alerts", "PhD flood mapping funded",
     "https://www.google.com/alerts/feeds/14103899754495623098/6766904095506019170"),
    ("Google Alerts", "PhD hydrology machine learning funded",
     "https://www.google.com/alerts/feeds/14103899754495623098/17993141065103238557"),
    ("Google Alerts", "GeoAI fellowship grant PhD",
     "https://www.google.com/alerts/feeds/14103899754495623098/9040683348819241136"),
    ("Google Alerts", "Earth observation PhD fellowship funded",
     "https://www.google.com/alerts/feeds/14103899754495623098/9598089568831618758"),
    ("Google Alerts", "SAR Sentinel-1 PhD research grant funded",
     "https://www.google.com/alerts/feeds/14103899754495623098/12510522689205402605"),
    ("Google Alerts", "PhD remote sensing funded",
     "https://www.google.com/alerts/feeds/14103899754495623098/456395825921442112"),
]

# ---------------------------------------------------------------------------
# Scoring and filtering helpers
# ---------------------------------------------------------------------------

def text_of(entry) -> str:
    """Return a single lowercase string combining title + summary."""
    title   = getattr(entry, "title",   "") or ""
    summary = getattr(entry, "summary", "") or ""
    return (title + " " + summary).lower()


def score_entry(entry) -> int:
    """Return a relevance score (0 = irrelevant)."""
    text = text_of(entry)
    for term in EXCLUDE_TERMS:
        if term.lower() in text:
            return 0
    score = 0
    for kw in HIGH_PRIORITY:
        if kw.lower() in text:
            score += 3
    for kw in MEDIUM_PRIORITY:
        if kw.lower() in text:
            score += 1
    return score


def is_self_funded_only(entry) -> bool:
    text = text_of(entry)
    return any(flag in text for flag in SELF_FUNDED_FLAGS)


def entry_published(entry) -> datetime | None:
    """Return a timezone-aware datetime for when the entry was published."""
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                import time as _time
                ts = _time.mktime(val)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# Fetch feeds
# ---------------------------------------------------------------------------

def fetch_all_feeds(lookback: timedelta) -> list[dict]:
    cutoff = datetime.now(tz=timezone.utc) - lookback
    results = []
    seen_links = set()

    for source, label, url in FEEDS:
        try:
            feed = feedparser.parse(url, agent="Mozilla/5.0 (compatible; PhD-Digest/1.0)")
        except Exception as exc:
            print(f"[WARN] Could not fetch {source}/{label}: {exc}")
            continue

        for entry in feed.entries:
            link = getattr(entry, "link", "") or ""
            if link in seen_links:
                continue

            pub = entry_published(entry)
            if pub and pub < cutoff:
                continue          # too old

            score = score_entry(entry)
            if score == 0:
                continue

            results.append({
                "source":      source,
                "label":       label,
                "title":       getattr(entry, "title",   "(no title)"),
                "link":        link,
                "summary":     getattr(entry, "summary", ""),
                "published":   pub,
                "score":       score,
                "self_funded": is_self_funded_only(entry),
            })
            seen_links.add(link)

    results.sort(key=lambda x: (-x["score"], x["source"]))
    return results


# ---------------------------------------------------------------------------
# Email builder
# ---------------------------------------------------------------------------
CSS = """
body{font-family:Arial,sans-serif;font-size:14px;color:#222;max-width:700px;margin:0 auto;padding:16px}
h1{font-size:20px;color:#1a4a8a;border-bottom:2px solid #1a4a8a;padding-bottom:6px}
h2{font-size:13px;color:#555;font-weight:normal;margin-top:0}
.item{border:1px solid #ddd;border-radius:6px;padding:12px 14px;margin-bottom:12px}
.item.hot{border-left:4px solid #c0392b}
.item.self-funded{opacity:0.7}
.tag{display:inline-block;font-size:11px;padding:2px 7px;border-radius:10px;margin-right:4px;background:#e8f0fe;color:#1a4a8a}
.tag.warn{background:#fef3cd;color:#856404}
.item-title{font-size:15px;font-weight:bold;margin:0 0 4px}
.item-title a{color:#1a4a8a;text-decoration:none}
.item-title a:hover{text-decoration:underline}
.item-meta{font-size:12px;color:#888;margin-bottom:6px}
.item-summary{font-size:13px;color:#444;margin:0}
.footer{font-size:12px;color:#aaa;margin-top:24px;border-top:1px solid #eee;padding-top:8px}
"""


def truncate(text: str, n: int = 200) -> str:
    text = text.replace("<br>", " ").replace("&nbsp;", " ")
    # strip HTML tags crudely
    import re
    text = re.sub(r"<[^>]+>", "", text)
    text = text.strip()
    return textwrap.shorten(text, width=n, placeholder="…")


def build_html(items: list[dict], generated_at: datetime) -> str:
    date_str = generated_at.strftime("%a %d %b %Y")
    count    = len(items)
    hot      = [i for i in items if i["score"] >= 6]

    rows = []
    for item in items:
        is_hot = item["score"] >= 6
        sf     = item["self_funded"]
        cls    = "item"
        if is_hot: cls += " hot"
        if sf:     cls += " self-funded"

        pub_str = ""
        if item["published"]:
            pub_str = item["published"].strftime("%d %b %Y")

        tags_html = f'<span class="tag">{escape(item["source"])}</span>'
        tags_html += f'<span class="tag">{escape(item["label"])}</span>'
        if is_hot:
            tags_html += '<span class="tag" style="background:#fde;color:#c00">High match</span>'
        if sf:
            tags_html += '<span class="tag warn">Self-funded</span>'

        summary_html = truncate(item["summary"], 250)

        rows.append(f"""
<div class="{cls}">
  <p class="item-title"><a href="{escape(item['link'])}">{escape(item['title'])}</a></p>
  <p class="item-meta">{tags_html} &nbsp; {pub_str}</p>
  <p class="item-summary">{escape(summary_html)}</p>
</div>""")

    rows_html = "\n".join(rows) if rows else "<p>No new items found in the last 48 hours.</p>"
    hot_note  = f"<b>{len(hot)} high-match</b> items today." if hot else "No high-match items today."

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><style>{CSS}</style></head>
<body>
<h1>PhD &amp; Grant Digest — {date_str}</h1>
<h2>{count} new opportunities found in the last 48 h &nbsp;|&nbsp; {hot_note}</h2>
{rows_html}
<div class="footer">
  Generated {generated_at.strftime("%Y-%m-%d %H:%M UTC")} by phd-digest &middot;
  <a href="https://github.com/monirtitas/phd-digest">github.com/monirtitas/phd-digest</a>
</div>
</body>
</html>"""


def build_plaintext(items: list[dict]) -> str:
    lines = []
    for i, item in enumerate(items, 1):
        pub = item["published"].strftime("%d %b %Y") if item["published"] else ""
        lines.append(f"{i}. [{item['source']}] {item['title']}")
        if pub:
            lines.append(f"   Date: {pub}")
        lines.append(f"   {item['link']}")
        if item["self_funded"]:
            lines.append("   ** Self-funded — check funding carefully **")
        lines.append("")
    return "\n".join(lines) if lines else "No new items found in the last 48 hours."


# ---------------------------------------------------------------------------
# Send email
# ---------------------------------------------------------------------------

def send_email(html: str, plain: str, item_count: int) -> None:
    now      = datetime.now(tz=timezone.utc)
    subject  = f"PhD Digest {now.strftime('%d %b %Y')} — {item_count} new opportunities"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECIPIENT_EMAIL

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html,  "html",  "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SENDER_EMAIL, SMTP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
    print(f"[OK] Email sent to {RECIPIENT_EMAIL} ({item_count} items)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    now      = datetime.now(tz=timezone.utc)
    lookback = timedelta(hours=LOOKBACK_HOURS)

    print(f"[INFO] Fetching feeds, looking back {LOOKBACK_HOURS}h …")
    items = fetch_all_feeds(lookback)
    print(f"[INFO] {len(items)} relevant items found")

    html  = build_html(items, now)
    plain = build_plaintext(items)

    if not items:
        print("[INFO] No new items — sending empty digest anyway")

    send_email(html, plain, len(items))


if __name__ == "__main__":
    main()
