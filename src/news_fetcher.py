"""
Fetches AI/tech news from free RSS feeds and APIs.
Filters to the last 48h window and deduplicates against history.json.
"""
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

HISTORY_PATH = Path(__file__).parent.parent / "data" / "history.json"
DEDUP_WINDOW_DAYS = 14
SIMILARITY_THRESHOLD = 0.70

RSS_SOURCES = [
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "category": "empresas",
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
        "category": "empresas",
    },
    {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
        "category": "produtos",
    },
    {
        "name": "Wired AI",
        "url": "https://www.wired.com/feed/tag/artificial-intelligence/latest/rss",
        "category": "análise",
    },
    {
        "name": "MIT Tech Review",
        "url": "https://www.technologyreview.com/feed/",
        "category": "pesquisa",
    },
    {
        "name": "Ars Technica AI",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "category": "análise",
    },
    {
        "name": "Google News AI",
        "url": "https://news.google.com/rss/search?q=artificial+intelligence+OR+OpenAI+OR+Anthropic+OR+Gemini&hl=en-US&gl=US&ceid=US:en",
        "category": "geral",
    },
]

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "de", "da", "do", "das", "dos", "e",
    "o", "a", "os", "as", "um", "uma", "em", "no", "na", "nos", "nas",
    "que", "para", "por", "com", "se", "seu", "sua", "seus", "suas",
}


def _normalize_title(title: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", title.lower())
    return {t for t in tokens if t not in STOPWORDS and len(t) > 2}


def _title_hash(title: str) -> str:
    return hashlib.sha256(title.lower().strip().encode()).hexdigest()


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_history() -> dict:
    if HISTORY_PATH.exists():
        with open(HISTORY_PATH) as f:
            return json.load(f)
    return {"posts": []}


def is_duplicate(title: str, history: dict) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=DEDUP_WINDOW_DAYS)
    title_tokens = _normalize_title(title)
    title_h = _title_hash(title)

    for post in history.get("posts", []):
        try:
            post_date = datetime.fromisoformat(post["date"]).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if post_date < cutoff:
            continue
        if title_h in post.get("title_hashes", []):
            return True
        for stored_tokens in post.get("topic_tokens", []):
            if _jaccard(title_tokens, set(stored_tokens)) >= SIMILARITY_THRESHOLD:
                return True
    return False


def _fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            # Try UTF-8, fall back to latin-1
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1", errors="replace")
    except Exception as e:
        print(f"  [warn] Failed to fetch {url[:60]}: {e}")
        return None


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _parse_rss(xml_text: str, source_name: str, category: str) -> list[dict]:
    items = []
    try:
        # Strip BOM and whitespace
        xml_text = xml_text.lstrip("﻿").strip()
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  [warn] XML parse error for {source_name}: {e}")
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall(".//item") or root.findall(".//atom:entry", ns)
    print(f"  [{source_name}] {len(entries)} entries found in feed")

    for entry in entries:
        title_el = entry.find("title") or entry.find("atom:title", ns)
        link_el = entry.find("link") or entry.find("atom:link", ns)
        date_el = (
            entry.find("pubDate")
            or entry.find("atom:published", ns)
            or entry.find("atom:updated", ns)
        )
        desc_el = (
            entry.find("description")
            or entry.find("atom:summary", ns)
            or entry.find("atom:content", ns)
        )

        if title_el is None:
            continue

        title = (title_el.text or "").strip()
        if not title:
            continue

        link = ""
        if link_el is not None:
            link = link_el.get("href") or link_el.text or ""
        link = link.strip()

        pub_date = None
        if date_el is not None and date_el.text:
            pub_date = _parse_rss_date(date_el.text)

        summary = ""
        if desc_el is not None and desc_el.text:
            summary = re.sub(r"<[^>]+>", "", desc_el.text or "").strip()
            summary = " ".join(summary.split())[:300]

        items.append({
            "title": title,
            "url": link,
            "pub_date": pub_date,
            "summary": summary,
            "source": source_name,
            "category": category,
        })

    return items


def _fetch_hacker_news(window_start: datetime, window_end: datetime) -> list[dict]:
    items = []
    ts_start = int(window_start.timestamp())
    ts_end = int(window_end.timestamp())
    queries = [
        "artificial intelligence OR machine learning OR LLM",
        "OpenAI OR Anthropic OR Google DeepMind OR Meta AI",
        "GPT OR Claude OR Gemini OR Llama",
    ]
    seen = set()
    for query in queries:
        encoded = urllib.parse.quote(query)
        url = (
            f"https://hn.algolia.com/api/v1/search_by_date"
            f"?query={encoded}&numericFilters=created_at_i>{ts_start},"
            f"created_at_i<{ts_end}&hitsPerPage=15&tags=story"
        )
        raw = _fetch_url(url)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for hit in data.get("hits", []):
            title = hit.get("title", "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            points = hit.get("points", 0) or 0
            if points < 5:
                continue
            url_story = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            created = hit.get("created_at_i")
            pub_date = datetime.fromtimestamp(created, tz=timezone.utc) if created else None
            items.append({
                "title": title,
                "url": url_story,
                "pub_date": pub_date,
                "summary": "",
                "source": "Hacker News",
                "category": "comunidade",
                "points": points,
            })
        time.sleep(0.5)

    print(f"  [Hacker News] {len(items)} stories found")
    return items


def _fetch_reddit(window_start: datetime, window_end: datetime) -> list[dict]:
    items = []
    subreddits = ["MachineLearning", "artificial", "OpenAI", "singularity"]
    ts_start = int(window_start.timestamp())
    ts_end = int(window_end.timestamp())

    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
        raw = _fetch_url(url)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        count = 0
        for post in data.get("data", {}).get("children", []):
            d = post.get("data", {})
            created = int(d.get("created_utc", 0))
            if not (ts_start <= created < ts_end):
                continue
            title = d.get("title", "").strip()
            if not title:
                continue
            score = d.get("score", 0) or 0
            if score < 3:
                continue
            link = d.get("url") or f"https://reddit.com{d.get('permalink', '')}"
            pub_date = datetime.fromtimestamp(created, tz=timezone.utc)
            items.append({
                "title": title,
                "url": link,
                "pub_date": pub_date,
                "summary": d.get("selftext", "")[:200].strip(),
                "source": f"Reddit r/{sub}",
                "category": "comunidade",
                "score": score,
            })
            count += 1
        print(f"  [Reddit r/{sub}] {count} stories found")
        time.sleep(1)

    return items


def fetch_news(dry_run: bool = False) -> list[dict]:
    """
    Fetch AI/tech news from the last 48h, filtered and deduplicated.
    Returns list of story dicts sorted by relevance.
    """
    now = datetime.now(timezone.utc)
    # 48h window to handle timezone differences and sparse news days
    window_end = now
    window_start = now - timedelta(hours=48)

    print(f"[news] Fetching news from {window_start.strftime('%Y-%m-%d %H:%M')} UTC to now...")

    history = load_history()
    all_stories: list[dict] = []

    # RSS sources — include all entries (feeds already serve recent articles)
    # Deduplication handles repeated content across days
    for source in RSS_SOURCES:
        print(f"  Fetching {source['name']}...")
        raw = _fetch_url(source["url"])
        if raw:
            stories = _parse_rss(raw, source["name"], source["category"])
            # Accept entries within window, or entries with no parseable date (take top 5)
            in_window = [s for s in stories if s["pub_date"] and window_start <= s["pub_date"] <= window_end]
            no_date = [s for s in stories if not s["pub_date"]]
            if in_window:
                all_stories.extend(in_window)
                print(f"  [{source['name']}] {len(in_window)} in window")
            elif no_date:
                all_stories.extend(no_date[:5])
                print(f"  [{source['name']}] {len(no_date[:5])} (no parseable date, taking top)")
            elif stories:
                # All have dates but outside window — take 3 most recent as fallback
                stories_sorted = sorted([s for s in stories if s["pub_date"]], key=lambda x: x["pub_date"], reverse=True)
                all_stories.extend(stories_sorted[:3])
                oldest = stories_sorted[0]["pub_date"].strftime("%Y-%m-%d") if stories_sorted else "?"
                print(f"  [{source['name']}] outside window, newest={oldest}, taking 3 as fallback")
        time.sleep(0.5)

    # Hacker News
    print("  Fetching Hacker News...")
    all_stories.extend(_fetch_hacker_news(window_start, window_end))

    # Reddit
    print("  Fetching Reddit...")
    all_stories.extend(_fetch_reddit(window_start, window_end))

    print(f"[news] Found {len(all_stories)} raw stories, deduplicating...")

    seen_titles: set[str] = set()
    filtered = []
    for story in all_stories:
        title = story["title"]
        h = _title_hash(title)
        if h in seen_titles:
            continue
        seen_titles.add(h)
        if is_duplicate(title, history):
            print(f"  [skip-dup] {title[:60]}")
            continue
        filtered.append(story)

    # Sort by points/score (proxy for relevance), then recency
    def _rank(s: dict) -> float:
        pts = s.get("points", 0) or s.get("score", 0) or 5
        recency = s["pub_date"].timestamp() if s.get("pub_date") else 0
        return pts * 1000 + recency

    filtered.sort(key=_rank, reverse=True)

    print(f"[news] {len(filtered)} unique stories ready")

    if dry_run:
        for s in filtered[:6]:
            print(f"  [{s['source']}] {s['title'][:80]}")

    return filtered[:6]


if __name__ == "__main__":
    stories = fetch_news(dry_run=True)
    print(f"\nTop {len(stories)} stories ready.")
