"""
Updates data/history.json with today's posted topics and commits back to the repo.
The commit uses [skip ci] to avoid triggering GitHub Actions again.
"""
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

HISTORY_PATH = Path(__file__).parent.parent / "data" / "history.json"
WINDOW_DAYS = 14
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "de", "da", "do", "das", "dos", "e", "o", "a", "os", "as", "um", "uma",
    "em", "no", "na", "nos", "nas", "que", "para", "por", "com",
}


def _normalize_tokens(title: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", title.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 2]


def _title_hash(title: str) -> str:
    return hashlib.sha256(title.lower().strip().encode()).hexdigest()


def update_history(stories: list[dict], date_str: str):
    """Append today's stories to history.json, pruning entries older than WINDOW_DAYS."""
    if HISTORY_PATH.exists():
        with open(HISTORY_PATH) as f:
            history = json.load(f)
    else:
        history = {"posts": []}

    # Prune old entries
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    history["posts"] = [
        p for p in history["posts"]
        if _parse_date(p.get("date", "")) >= cutoff
    ]

    topics = [s["title"] for s in stories]
    title_hashes = [_title_hash(t) for t in topics]
    topic_tokens = [_normalize_tokens(t) for t in topics]

    history["posts"].append(
        {
            "date": date_str,
            "topics": topics,
            "title_hashes": title_hashes,
            "topic_tokens": topic_tokens,
        }
    )

    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    print(f"[history] Updated history.json — {len(history['posts'])} entries in window")


def _parse_date(date_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def git_commit_history(dry_run: bool = False):
    """Commit the updated history.json back to the repo with [skip ci]."""
    repo_root = Path(__file__).parent.parent

    if dry_run:
        print("[history] DRY RUN — would commit history.json")
        return

    gh_token = os.environ.get("GH_TOKEN", "")
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "")

    # Configure git identity for GitHub Actions
    subprocess.run(
        ["git", "config", "user.email", "actions@github.com"],
        cwd=repo_root, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "AI Daily Bot"],
        cwd=repo_root, check=True, capture_output=True,
    )

    # Set remote with token for push
    if gh_token and gh_repo:
        remote_url = f"https://x-access-token:{gh_token}@github.com/{gh_repo}.git"
        subprocess.run(
            ["git", "remote", "set-url", "origin", remote_url],
            cwd=repo_root, check=True, capture_output=True,
        )

    subprocess.run(
        ["git", "add", "data/history.json"],
        cwd=repo_root, check=True, capture_output=True,
    )

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo_root, capture_output=True,
    )
    if result.returncode == 0:
        print("[history] No changes to commit")
        return

    subprocess.run(
        ["git", "commit", "-m", "chore: update post history [skip ci]"],
        cwd=repo_root, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "push"],
        cwd=repo_root, check=True, capture_output=True,
    )
    print("[history] history.json committed and pushed")
