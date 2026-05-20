"""
Posts to LinkedIn using the LinkedIn API v2 (UGC Posts endpoint).
Supports text-only posts and image posts (registers upload, uploads binary, posts).
Requires: LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN env vars.
"""
import json
import os
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

API_BASE = "https://api.linkedin.com/v2"


def _post_json(url: str, payload: dict, token: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"LinkedIn API error {e.code}: {body}") from e


def _upload_image(image_path: Path, token: str, person_urn: str) -> str:
    """
    Upload an image to LinkedIn and return the asset URN.
    Flow: register upload → PUT binary → return asset URN.
    """
    # Step 1: Register upload
    register_payload = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": person_urn,
            "serviceRelationships": [
                {
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent",
                }
            ],
        }
    }
    result = _post_json(f"{API_BASE}/assets?action=registerUpload", register_payload, token)

    upload_url = (
        result.get("value", {})
        .get("uploadMechanism", {})
        .get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {})
        .get("uploadUrl", "")
    )
    asset_urn = result.get("value", {}).get("asset", "")

    if not upload_url or not asset_urn:
        raise RuntimeError(f"Failed to register LinkedIn image upload: {result}")

    # Step 2: Upload binary
    with open(image_path, "rb") as f:
        image_data = f.read()

    put_req = urllib.request.Request(
        upload_url,
        data=image_data,
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "image/jpeg",
        },
    )
    try:
        with urllib.request.urlopen(put_req) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"LinkedIn image upload failed {e.code}: {body}") from e

    print(f"[linkedin] Image uploaded: {asset_urn}")
    return asset_urn


def post_with_image(
    text: str,
    image_path: Path,
    image_title: str = "AI Daily Digest",
    dry_run: bool = False,
) -> str:
    """Post to LinkedIn with an image attachment."""
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    person_urn = os.environ.get("LINKEDIN_PERSON_URN", "")

    if not token or not person_urn:
        raise EnvironmentError("LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN must be set")

    if dry_run:
        print(f"[linkedin] DRY RUN — would post with image: {image_path.name} ({len(text)} chars)")
        print(f"  Preview: {text[:200]}")
        return "dry-run-urn"

    print("[linkedin] Uploading image...")
    asset_urn = _upload_image(image_path, token, person_urn)

    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "IMAGE",
                "media": [
                    {
                        "status": "READY",
                        "description": {"text": image_title},
                        "media": asset_urn,
                        "title": {"text": image_title},
                    }
                ],
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
        },
    }

    result = _post_json(f"{API_BASE}/ugcPosts", payload, token)
    post_id = result.get("id", "unknown")
    print(f"[linkedin] Posted with image: {post_id}")
    return post_id


def post_text(text: str, main_url: str = "", dry_run: bool = False) -> str:
    """Post text-only (with optional link preview) — fallback when no image."""
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    person_urn = os.environ.get("LINKEDIN_PERSON_URN", "")

    if not token or not person_urn:
        raise EnvironmentError("LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN must be set")

    if dry_run:
        print(f"[linkedin] DRY RUN — would post text {len(text)} chars")
        print(f"  Preview: {text[:200]}")
        return "dry-run-urn"

    payload: dict = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
        },
    }

    if main_url:
        payload["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] = "ARTICLE"
        payload["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [
            {"status": "READY", "originalUrl": main_url}
        ]

    result = _post_json(f"{API_BASE}/ugcPosts", payload, token)
    post_id = result.get("id", "unknown")
    print(f"[linkedin] Posted: {post_id}")
    return post_id


def post_sources_comment(post_urn: str, sources_text: str, dry_run: bool = False):
    """Add first comment with source links."""
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    person_urn = os.environ.get("LINKEDIN_PERSON_URN", "")

    if dry_run:
        print("[linkedin] DRY RUN — would add sources comment")
        return

    if not post_urn or post_urn == "dry-run-urn":
        return

    encoded_urn = urllib.parse.quote(post_urn, safe="")
    url = f"{API_BASE}/socialActions/{encoded_urn}/comments"
    payload = {"actor": person_urn, "message": {"text": sources_text}}

    try:
        _post_json(url, payload, token)
        print("[linkedin] Sources comment added")
    except Exception as e:
        print(f"[linkedin] Warning: could not add sources comment: {e}")
