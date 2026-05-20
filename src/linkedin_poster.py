"""
Posts to LinkedIn using the LinkedIn API v2 (UGC Posts endpoint).
Requires: LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN env vars.
"""
import json
import os
import urllib.request
import urllib.error
import urllib.parse

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


def post_text(text: str, main_url: str = "", dry_run: bool = False) -> str:
    """
    Post a text update (with optional link preview) to LinkedIn.
    Returns the post URN on success.
    """
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    person_urn = os.environ.get("LINKEDIN_PERSON_URN", "")

    if not token or not person_urn:
        raise EnvironmentError(
            "LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN must be set"
        )

    if dry_run:
        print(f"[linkedin] DRY RUN — would post {len(text)} chars")
        print(f"  First 200 chars: {text[:200]}")
        return "dry-run-urn"

    payload: dict = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text,
                },
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
        },
    }

    # Add link article if URL provided
    if main_url:
        payload["specificContent"]["com.linkedin.ugc.ShareContent"][
            "shareMediaCategory"
        ] = "ARTICLE"
        payload["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [
            {
                "status": "READY",
                "originalUrl": main_url,
            }
        ]

    result = _post_json(f"{API_BASE}/ugcPosts", payload, token)
    post_id = result.get("id", "unknown")
    print(f"[linkedin] Posted successfully: {post_id}")
    return post_id


def post_sources_comment(post_urn: str, sources_text: str, dry_run: bool = False):
    """Add a comment to the LinkedIn post with source links."""
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    person_urn = os.environ.get("LINKEDIN_PERSON_URN", "")

    if dry_run:
        print(f"[linkedin] DRY RUN — would add comment with sources")
        return

    if not post_urn or post_urn == "dry-run-urn":
        return

    # Encode the post URN for the comments endpoint
    encoded_urn = urllib.parse.quote(post_urn, safe="")
    url = f"{API_BASE}/socialActions/{encoded_urn}/comments"

    payload = {
        "actor": person_urn,
        "message": {
            "text": sources_text,
        },
    }

    try:
        _post_json(url, payload, token)
        print("[linkedin] Source comment added")
    except Exception as e:
        print(f"[linkedin] Warning: could not add source comment: {e}")


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    post_text(
        "🇧🇷 Teste de post do AI Diário!\n\nIsso é um teste da integração com LinkedIn.\n\n#IA #Tecnologia",
        dry_run=dry,
    )
