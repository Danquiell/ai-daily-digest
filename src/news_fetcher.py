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
    # A second Google News query aimed at the events that make a day's news:
    # money, courts and regulators, not product notes.
    {
        "name": "Google News AI Deals",
        "url": "https://news.google.com/rss/search?q=AI+(acquisition+OR+lawsuit+OR+regulation+OR+funding+OR+antitrust+OR+ban)&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "9to5Google AI",
        "url": "https://9to5google.com/feed/",
    },
    # Techmeme is an editorial front page: what it leads with is what the
    # industry is arguing about that morning.
    {
        "name": "Techmeme",
        "url": "https://www.techmeme.com/feed.xml",
    },
    {
        "name": "Wired AI",
        "url": "https://www.wired.com/feed/tag/ai/latest/rss",
    },
    {
        "name": "r/artificial",
        "url": "https://www.reddit.com/r/artificial/top/.rss?t=day",
    },
    {
        "name": "r/LocalLLaMA",
        "url": "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day",
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


# Press-release syndication. These carry a dollar figure in every headline, so
# the money signal scores them like real deal news: a market-forecast release
# reached a published post as "the AI Personal Finance And Wealth Management
# Platform market is projected to cross $29.81 billion by 2030".
_WIRE_DOMAINS = (
    "einnews.com", "einpresswire.com", "prnewswire.com", "businesswire.com",
    "globenewswire.com", "openpr.com", "digitaljournal.com", "accesswire.com",
    "prweb.com", "newsfilecorp.com",
)
_WIRE_TITLE = re.compile(
    r"\b(market (size|share|report|research|outlook|analysis)|cagr|forecast to|"
    r"by 20[3-9]\d|industry report|market to (reach|grow|cross))\b",
    re.I,
)


def _is_press_release(title: str, url: str) -> bool:
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return any(d in host for d in _WIRE_DOMAINS) or bool(_WIRE_TITLE.search(title))


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
            if source["name"] in ("Ars Technica", "The Verge", "9to5Google AI", "Techmeme"):
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
    ids: list[int] = []
    # "best" ranks by score over a longer horizon and surfaces the story the
    # site actually argued about; "top" is the live front page. Both, deduped.
    for listing in ("beststories", "topstories"):
        try:
            req = urllib.request.Request(
                f"https://hacker-news.firebaseio.com/v0/{listing}.json",
                headers={"User-Agent": "AIDigestBot/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                ids.extend(json.loads(resp.read())[:80])
        except Exception as e:
            print(f"  [warn] HN {listing} failed: {e}")
    ids = list(dict.fromkeys(ids))
    if not ids:
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
        story_url = item.get("url") or f"https://news.ycombinator.com/item?id={story_id}"

        # HN has no article summary, and a story that reaches the model as a bare
        # title gives it nothing to write from. Its own metadata is real data:
        # score, comment count and the domain the link points at.
        domain = urllib.parse.urlparse(story_url).netloc.removeprefix("www.")
        comments = item.get("descendants", 0) or 0
        summary = f"Hacker News front page: {score} points, {comments} comments"
        if domain and "ycombinator" not in domain:
            summary += f", links to {domain}"
        text = re.sub(r"<[^>]+>", " ", item.get("text") or "").strip()
        if text:
            summary += f". Author's text: {text[:200]}"

        stories.append({
            "title": title,
            "url": story_url,
            "pub_date": pub_date,
            "summary": summary,
            "source": "Hacker News",
            "points": score,
            "comments": comments,
        })

        if len(stories) >= 18:
            break
        time.sleep(0.05)

    print(f"  [Hacker News] {len(stories)} AI stories found")
    return stories


# What makes a story the day's story. Tuned against 2026-09-03, when the digest
# led with a Mistral FAQ page that answers nothing and buried Nvidia buying
# Hugging Face for $12.93B in a single closing line.
_SIGNAL_WEIGHTS = [
    (70, {
        "acquire", "acquires", "acquired", "acquisition", "buys", "buyout",
        "merger", "billion", "billions", "raises", "raised", "funding", "ipo",
        "valuation", "stake", "invests", "investment", "bailout",
    }),
    (60, {
        "lawsuit", "sues", "sued", "suing", "court", "ruling", "rules", "judge",
        "ban", "banned", "bans", "regulation", "regulator", "antitrust", "fine",
        "fined", "investigation", "settlement", "injunction", "subpoena",
        "copyright", "illegal", "sanctions", "probe",
    }),
    (55, {
        "backlash", "controversy", "controversial", "criticized", "accused",
        "accuses", "leak", "leaked", "breach", "outage", "resigns", "resigned",
        "fired", "layoffs", "shuts", "shutdown", "scandal", "boycott", "quits",
        "apologizes", "retracts", "hoax", "fraud", "deceptive",
    }),
    (40, {
        "launches", "launch", "releases", "unveils", "announces", "debuts",
        "benchmark", "sota", "weights", "opensource", "outperforms", "beats",
        "record", "breakthrough", "deprecates", "discontinues",
    }),
    (25, {
        "openai", "anthropic", "google", "nvidia", "meta", "microsoft", "apple",
        "mistral", "deepmind", "xai", "amazon", "tesla", "claude", "gemini",
        "gpt", "llama", "chatgpt", "perplexity", "huggingface", "sora", "grok",
    }),
]

_MONEY = re.compile(r"[$€£]\s?\d|(\d+(\.\d+)?\s?(billion|bilh|million|milh|trillion))", re.I)


def _signal_score(story: dict, cluster_size: int) -> float:
    """Rank by how consequential a story is, not by how recently it appeared.

    Coverage breadth is the strongest signal available: the same story filed by
    four outlets is the day's news. Hacker News points and comments come next —
    comments weigh in on their own because an argument is what "polêmica" looks
    like in the data.
    """
    title = story.get("title", "")
    tokens = set(re.findall(r"[a-z0-9]+", title.lower()))

    score = 90.0 * (cluster_size - 1)
    score += min(story.get("points", 0) or 0, 1200) * 0.14
    score += min(story.get("comments", 0) or 0, 800) * 0.16

    for weight, words in _SIGNAL_WEIGHTS:
        if tokens & words:
            score += weight
    if _MONEY.search(title):
        score += 55

    # A question or a how-to is someone's blog post, not the day's news.
    if title.rstrip().endswith("?") or title.lower().startswith(("how ", "why ", "can i", "ask hn")):
        score -= 45

    pub = story.get("pub_date")
    if pub:
        hours_old = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
        score += max(0.0, 24.0 - hours_old)  # tiebreaker only
    return score


# Words two unrelated headlines share by accident. Excluded when counting how
# much substance two titles have in common.
_WEAK_TOKENS = {
    "new", "says", "said", "report", "reports", "reported", "launches", "launch",
    "announces", "announced", "update", "updates", "first", "more", "now",
    "using", "use", "after", "over", "into", "with", "how", "why", "his", "her",
    "their", "this", "that", "you", "your", "can", "all", "out", "about",
}


def _same_story(a: set, b: set) -> bool:
    """Two headlines about one event.

    Jaccard alone misses it: "Nvidia to acquire Hugging Face for $12.93B" and
    "Nvidia confirms Hugging Face acquisition at $12.93 billion" score 0.38,
    because each outlet words the rest of the sentence its own way. Overlap on
    the substantive tokens catches the pair; dropping the filler words keeps
    "OpenAI launches new model" and "OpenAI launches new API" apart.
    """
    if _jaccard(a, b) >= 0.45:
        return True
    shared = (a & b) - _WEAK_TOKENS
    smaller = min(len(a), len(b)) or 1
    return len(shared) >= 3 and len(a & b) / smaller >= 0.55


def _cluster_stories(stories: list[dict]) -> list[dict]:
    """Group the same story as filed by different outlets.

    The old pipeline threw near-duplicates away. Their number is the signal.
    """
    clusters: list[dict] = []
    for story in stories:
        tokens = _normalize(story["title"])
        for cluster in clusters:
            if any(_same_story(tokens, m_tokens) for m_tokens in cluster["member_tokens"]):
                cluster["members"].append(story)
                cluster["member_tokens"].append(tokens)
                break
        else:
            clusters.append({"member_tokens": [tokens], "members": [story]})
    return clusters


def _pick_representative(members: list[dict]) -> dict:
    """The member worth writing from: real publisher, longest summary."""
    def rank(s: dict) -> tuple:
        url = s.get("url", "")
        real_publisher = "news.google.com" not in url and "reddit.com" not in url
        return (real_publisher, len(s.get("summary", "")), s.get("points", 0))

    return max(members, key=rank)


_TAG_STRIP = re.compile(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def fetch_article_text(url: str, limit: int = 1400) -> str:
    """Download an article and return its visible text, or "" on any failure.

    A headline alone is not enough material: given only titles, the model either
    refuses to write or invents the details it is missing. Both happened on
    2026-09-01.
    """
    if not url or "news.ycombinator.com" in url:
        return ""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AIDigestBot/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype.lower():
                return ""
            raw = resp.read(400_000).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [article] {urllib.parse.urlparse(url).netloc}: {type(e).__name__}")
        return ""

    body = _TAG_STRIP.sub(" ", raw)
    # Paragraph text carries the article; everything else on the page is chrome.
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", body, re.S | re.I)
    text = " ".join(_WS.sub(" ", _TAGS.sub(" ", p)).strip() for p in paragraphs)
    text = _WS.sub(" ", text).strip()
    if len(text) < 200:
        return ""
    return text[:limit]


def enrich_with_article_text(stories: list[dict], count: int = 3) -> None:
    """Attach real article text to the stories the post will develop in depth."""
    for story in stories[:count]:
        text = fetch_article_text(story.get("url", ""))
        if text:
            story["article"] = text
            print(f"  [article] {len(text)} chars for: {story['title'][:60]}")
        time.sleep(0.2)


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
        if _is_press_release(story["title"], story.get("url", "")):
            continue
        if is_duplicate(story["title"], history):
            print(f"  [skip-dup] {story['title'][:60]}")
            continue
        filtered.append(story)

    clusters = _cluster_stories(filtered)
    ranked = []
    for cluster in clusters:
        story = _pick_representative(cluster["members"])
        story["cluster_size"] = len(cluster["members"])
        story["also_covered_by"] = sorted(
            {m["source"] for m in cluster["members"] if m["source"] != story["source"]}
        )
        story["score"] = _signal_score(story, story["cluster_size"])
        ranked.append(story)

    ranked.sort(key=lambda s: s["score"], reverse=True)
    print(f"[news] {len(filtered)} unique stories in {len(ranked)} clusters")

    selected = _select_balanced(ranked, limit=6, per_source=3)

    print("[news] Fetching article text for the lead stories...")
    enrich_with_article_text(selected, count=4)

    for i, s in enumerate(selected, 1):
        covered = f" +{len(s['also_covered_by'])} outlets" if s.get("also_covered_by") else ""
        print(f"  {i}. [{s['score']:.0f}{covered}] [{s['source']}] {s['title'][:70]}")

    return selected


def _stem(token: str) -> str:
    """Crude suffix strip, enough to match how two outlets word one event.

    "Mamdani bans AI in NYC schools" and "NYC Public Schools banning AI use
    through middle school" share nothing until bans/banning and schools/school
    collapse to the same token.
    """
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            stem = token[: -len(suffix)]
            # banning -> bann -> ban, so it meets bans -> ban.
            if len(stem) > 3 and stem[-1] == stem[-2] and stem[-1] not in "lsfz":
                stem = stem[:-1]
            return stem
    return token


_WEAK_STEMS = {_stem(t) for t in _WEAK_TOKENS} | {"artificial", "intelligence"}


def _content_stems(title: str) -> set[str]:
    return {_stem(t) for t in _normalize(title)} - _WEAK_STEMS


def _select_balanced(
    stories: list[dict],
    limit: int,
    per_source: int,
) -> list[dict]:
    """Pick the top stories with a cap per source and no repeated event.

    On 2026-09-01 the whole digest came from Hacker News, and every entry
    carried a bare title, so the model had no facts to write from and answered
    with a refusal instead of a post. A source cap keeps at least half the list
    coming from feeds that ship a summary.

    On 2026-09-03 the six slots held three actual stories: the NYC school AI ban
    arrived worded three different ways. Selection rejects a candidate sharing
    two content stems with one already picked — a looser bar than clustering,
    which is right here: a repeat in a six-item list costs more than a missed
    story, and the story below it is one line down the ranking.
    """
    picked: list[dict] = []
    picked_stems: list[set[str]] = []
    counts: dict[str, int] = {}
    for story in stories:
        source = story.get("source", "")
        if counts.get(source, 0) >= per_source:
            continue
        stems = _content_stems(story["title"])
        if any(len(stems & seen) >= 2 for seen in picked_stems):
            continue
        picked.append(story)
        picked_stems.append(stems)
        counts[source] = counts.get(source, 0) + 1
        if len(picked) >= limit:
            return picked

    # Caps left the list short: fill from what is left, best-ranked first.
    if len(picked) < limit:
        chosen = {id(s) for s in picked}
        picked.extend(s for s in stories if id(s) not in chosen)
    return picked[:limit]


if __name__ == "__main__":
    stories = fetch_news(dry_run=True)
    print(f"\nTop {len(stories)} stories.")
