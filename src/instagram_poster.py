"""
Posts to Instagram using the Meta Graph API.
Requires: INSTAGRAM_USER_ID, INSTAGRAM_ACCESS_TOKEN env vars.
Flow: upload image to imgbb (free) → create IG container → publish → add comment.
"""
import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

GRAPH_API = "https://graph.facebook.com/v19.0"


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"Graph API error {e.code}: {body}") from e


def _upload_image_imgbb(image_path: Path) -> str:
    """Upload image to imgbb.com (free, returns public URL for IG Graph API)."""
    api_key = os.environ.get("IMGBB_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "IMGBB_API_KEY must be set — get a free key at imgbb.com/api"
        )

    import base64
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    data = urllib.parse.urlencode({"key": api_key, "image": b64}).encode("utf-8")
    req = urllib.request.Request("https://api.imgbb.com/1/upload", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if not result.get("success"):
        raise RuntimeError(f"imgbb upload failed: {result}")

    url = result["data"]["url"]
    print(f"[instagram] Image uploaded to imgbb: {url}")
    return url


def _create_container(user_id: str, token: str, image_url: str, caption: str) -> str:
    """Step 1: Create a media container on Instagram."""
    url = f"{GRAPH_API}/{user_id}/media"
    fields = {
        "image_url": image_url,
        "caption": caption,
        "access_token": token,
    }
    result = _post_form(url, fields)
    container_id = result.get("id")
    if not container_id:
        raise RuntimeError(f"Failed to create IG container: {result}")
    print(f"[instagram] Container created: {container_id}")
    return container_id


def _wait_for_container(user_id: str, token: str, container_id: str, max_wait: int = 60):
    """Poll until the container is ready to publish."""
    url = (
        f"{GRAPH_API}/{container_id}"
        f"?fields=status_code&access_token={token}"
    )
    for _ in range(max_wait // 5):
        result = _get(url)
        status = result.get("status_code", "")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"IG container processing failed: {result}")
        time.sleep(5)
    raise TimeoutError("Instagram container processing timed out")


def _publish_container(user_id: str, token: str, container_id: str) -> str:
    """Step 2: Publish the container."""
    url = f"{GRAPH_API}/{user_id}/media_publish"
    fields = {
        "creation_id": container_id,
        "access_token": token,
    }
    result = _post_form(url, fields)
    media_id = result.get("id")
    if not media_id:
        raise RuntimeError(f"Failed to publish IG media: {result}")
    print(f"[instagram] Published media: {media_id}")
    return media_id


def _add_comment(media_id: str, token: str, comment_text: str):
    """Add the English version as the first comment."""
    url = f"{GRAPH_API}/{media_id}/comments"
    fields = {
        "message": comment_text,
        "access_token": token,
    }
    try:
        result = _post_form(url, fields)
        print(f"[instagram] Comment added: {result.get('id', '?')}")
    except Exception as e:
        print(f"[instagram] Warning: could not add comment: {e}")


def post_image(
    image_path: Path,
    caption_pt: str,
    comment_en: str,
    dry_run: bool = False,
) -> str:
    """
    Full Instagram post flow: upload image → create container → publish → comment.
    Returns the media ID.
    """
    user_id = os.environ.get("INSTAGRAM_USER_ID", "")
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")

    if not user_id or not token:
        raise EnvironmentError(
            "INSTAGRAM_USER_ID and INSTAGRAM_ACCESS_TOKEN must be set"
        )

    if dry_run:
        print(f"[instagram] DRY RUN — would post image: {image_path}")
        print(f"  Caption ({len(caption_pt)} chars): {caption_pt[:100]}...")
        print(f"  Comment: {comment_en[:80]}...")
        return "dry-run-media-id"

    print("[instagram] Uploading image...")
    image_url = _upload_image_imgbb(image_path)

    print("[instagram] Creating media container...")
    container_id = _create_container(user_id, token, image_url, caption_pt)

    print("[instagram] Waiting for processing...")
    _wait_for_container(user_id, token, container_id)

    print("[instagram] Publishing...")
    media_id = _publish_container(user_id, token, container_id)

    # Small delay before commenting to avoid race condition
    time.sleep(3)
    _add_comment(media_id, token, comment_en)

    return media_id


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    from pathlib import Path
    test_img = Path(__file__).parent.parent / "output" / "instagram_card.jpg"
    if test_img.exists():
        post_image(
            test_img,
            "🤖 Teste do AI Diário!\n\nIsso é um teste da integração.\n#ia #teste",
            "🇺🇸 This is a test post. #ai #test",
            dry_run=dry,
        )
    else:
        print(f"Test image not found at {test_img}. Run image_generator.py first.")
