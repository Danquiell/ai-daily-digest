"""
Main orchestrator for AI Daily Digest.
Run daily at 06:00 BRT (09:00 UTC) via GitHub Actions.

Usage:
  python src/main.py              # full run
  python src/main.py --dry-run   # fetch + generate + preview, no posting
"""
import argparse
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Make src importable when running as script
sys.path.insert(0, str(Path(__file__).parent))

from news_fetcher import fetch_news, load_history
from content_generator import generate_content
from image_generator import generate_card
from linkedin_poster import post_text, post_sources_comment
from instagram_poster import post_image
from history_updater import update_history, git_commit_history


def build_linkedin_post(content) -> str:
    """Combine PT and EN versions into the final LinkedIn post."""
    divider = "\n\n──────────────────\n\n"
    return f"{content.linkedin_pt}{divider}{content.linkedin_en}"


def build_sources_comment(stories: list[dict]) -> str:
    lines = ["🔗 Fontes de hoje / Today's sources:\n"]
    seen = set()
    for s in stories:
        url = s.get("url", "")
        if url and url not in seen:
            seen.add(url)
            lines.append(f"• {s['source']}: {url}")
    return "\n".join(lines[:8])  # Max 8 links


def run(dry_run: bool = False):
    today = date.today()
    yesterday = today - timedelta(days=1)
    date_str = str(yesterday)

    print(f"\n{'='*60}")
    print(f"  AI Daily Digest — {today.strftime('%d/%m/%Y')}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    # 1. Fetch news
    try:
        stories = fetch_news(dry_run=dry_run)
    except Exception as e:
        print(f"[FATAL] News fetch failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    if not stories:
        print("[WARN] No new stories found for today. Skipping post.")
        sys.exit(0)

    history = load_history()

    # 2. Generate content
    try:
        content = generate_content(stories, history, date_str, dry_run=dry_run)
    except Exception as e:
        print(f"[FATAL] Content generation failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    # 3. Generate Instagram card image
    try:
        main_story = stories[0]
        # Sub-headline: second story title or summary of main
        sub = stories[1]["title"] if len(stories) > 1 else main_story.get("summary", "")[:80]
        card_path = generate_card(
            headline=main_story["title"],
            sub_headline=sub,
            username="@daniel.rios",  # adjust to real username
            today=today,
            source=main_story["source"],
            output_filename=f"card_{today.isoformat()}.jpg",
        )
    except Exception as e:
        print(f"[ERROR] Image generation failed: {e}")
        traceback.print_exc()
        card_path = None

    # 4. Post to LinkedIn
    linkedin_post_id = None
    try:
        linkedin_text = build_linkedin_post(content)
        linkedin_post_id = post_text(
            linkedin_text,
            main_url=content.main_url,
            dry_run=dry_run,
        )
        sources_comment = build_sources_comment(stories)
        post_sources_comment(linkedin_post_id, sources_comment, dry_run=dry_run)
        print(f"[OK] LinkedIn post published")
    except Exception as e:
        print(f"[ERROR] LinkedIn post failed: {e}")
        traceback.print_exc()

    # 5. Post to Instagram
    instagram_ok = False
    if card_path and card_path.exists():
        try:
            post_image(
                card_path,
                content.instagram_caption_pt,
                content.instagram_comment_en,
                dry_run=dry_run,
            )
            instagram_ok = True
            print(f"[OK] Instagram post published")
        except Exception as e:
            print(f"[ERROR] Instagram post failed: {e}")
            traceback.print_exc()
    else:
        print("[WARN] Skipping Instagram — card image not available")

    # 6. Update history and commit
    if not dry_run:
        try:
            update_history(stories, date_str)
            git_commit_history(dry_run=False)
        except Exception as e:
            print(f"[ERROR] History update failed: {e}")
            traceback.print_exc()
    else:
        print("[history] DRY RUN — skipping history update")

    print(f"\n{'='*60}")
    print(f"  Summary:")
    print(f"  Stories found:   {len(stories)}")
    print(f"  LinkedIn:        {'OK' if linkedin_post_id else 'FAILED'}")
    print(f"  Instagram:       {'OK' if instagram_ok else 'FAILED/SKIPPED'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Daily Digest Poster")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and generate content without posting",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)
