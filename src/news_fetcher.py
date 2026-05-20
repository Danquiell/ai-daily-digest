"""
Fetches AI/tech news using feedparser (handles all RSS/Atom quirks).
Deduplicates against history.json using title hashing + Jaccard similarity.
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

import feedparser

HISTORY_PATH = Path(__file__).parent.parent / "data" / "history.json"
DEDUP_WINDOW_DAYS = 14
SIMILARITY_THRESHOLD = 0.70

RSS_SOURCES = [
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
    },
    {
        "name": "MIT Tech Review",
        "url": "https://www.technologyreview.com/feed/",
    },
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
    },
    {
        "name": "The Verge",
        "url": "https://www.theverge.com/rss/index.xml",
    },
    {
        "name": "Google News AI",
        "url": "https://news.google.com/rss/search?q=artificial+intelligence+OR+OpenAI+OR+Anthropic+OR+Gemini+OR+ChatGPT&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "9to5Google AI",
        "url": "https://9to5google.com/feed/",
    },
]

AI_KEYWORDS = {
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "neural network", "llm", "large language model", "openai", "anthropic",
    "gemini", "chatgpt", "claude", "gpt", "llama", "mistral", "deepmind",
    "transformer", "generative", "diffusion", "midjourney", "stable diffusion",
    "robot", "automation", "nlp", "computer vision", "nvidia", "cuda",
    "sam altman", "elon musk", "meta ai", "microsoft copilot", "github copilot",
    "hugging face", "agi", "reinforcement learning", "fine-tuning", "sora",
}

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "de", "da", "do", "das", "dos", "e",
    "o", "a", "os", "as", "um", "uma", "em", "no", "na", "nos", "nas",
    "que", "para", "por", "com", "se", "seu", "sua",
}


def _normalize(title: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", title.lower())
    return {t for t in tokens if t not in STOPWORDS and len(t) > 2}


def _title_hash(title: str) -> str:
    return hashlib.sha256(title.lower().strip().encode()).hexdigest()


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_ai_related(title: str, summary: str = "") -> bool:
    text = (title + " " + summary).lower()
    return any(kw in text for kw in AI_KEYWORDS)


def load_history() -> dict:
    if HISTORY_PATH.exists():
        with open(HISTORY_PATH) as f:
            return json.load(f)
    return {"posts": []}


def is_duplicate(title: str, history: dict) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=DEDUP_WINDOW_DAYS)
    title_tokens = _normalize(title)
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


def _parse_feed_entry_date(entry) -> Optional[datetime]:
    """Extract and normalize publication date from a feedparser entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def fetch_rss_stories(window_start: datetime) -> list[dict]:
    """Fetch from all RSS sources using feedparser."""
    stories = []
    for source in RSS_SOURCES:
        print(f"  Fetching {source['name']}...")
        try:
            feed = feedparser.parse(
                source["url"],
                agent="Mozilla/5.0 (compatible; AIDigestBot/1.0)",
                request_headers={"Accept": "application/rss+xml, application/xml, */*"},
            )
        except Exception as e:
            print(f"  [warn] feedparser error for {source['name']}: {e}")
            continue

        entries = feed.get("entries", [])
        print(f"  [{source['name']}] {len(entries)} entries in feed")

        in_window, fallback = [], []
        for entry in entries:
            title = (getattr(entry, "title", "") or "").strip()
            if not title:
                continue
            link = getattr(entry, "link", "") or ""
            summary = re.sub(r"<[^>]+>", "", getattr(entry, "summary", "") or "")[:300]
            pub_date = _parse_feed_entry_date(entry)

            # Filter for AI-related content on general feeds
            if source["name"] in ("Ars Technica", "The Verge", "9to5Google AI"):
                if not _is_ai_related(title, summary):
                    continue

            story = {
                "title": title,
                "url": link,
                "pub_date": pub_date,
                "summary": summary.strip(),
                "source": source["name"],
                "points": 10,
            }

            if pub_date and pub_date >= window_start:
                in_window.append(story)
            else:
                fallback.append(story)

        if in_window:
            stories.extend(in_window)
            print(f"  [{source['name']}] {len(in_window)} within window")
        elif fallback:
            # Take 3 most recent as fallback
            fallback_sorted = sorted(
                [s for s in fallback if s["pub_date"]],
                key=lambda x: x["pub_date"],
                reverse=True,
            )
            stories.extend(fallback_sorted[:3])
            newest = fallback_sorted[0]["pub_date"].strftime("%Y-%m-%d") if fallback_sorted else "?"
            print(f"  [{source['name']}] outside window (newest: {newest}), taking 3 as fallback")

        time.sleep(0.3)

    return stories


def fetch_hacker_news(window_start: datetime) -> list[dict]:
    """Fetch top AI stories from Hacker News Firebase API."""
    stories = []
    try:
        req = urllib.request.Request(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            headers={"User-Agent": "AIDigestBot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ids = json.loads(resp.read())[:60]  # Top 60 stories
    except Exception as e:
        print(f"  [warn] HN top stories failed: {e}")
        return stories

    for story_id in ids:
        try:
            req = urllib.request.Request(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                headers={"User-Agent": "AIDigestBot/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                item = json.loads(resp.read())
        except Exception:
            continue

        title = (item.get("title") or "").strip()
        if not title or not _is_ai_related(title):
            continue
        score = item.get("score", 0) or 0
        if score < 20:
            continue
        created = item.get("time", 0)
        pub_date = datetime.fromtimestamp(created, tz=timezone.utc) if created else None

        stories.append({
            "title": title,
            "url": item.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
            "pub_date": pub_date,
            "summary": "",
            "source": "Hacker News",
            "points": score,
        })

        if len(stories) >= 10:
            break
        time.sleep(0.1)

    print(f"  [Hacker News] {len(stories)} AI stories found")
    return stories


def fetch_news(dry_run: bool = False) -> list[dict]:
    """
    Fetch AI/tech news from the last 48h, deduplicated.
    Returns top 6 stories sorted by relevance.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=48)

    print(f"[news] Fetching from {window_start.strftime('%Y-%m-%d %H:%M')} UTC to now...")

    history = load_history()
    all_stories: list[dict] = []

    all_stories.extend(fetch_rss_stories(window_start))
    print("  Fetching Hacker News...")
    all_stories.extend(fetch_hacker_news(window_start))

    print(f"[news] {len(all_stories)} raw stories, deduplicating...")

    seen: set[str] = set()
    filtered = []
    for story in all_stories:
        h = _title_hash(story["title"])
        if h in seen:
            continue
        seen.add(h)
        if is_duplicate(story["title"], history):
            print(f"  [skip-dup] {story['title'][:60]}")
            continue
        filtered.append(story)

    filtered.sort(
        key=lambda s: (s.get("points", 5) * 1000 + (s["pub_date"].timestamp() if s.get("pub_date") else 0)),
        reverse=True,
    )

    print(f"[news] {len(filtered)} unique stories ready")

    if dry_run:
        for s in filtered[:6]:
            print(f"  [{s['source']}] {s['title'][:80]}")

    return filtered[:6]


if __name__ == "__main__":
    stories = fetch_news(dry_run=True)
    print(f"\nTop {len(stories)} stories.")
