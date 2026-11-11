"""
Main orchestrator for AI Daily Digest.
Triggered daily via GitHub Actions (see .github/workflows/daily_post.yml).
"""
import argparse
import json
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from news_fetcher import fetch_news, load_history
from content_generator import generate_content
from image_generator import generate_card
from linkedin_poster import (
    TokenExpired,
    check_token,
    post_document,
    post_multi_image,
    post_sources_comment,
    post_text,
    post_with_image,
)
from history_updater import update_history, git_commit_history, already_posted

LINKEDIN_USERNAME = "@danquiell"
OUTPUT_DIR = Path(__file__).parent.parent / "output"

# LinkedIn cuts a post at 3000 characters, without saying so.
LINKEDIN_MAX_CHARS = 3000


def build_caption(content) -> str:
    """English first, with no label above it: the first line of the post is the
    only thing the feed shows before "see more", and "[EN/US]" used to spend it.
    Portuguese follows under its own label. Hashtags are added by the poster.
    """
    en = content.linkedin_en.strip()
    pt = content.linkedin_pt.strip()
    parts = [en]
    if pt and pt != en:
        parts.append(f"[PT/BR]\n\n{pt}")
    parts.append("Sources in the first comment. / Fontes no primeiro comentário.")
    return "\n\n──────────────────\n\n".join(parts[:-1]) + "\n\n" + parts[-1]


def build_sources_comment(stories: list[dict]) -> str:
    lines = ["Sources / Fontes:\n"]
    seen = set()
    for s in stories:
        url = s.get("url", "")
        if url and url not in seen:
            seen.add(url)
            lines.append(f"• {s.get('outlet') or s['source']}: {url}")
    return "\n".join(lines[:8])


def run(dry_run: bool = False):
    today = date.today()
    yesterday = today - timedelta(days=1)
    date_str = str(yesterday)

    print(f"\n{'='*60}")
    print(f"  AI Daily Digest — {today.strftime('%d/%m/%Y')}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    if not dry_run and already_posted(date_str):
        print(f"[skip] history.json already has entry for {date_str} — exiting cleanly.")
        sys.exit(0)

    # 0. A dead token fails here, before the news fetch and the Claude call.
    if not dry_run:
        try:
            check_token()
        except TokenExpired as e:
            print(f"[FATAL] {e}")
            sys.exit(1)

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

    # 2. Generate caption and slide content
    try:
        content = generate_content(stories, history, date_str, dry_run=dry_run)
    except Exception as e:
        print(f"[FATAL] Content generation failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    caption = build_caption(content)
    full_text = f"{caption}\n\n{content.hashtags}".strip()
    if len(full_text) > LINKEDIN_MAX_CHARS:
        print(f"[WARN] Post is {len(full_text)} chars — LinkedIn cuts at {LINKEDIN_MAX_CHARS}")

    # The run log and the artifact are the only record of what went out: the
    # token cannot read a post back (403 for w_member_social).
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "caption.txt").write_text(full_text, encoding="utf-8")
    (OUTPUT_DIR / "deck.json").write_text(
        json.dumps(content.deck, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n--- POST TEXT ({len(full_text)} chars) ---")
    print(full_text)
    print("--- END POST TEXT ---\n")

    # 3. Render the carousel; keep the single card as the fallback image.
    carousel = None
    if content.deck.get("slides"):
        try:
            from carousel import render_carousel

            deck = dict(content.deck, username=LINKEDIN_USERNAME, outlets=sorted(content.sources))
            carousel = render_carousel(
                deck, today, stem=f"digest_{today.isoformat()}", image_query=content.image_query
            )
        except Exception as e:
            print(f"[ERROR] Carousel rendering failed: {e}")
            traceback.print_exc()
    else:
        print("[carousel] No slide survived the number check — using the single card")

    card_path = None
    if carousel is None:
        try:
            card_path = generate_card(
                headline=stories[0]["title"],
                stories=stories[:4],
                teaser=content.image_teaser,
                subtitle=content.image_subtitle,
                image_query=content.image_query,
                username=LINKEDIN_USERNAME,
                today=today,
                output_filename=f"card_{today.isoformat()}.jpg",
            )
        except Exception as e:
            print(f"[ERROR] Image generation failed: {e}")
            traceback.print_exc()

    # 4. Post to LinkedIn: carousel, then multi-image, then single image, then
    # text. Each step down is a format LinkedIn shows smaller, so the order is
    # by reach, and a failure in one never loses the day.
    linkedin_post_id = None
    post_format = "none"
    title = content.deck.get("headline") or stories[0]["title"]
    attempts = []
    if carousel:
        attempts.append(("carousel", lambda: post_document(caption, content.hashtags, carousel["pdf"], title)))
        attempts.append(("multi-image", lambda: post_multi_image(
            caption, content.hashtags, carousel["images"], content.alt_text or title)))
        attempts.append(("single image", lambda: post_with_image(
            text=full_text, image_path=carousel["images"][0], image_title=title[:100])))
    if card_path and card_path.exists():
        attempts.append(("single image", lambda: post_with_image(
            text=full_text, image_path=card_path, image_title=title[:100])))
    attempts.append(("text", lambda: post_text(full_text, main_url=content.main_url)))

    if dry_run:
        post_format = attempts[0][0]
        linkedin_post_id = "dry-run-urn"
        print(f"[linkedin] DRY RUN — would post as: {post_format}")
    else:
        for name, attempt in attempts:
            try:
                linkedin_post_id = attempt()
                post_format = name
                break
            except Exception as e:
                print(f"[ERROR] LinkedIn {name} post failed: {e}")

    if linkedin_post_id:
        post_sources_comment(linkedin_post_id, build_sources_comment(stories), dry_run=dry_run)
        print(f"[OK] LinkedIn post published as {post_format}")

    # 5. Update history and commit — only after the post actually went out.
    # Writing history on a failed post marks the day as done and makes every
    # later cron attempt skip it, so a token/API failure silently loses the day.
    if not dry_run:
        if linkedin_post_id:
            try:
                update_history(stories, date_str)
                git_commit_history(dry_run=False)
            except Exception as e:
                print(f"[ERROR] History update failed: {e}")
                traceback.print_exc()
        else:
            print("[history] Post failed — history NOT updated so the next run retries today")
    else:
        print("[history] DRY RUN — skipping history update")

    print(f"\n{'='*60}")
    print(f"  Stories found: {len(stories)}")
    print(f"  Carousel:      {'OK' if carousel else 'FAILED'}")
    print(f"  LinkedIn:      {post_format if linkedin_post_id else 'FAILED'}")
    print(f"{'='*60}\n")

    # Exit non-zero on a failed post so the Actions run turns red and GitHub
    # sends the failure e-mail. A green run that posted nothing hid an expired
    # LinkedIn token for 74 days.
    if not linkedin_post_id and not dry_run:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
