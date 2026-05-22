"""
Main orchestrator for AI Daily Digest.
Triggered daily via GitHub Actions (see .github/workflows/daily_post.yml).
"""
import argparse
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from news_fetcher import fetch_news, load_history
from content_generator import generate_content
from image_generator import generate_card
from linkedin_poster import post_with_image, post_text, post_sources_comment
from history_updater import update_history, git_commit_history

LINKEDIN_USERNAME = "@danquiell"


def build_linkedin_post(content) -> str:
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
    return "\n".join(lines[:8])


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
        print("[WARN] No new stories found. Skipping post.")
        sys.exit(0)

    history = load_history()

    # 2. Generate content
    try:
        content = generate_content(stories, history, date_str, dry_run=dry_run)
    except Exception as e:
        print(f"[FATAL] Content generation failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    # 3. Generate image card
    card_path = None
    try:
        card_path = generate_card(
            headline=stories[0]["title"],
            stories=stories[:4],
            username=LINKEDIN_USERNAME,
            today=today,
            output_filename=f"card_{today.isoformat()}.jpg",
        )
        print(f"[image] Card generated: {card_path.name}")
    except Exception as e:
        print(f"[ERROR] Image generation failed: {e}")
        traceback.print_exc()

    # 4. Post to LinkedIn
    linkedin_post_id = None
    try:
        linkedin_text = build_linkedin_post(content)

        if card_path and card_path.exists():
            linkedin_post_id = post_with_image(
                text=linkedin_text,
                image_path=card_path,
                image_title=stories[0]["title"][:100],
                dry_run=dry_run,
            )
        else:
            print("[linkedin] No image — falling back to text post")
            linkedin_post_id = post_text(
                linkedin_text,
                main_url=content.main_url,
                dry_run=dry_run,
            )

        sources_comment = build_sources_comment(stories)
        post_sources_comment(linkedin_post_id, sources_comment, dry_run=dry_run)
        print("[OK] LinkedIn post published")
    except Exception as e:
        print(f"[ERROR] LinkedIn post failed: {e}")
        traceback.print_exc()

    # 5. Update history and commit
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
    print(f"  Stories found: {len(stories)}")
    print(f"  Image card:    {'OK' if card_path and card_path.exists() else 'FAILED'}")
    print(f"  LinkedIn:      {'OK' if linkedin_post_id else 'FAILED'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
