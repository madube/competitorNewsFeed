#!/usr/bin/env python3
import os
import re
import json
import time
import hashlib
import logging
import datetime as dt
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional

import requests
import feedparser
from bs4 import BeautifulSoup
import yaml
from dateutil import tz

# ---------- Settings ----------
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
SEEN_PATH = os.path.join(DATA_DIR, "seen.json")
CONFIG_PATH = os.path.join(ROOT, "config.yaml")

# Default timezone for scheduling context
DEFAULT_TZ = "America/Toronto"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------- Utilities ----------

def slugify(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)

def load_seen() -> Dict[str, float]:
    if os.path.exists(SEEN_PATH):
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def save_seen(seen: Dict[str, float]):
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2)

def load_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def is_probable_rss(url: str) -> bool:
    # Heuristic: try parsing and see if feedparser identifies entries
    try:
        fp = feedparser.parse(url)
        return bool(fp.entries)
    except Exception:
        return False

def try_feed(url: str) -> List[Dict[str, Any]]:
    try:
        fp = feedparser.parse(url)
        items = []
        for e in fp.entries[:50]:
            link = e.get("link") or ""
            title = e.get("title") or ""
            summary = e.get("summary") or ""
            published = None
            if e.get("published_parsed"):
                published = time.mktime(e.published_parsed)
            items.append({
                "url": link,
                "title": title,
                "summary": BeautifulSoup(summary, "html.parser").get_text(" ", strip=True),
                "published_ts": published
            })
        return items
    except Exception as ex:
        logging.warning(f"RSS parse failed for {url}: {ex}")
        return []

def try_html(url: str) -> List[Dict[str, Any]]:
    # Fallback: fetch page and extract <a> links with <article> or list items for basic coverage
    # Also use the page itself as a single "article" if nothing else
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Try OpenGraph / meta
        page_title = soup.find("meta", property="og:title")
        if page_title and page_title.get("content"):
            page_title = page_title.get("content")
        else:
            if soup.title and soup.title.string:
                page_title = soup.title.string.strip()
            else:
                page_title = url

        page_desc = soup.find("meta", property="og:description")
        if page_desc and page_desc.get("content"):
            page_desc = page_desc.get("content")
        else:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            page_desc = meta_desc.get("content").strip() if meta_desc and meta_desc.get("content") else ""

        # Collect article-like links
        items = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True)
            if not text:
                continue
            # Heuristic: keep on-site article links
            if href.startswith("/"):
                href = f"{urlparse(url).scheme}://{urlparse(url).netloc}{href}"
            url_netloc = urlparse(url).netloc
            if urlparse(href).netloc != url_netloc:
                continue
            # Prefer likely news/article URLs
            if any(seg in href for seg in ["/news", "/article", "/stories", "/202", "/blog"]):
                items.append({"url": href, "title": text[:200], "summary": "", "published_ts": None})

        # Always include the page itself as a candidate
        items = items[:50]
        if not items:
            items = [{"url": url, "title": page_title[:200], "summary": page_desc[:500], "published_ts": None}]

        return items
    except Exception as ex:
        logging.warning(f"HTML fetch failed for {url}: {ex}")
        return []

def fetch_source_items(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = []
    for u in source.get("urls", []):
        use_rss = is_probable_rss(u)
        items.extend(try_feed(u) if use_rss else try_html(u))
    # Dedup by URL
    seen_urls = set()
    uniq = []
    for it in items:
        if it["url"] in seen_urls:
            continue
        seen_urls.add(it["url"])
        uniq.append(it)
    return uniq

def contains_any(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    for k in keywords:
        if k.lower() in t:
            return True
    return False

def legal_filter(title: str, summary: str, cfg: Dict[str, Any]) -> bool:
    text = f"{title} {summary}"
    return contains_any(text, cfg.get("legal_keywords", []))

def domain_from_url(u: str) -> str:
    try:
        return urlparse(u).netloc.replace("www.", "")
    except Exception:
        return ""

def hash_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()

def filter_and_collect(all_sources: List[Dict[str, Any]], cfg: Dict[str, Any], since_ts: float, seen: Dict[str, float]) -> List[Dict[str, Any]]:
    results = []
    for src in all_sources:
        items = fetch_source_items(src)
        for it in items:
            uid = hash_id(it["url"])
            if uid in seen:
                continue
            # Published time heuristic; if missing, treat as recent
            published = it.get("published_ts") or time.time()
            if published < since_ts:
                continue
            # Must match competitors AND industries AND legal keywords
            text = f"{it.get('title','')} {it.get('summary','')}"
            if not contains_any(text, cfg["competitors"]):
                continue
            if not contains_any(text, cfg["industries"]):
                continue
            if not legal_filter(it.get("title",""), it.get("summary",""), cfg):
                continue

            results.append({
                "title": it.get("title") or "(untitled)",
                "url": it.get("url"),
                "summary": it.get("summary", ""),
                "published_ts": published,
                "source": src.get("name") or domain_from_url(it.get("url",""))
            })
            seen[uid] = time.time()
    return results

def build_slack_blocks(found: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not found:
        return [
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Weekly Regulatory Monitor*\n_No new relevant articles found this period._"}}
        ]

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Weekly Regulatory Monitor", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Compiled {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}"}]},
        {"type": "divider"}
    ]
    for art in sorted(found, key=lambda x: x["published_ts"] or 0, reverse=True):
        ts_str = dt.datetime.fromtimestamp(art["published_ts"]).strftime("%Y-%m-%d") if art.get("published_ts") else "recent"
        title = art["title"].strip() or "(untitled)"
        summary = art["summary"].strip()
        summary = (summary[:300] + "…") if len(summary) > 300 else summary

        blocks.extend([
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*<{art['url']}|{title}>*\n_{art['source']} · {ts_str}_\n{summary}"}},
            {"type": "divider"}
        ])
    return blocks

def post_to_slack(webhook_url: str, blocks: List[Dict[str, Any]]):
    payload = {"blocks": blocks}
    resp = requests.post(webhook_url, json=payload, timeout=20)
    if resp.status_code >= 300:
        raise RuntimeError(f"Slack webhook error {resp.status_code}: {resp.text}")

def main():
    ensure_dirs()
    cfg = load_config()
    seen = load_seen()

    # Period: last 8 days to be safe for weekly runs
    now = dt.datetime.now(tz.gettz(DEFAULT_TZ))
    since = now - dt.timedelta(days=8)
    since_ts = since.timestamp()

    sources = cfg.get("sources", [])
    found = filter_and_collect(sources, cfg, since_ts, seen)

    # Save dedup state regardless
    save_seen(seen)

    blocks = build_slack_blocks(found)

    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    dry_run = False
    if not webhook:
        logging.warning("SLACK_WEBHOOK_URL not set. Running in dry-run mode (printing JSON).")
        dry_run = True

    if dry_run:
        print(json.dumps({"blocks": blocks}, indent=2))
    else:
        post_to_slack(webhook, blocks)
        logging.info(f"Posted {len(blocks)} block(s) to Slack.")

if __name__ == "__main__":
    main()
