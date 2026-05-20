"""
Fetches AI/tech news from free RSS feeds and APIs.
Filters to yesterday's date window and deduplicates against history.json.
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
        "name": "MIT Tech Review AI",
        "url": "https://www.technologyreview.com/feed/",
        "category": "pesquisa",
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
            sim = _jaccard(title_tokens, set(stored_tokens))
            if sim >= SIMILARITY_THRESHOLD:
                return True
    return False


def _fetch_url(url: str, timeout: int = 10) -> Optional[str]:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AIDigestBot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [warn] Failed to fetch {url}: {e}")
        return None


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Try multiple date formats found in RSS feeds."""
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
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
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # Handle both RSS 2.0 and Atom
    entries = root.findall(".//item") or root.findall(".//atom:entry", ns)

    for entry in entries:
        title_el = entry.find("title") or entry.find("atom:title", ns)
        link_el = entry.find("link") or entry.find("atom:link", ns)
        date_el = (
            entry.find("pubDate")
            or entry.find("atom:published", ns)
            or entry.find("atom:updated", ns)
            or entry.find("dc:date")
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

        items.append(
            {
                "title": title,
                "url": link,
                "pub_date": pub_date,
                "summary": summary,
                "source": source_name,
                "category": category,
            }
        )

    return items


def _fetch_hacker_news(yesterday: datetime) -> list[dict]:
    """Use Algolia HN API to search for AI stories from yesterday."""
    items = []
    ts_start = int(yesterday.timestamp())
    ts_end = int((yesterday + timedelta(days=1)).timestamp())
    query = "AI OR artificial intelligence OR LLM OR machine learning OR OpenAI OR Anthropic OR Google DeepMind"
    encoded = urllib.parse.quote(query)
    url = (
        f"https://hn.algolia.com/api/v1/search_by_date"
        f"?query={encoded}&numericFilters=created_at_i>{ts_start},"
        f"created_at_i<{ts_end}&hitsPerPage=20&tags=story"
    )
    raw = _fetch_url(url)
    if not raw:
        return items

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return items

    for hit in data.get("hits", []):
        title = hit.get("title", "").strip()
        if not title:
            continue
        url_story = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
        created = hit.get("created_at_i")
        pub_date = datetime.fromtimestamp(created, tz=timezone.utc) if created else None
        points = hit.get("points", 0) or 0
        if points < 10:  # Skip low-signal stories
            continue
        items.append(
            {
                "title": title,
                "url": url_story,
                "pub_date": pub_date,
                "summary": "",
                "source": "Hacker News",
                "category": "comunidade",
                "points": points,
            }
        )
    return items


def _fetch_reddit_ml(yesterday: datetime) -> list[dict]:
    """Fetch top posts from r/MachineLearning and r/artificial from yesterday."""
    items = []
    subreddits = ["MachineLearning", "artificial", "OpenAI"]
    ts_start = int(yesterday.timestamp())
    ts_end = int((yesterday + timedelta(days=1)).timestamp())

    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
        raw = _fetch_url(url)
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for post in data.get("data", {}).get("children", []):
            d = post.get("data", {})
            created = int(d.get("created_utc", 0))
            if not (ts_start <= created < ts_end):
                continue
            title = d.get("title", "").strip()
            if not title:
                continue
            score = d.get("score", 0) or 0
            if score < 5:
                continue
            link = d.get("url") or f"https://reddit.com{d.get('permalink', '')}"
            pub_date = datetime.fromtimestamp(created, tz=timezone.utc)
            items.append(
                {
                    "title": title,
                    "url": link,
                    "pub_date": pub_date,
                    "summary": d.get("selftext", "")[:200].strip(),
                    "source": f"Reddit r/{sub}",
                    "category": "pesquisa",
                    "score": score,
                }
            )
        time.sleep(1)  # Reddit rate limiting

    return items


def fetch_news(dry_run: bool = False) -> list[dict]:
    """
    Fetch yesterday's AI/tech news, filtered and deduplicated.
    Returns list of story dicts sorted by relevance.
    """
    now = datetime.now(timezone.utc)
    yesterday_start = (now - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    yesterday_end = yesterday_start + timedelta(days=1)

    print(f"[news] Fetching news for {yesterday_start.date()}...")

    history = load_history()
    all_stories: list[dict] = []

    # RSS sources
    for source in RSS_SOURCES:
        print(f"  Fetching {source['name']}...")
        raw = _fetch_url(source["url"])
        if raw:
            stories = _parse_rss(raw, source["name"], source["category"])
            # Filter to yesterday
            for s in stories:
                if s["pub_date"] and yesterday_start <= s["pub_date"] < yesterday_end:
                    all_stories.append(s)
        time.sleep(0.5)

    # Hacker News
    print("  Fetching Hacker News...")
    all_stories.extend(_fetch_hacker_news(yesterday_start))

    # Reddit
    print("  Fetching Reddit...")
    all_stories.extend(_fetch_reddit_ml(yesterday_start))

    print(f"[news] Found {len(all_stories)} raw stories, deduplicating...")

    # Deduplicate against history + within current batch
    seen_titles: set[str] = set()
    filtered = []
    for story in all_stories:
        title = story["title"]
        h = _title_hash(title)
        if h in seen_titles:
            continue
        seen_titles.add(h)
        if is_duplicate(title, history):
            print(f"  [skip] Duplicate: {title[:60]}")
            continue
        filtered.append(story)

    # Sort: prefer HN points and Reddit score as proxy for relevance
    def _rank(s: dict) -> float:
        base = s.get("points", 0) or s.get("score", 0) or 5
        return float(base)

    filtered.sort(key=_rank, reverse=True)

    print(f"[news] {len(filtered)} unique stories after dedup")

    if dry_run:
        for s in filtered[:6]:
            print(f"  [{s['source']}] {s['title'][:80]}")

    return filtered[:6]


if __name__ == "__main__":
    stories = fetch_news(dry_run=True)
    print(f"\nTop {len(stories)} stories ready for content generation.")
