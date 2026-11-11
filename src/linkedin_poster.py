"""
Posts to LinkedIn. Requires LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN.

Two API generations live here on purpose:
- the versioned REST API (/rest/posts, /rest/documents, /rest/images) publishes
  the carousel as a document post, or as a multi-image post;
- the legacy v2 API (/v2/ugcPosts) publishes the single-image post. It is the
  path that ran every day until the token expired, so it stays as the last
  fallback.
"""
import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

API_BASE = "https://api.linkedin.com/v2"
REST_BASE = "https://api.linkedin.com/rest"
# LinkedIn keeps a version alive for at least a year, then rejects it. When this
# one is sunset the REST calls fail and the post falls back to the single image:
# bump it to a current YYYYMM (learn.microsoft.com/linkedin/marketing/versioning).
LINKEDIN_VERSION = "202610"


class TokenExpired(RuntimeError):
    """The access token is rejected. Nothing downstream can work."""


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


def check_token() -> None:
    """Fail before any paid work when the token is dead.

    The token lasts 60 days and LinkedIn issues no refresh token to this kind
    of app. Until this check existed, an expired token was found only at the
    upload step, after the Claude call had already been paid for, six times a
    day.

    Registering an upload is the cheapest call the w_member_social scope is
    allowed to make; the registration is simply never used.
    """
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    person_urn = os.environ.get("LINKEDIN_PERSON_URN", "")
    if not token or not person_urn:
        raise EnvironmentError("LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN must be set")
    payload = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": person_urn,
            "serviceRelationships": [
                {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
            ],
        }
    }
    try:
        _post_json(f"{API_BASE}/assets?action=registerUpload", payload, token)
    except RuntimeError as e:
        if "401" in str(e):
            raise TokenExpired(
                "LinkedIn rejected the access token (expired or revoked). "
                "Renew it with: python scripts/linkedin_auth.py"
            ) from e
        # Anything else (rate limit, outage) is not proof the token is bad.
        print(f"[linkedin] Token check inconclusive: {e}")
        return
    print("[linkedin] Token accepted")


# ── Versioned REST API: document and multi-image posts ───────────────────────
_LITTLE_RESERVED = set('\\|{}@[]()<>#*_~')


def _escape_little(text: str) -> str:
    """Escape the characters LinkedIn's "little text format" reserves.

    /rest/posts reads commentary in that format: an unescaped parenthesis or
    underscore is parsed as markup and the post is cut at that character.
    """
    return "".join("\\" + ch if ch in _LITTLE_RESERVED else ch for ch in text)


def _commentary(text: str, hashtags: str) -> str:
    body = _escape_little(text)
    tags = " ".join("{hashtag|\\#|%s}" % t.lstrip("#") for t in hashtags.split() if t.strip("#"))
    return f"{body}\n\n{tags}" if tags else body


def _rest_request(method: str, url: str, token: str, payload: dict | None = None):
    """Returns (headers, parsed_body). Raises RuntimeError with the API's answer."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "Linkedin-Version": LINKEDIN_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            return resp.headers, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LinkedIn API error {e.code}: {e.read().decode('utf-8')}") from e


def _rest_upload(kind: str, path: Path, token: str, person_urn: str) -> str:
    """Upload a file through /rest/documents or /rest/images. Returns its URN."""
    _, result = _rest_request(
        "POST",
        f"{REST_BASE}/{kind}s?action=initializeUpload",
        token,
        {"initializeUploadRequest": {"owner": person_urn}},
    )
    value = result.get("value", {})
    upload_url, urn = value.get("uploadUrl", ""), value.get(kind, "")
    if not upload_url or not urn:
        raise RuntimeError(f"LinkedIn {kind} upload was not initialised: {result}")

    put = urllib.request.Request(
        upload_url,
        data=path.read_bytes(),
        method="PUT",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(put, timeout=120) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LinkedIn {kind} upload failed {e.code}: {e.read().decode('utf-8')}") from e
    print(f"[linkedin] Uploaded {path.name}: {urn}")
    return urn


def _rest_create_post(content: dict, text: str, hashtags: str, token: str, person_urn: str) -> str:
    payload = {
        "author": person_urn,
        "commentary": _commentary(text, hashtags),
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": content,
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    # A document is processed after upload; posting it a moment too early is
    # refused, and the same call succeeds seconds later.
    last = None
    for attempt in range(4):
        try:
            headers, _ = _rest_request("POST", f"{REST_BASE}/posts", token, payload)
            post_id = headers.get("x-restli-id", "")
            if not post_id:
                raise RuntimeError("LinkedIn accepted the post but returned no id")
            return post_id
        except RuntimeError as e:
            last = e
            head = str(e)[:30]
            # 401 and 403 are about the token and its scopes: waiting fixes neither.
            if " 4" not in head or " 401" in head or " 403" in head or attempt == 3:
                break
            print(f"[linkedin] Post not accepted yet ({str(e)[:120]}) — retrying in 8s")
            time.sleep(8)
    raise last


def post_document(text: str, hashtags: str, pdf_path: Path, title: str) -> str:
    """Publish the carousel: a PDF that LinkedIn shows as swipeable slides."""
    token = os.environ["LINKEDIN_ACCESS_TOKEN"]
    person_urn = os.environ["LINKEDIN_PERSON_URN"]
    document = _rest_upload("document", pdf_path, token, person_urn)
    post_id = _rest_create_post(
        {"media": {"title": title[:100], "id": document}}, text, hashtags, token, person_urn
    )
    print(f"[linkedin] Posted as document carousel: {post_id}")
    return post_id


def post_multi_image(text: str, hashtags: str, images: list[Path], alt_text: str) -> str:
    """Publish the slides as a multi-image post (2 to 20 images)."""
    token = os.environ["LINKEDIN_ACCESS_TOKEN"]
    person_urn = os.environ["LINKEDIN_PERSON_URN"]
    urns = [_rest_upload("image", p, token, person_urn) for p in images[:20]]
    content = {"multiImage": {"images": [{"id": u, "altText": alt_text[:300]} for u in urns]}}
    post_id = _rest_create_post(content, text, hashtags, token, person_urn)
    print(f"[linkedin] Posted as multi-image: {post_id}")
    return post_id


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


def get_post_text(post_urn: str) -> str:
    """Read back the commentary of a published post, so a post is inspected
    before it is deleted."""
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    if not token:
        raise EnvironmentError("LINKEDIN_ACCESS_TOKEN must be set")

    url = f"{API_BASE}/ugcPosts/{urllib.parse.quote(post_urn, safe='')}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"LinkedIn read failed {e.code}: {body}") from e

    return (
        data.get("specificContent", {})
        .get("com.linkedin.ugc.ShareContent", {})
        .get("shareCommentary", {})
        .get("text", "")
    )


def delete_post(post_urn: str, dry_run: bool = False):
    """Delete a published post. LinkedIn removes it from the feed immediately;
    it cannot be restored."""
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    if not token:
        raise EnvironmentError("LINKEDIN_ACCESS_TOKEN must be set")

    if dry_run:
        print(f"[linkedin] DRY RUN — would delete {post_urn}")
        return

    url = f"{API_BASE}/ugcPosts/{urllib.parse.quote(post_urn, safe='')}"
    req = urllib.request.Request(
        url,
        method="DELETE",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"LinkedIn delete failed {e.code}: {body}") from e

    print(f"[linkedin] Deleted {post_urn}")


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
