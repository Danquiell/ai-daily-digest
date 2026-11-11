"""
Renews the LinkedIn access token and stores it in the repository secrets.

The token lasts 60 days and LinkedIn gives no refresh token to a self-serve
app, so this has to be run by hand about every two months. The daily workflow
opens an issue a week before the date this script records.

Two ways to run it, from the repository root:

  python scripts/linkedin_auth.py --paste
      Paste a token created at
      https://www.linkedin.com/developers/tools/oauth/token-generator
      (select the app, tick w_member_social, openid and profile).

  python scripts/linkedin_auth.py
      Full browser flow. Needs LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in
      the environment (or typed when asked) and http://localhost:8765/callback
      listed under "Authorized redirect URLs" in the app's Auth tab.

Both end by calling `gh secret set`, so the GitHub CLI must be logged in.
"""
import argparse
import getpass
import http.server
import json
import os
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser
from datetime import date, timedelta

REDIRECT = "http://localhost:8765/callback"
SCOPES = "openid profile w_member_social"
DEFAULT_LIFETIME_DAYS = 60


def _gh(*args: str, stdin: str | None = None) -> None:
    subprocess.run(["gh", *args], input=stdin, text=True, check=True)


def _person_urn(token: str) -> str:
    """The member id behind the token, or "" when the token lacks the profile scope."""
    req = urllib.request.Request(
        "https://api.linkedin.com/v2/userinfo", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            sub = json.loads(resp.read()).get("sub", "")
    except Exception as e:
        print(f"Could not read the profile ({e}); LINKEDIN_PERSON_URN is left as it is.")
        return ""
    return f"urn:li:person:{sub}" if sub else ""


def _browser_flow() -> tuple[str, int]:
    client_id = os.environ.get("LINKEDIN_CLIENT_ID") or input("Client ID: ").strip()
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET") or getpass.getpass("Client Secret: ").strip()
    state = secrets.token_urlsafe(16)
    received: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            received.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Done. You can close this tab and go back to the terminal.".encode())

        def log_message(self, *args):
            pass

    url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(
        {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
         "state": state, "scope": SCOPES}
    )
    server = http.server.HTTPServer(("localhost", 8765), Handler)
    print(f"Opening the browser. If it does not open, visit:\n{url}\n")
    webbrowser.open(url)
    while "code" not in received and "error" not in received:
        server.handle_request()
    server.server_close()

    if received.get("error"):
        sys.exit(f"LinkedIn refused: {received['error']} — {received.get('error_description', '')}")
    if received.get("state") != state:
        sys.exit("State mismatch: the answer did not come from the request this script made.")

    data = urllib.parse.urlencode(
        {"grant_type": "authorization_code", "code": received["code"], "redirect_uri": REDIRECT,
         "client_id": client_id, "client_secret": client_secret}
    ).encode()
    with urllib.request.urlopen(
        urllib.request.Request("https://www.linkedin.com/oauth/v2/accessToken", data=data), timeout=30
    ) as resp:
        answer = json.loads(resp.read())
    return answer["access_token"], int(answer.get("expires_in", DEFAULT_LIFETIME_DAYS * 86400)) // 86400


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--paste", action="store_true", help="paste a token from LinkedIn's token generator")
    args = parser.parse_args()

    if args.paste:
        token = getpass.getpass("Access token (hidden): ").strip()
        days = DEFAULT_LIFETIME_DAYS
    else:
        token, days = _browser_flow()
    if not token:
        sys.exit("No token given.")

    expires = date.today() + timedelta(days=days)
    _gh("secret", "set", "LINKEDIN_ACCESS_TOKEN", stdin=token)
    _gh("variable", "set", "LINKEDIN_TOKEN_EXPIRES_AT", "--body", expires.isoformat())
    urn = _person_urn(token)
    if urn:
        _gh("secret", "set", "LINKEDIN_PERSON_URN", stdin=urn)
    print(f"\nToken stored. It expires around {expires.isoformat()} ({days} days).")
    print("Test without posting:  gh workflow run daily_post.yml -f dry_run=true")


if __name__ == "__main__":
    main()
