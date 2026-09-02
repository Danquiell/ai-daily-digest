"""
Deletes a published LinkedIn post and runs the daily digest again for the same
date. Used when a post went out broken and has to be replaced.

Run from the workflow (the LinkedIn token lives in GitHub Secrets):
    python src/repost.py --urn urn:li:share:XXXX
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from history_updater import HISTORY_PATH
from linkedin_poster import delete_post, get_post_text
import main as digest


def drop_history_entry(date_str: str) -> bool:
    """Remove the entry for date_str so main.py stops skipping the day."""
    if not HISTORY_PATH.exists():
        return False
    with open(HISTORY_PATH) as f:
        history = json.load(f)
    before = len(history.get("posts", []))
    history["posts"] = [p for p in history["posts"] if p.get("date") != date_str]
    if len(history["posts"]) == before:
        print(f"[history] No entry for {date_str} — nothing to drop")
        return False
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"[history] Dropped the {date_str} entry so the day can be posted again")
    return True


def run(urn: str, dry_run: bool = False):
    date_str = str(date.today() - timedelta(days=1))

    print(f"\n[repost] Target post: {urn}")
    try:
        old_text = get_post_text(urn)
        print("[repost] Text of the post being deleted:")
        print("-" * 60)
        print(old_text)
        print("-" * 60)
    except Exception as e:
        print(f"[repost] Could not read the post before deleting: {e}")

    delete_post(urn, dry_run=dry_run)

    if not dry_run:
        drop_history_entry(date_str)

    digest.run(dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--urn", required=True, help="urn:li:share:... or urn:li:ugcPost:...")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.urn, dry_run=args.dry_run)
