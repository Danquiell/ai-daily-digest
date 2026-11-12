"""
Finds a real, licensed photo of the subject of a story on Wikimedia Commons.

Stock photos illustrate a mood ("boardroom"); these show the actual person,
company or product the story is about. Only files Commons marks as freely
licensed are used, and the author and licence are returned so the image and
the sources comment can credit them, which most of these licences require.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO

from PIL import Image

_UA = {"User-Agent": "AIDigestBot/1.0 (daily news digest)"}
_WIKI = "https://en.wikipedia.org/w/api.php"
_COMMONS = "https://commons.wikimedia.org/w/api.php"
_FREE = re.compile(r"^(cc[ -]?(by|0|zero)|public domain|pd\b|attribution|gfdl|fal\b)", re.I)
# A logo or a diagram is a real file about the subject, but not a photo.
_NOT_A_PHOTO = re.compile(r"logo|wordmark|icon|signature|diagram|chart|map|screenshot|\.svg", re.I)
MIN_WIDTH = 900


def _get(url: str, params: dict) -> dict:
    """Wikimedia answers 429 to bursts, so every call is spaced and retried."""
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=_UA)
    for wait in (1, 4, 10):
        time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
    raise RuntimeError("Wikimedia rate limit (429) after three tries")


def _clean(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"\s+", " ", text).strip()


def _file_info(titles: list[str]) -> list[dict]:
    """Licence, author and a 1600px rendition for Commons files, in the order given."""
    if not titles:
        return []
    data = _get(_COMMONS, {
        "action": "query", "format": "json", "titles": "|".join(titles[:20]),
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1600,
    })
    by_title = {}
    for page in data.get("query", {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        by_title[page.get("title", "")] = {
            "title": page.get("title", ""),
            "url": info.get("thumburl") or info.get("url", ""),
            "width": info.get("width", 0),
            "height": info.get("height", 0),
            "mime": info.get("mime", ""),
            "license": _clean(meta.get("LicenseShortName", {}).get("value", "")),
            "author": _clean(meta.get("Artist", {}).get("value", ""))[:32],
            "page": info.get("descriptionurl", ""),
        }
    normalized = {n["from"]: n["to"] for n in data.get("query", {}).get("normalized", [])}
    return [by_title[normalized.get(t, t)] for t in titles if normalized.get(t, t) in by_title]


def _usable(f: dict) -> bool:
    return (
        # JPEG only: on Commons a PNG about a company is almost always a logo,
        # a figure from a paper or a screenshot.
        f["mime"] == "image/jpeg"
        and f["width"] >= MIN_WIDTH
        and f["height"] >= 600
        and bool(_FREE.match(f["license"]))
        and not _NOT_A_PHOTO.search(f["title"])
        and bool(f["url"])
    )


def _candidates(subject: str) -> list[str]:
    """File titles for a subject: the lead image of its Wikipedia article first
    (the one editors picked to represent it), then a Commons search."""
    titles: list[str] = []
    try:
        data = _get(_WIKI, {
            "action": "query", "format": "json", "generator": "search", "gsrsearch": subject,
            "gsrlimit": 1, "prop": "pageimages", "piprop": "name", "redirects": 1,
        })
        for page in data.get("query", {}).get("pages", {}).values():
            if page.get("pageimage"):
                titles.append("File:" + page["pageimage"].replace("_", " "))
    except Exception as e:
        print(f"[photo] Wikipedia lookup failed for {subject!r}: {type(e).__name__}")
    try:
        data = _get(_COMMONS, {
            "action": "query", "format": "json", "list": "search", "srnamespace": 6,
            "srsearch": f"{subject} filetype:bitmap", "srlimit": 12,
        })
        titles += [hit["title"] for hit in data.get("query", {}).get("search", [])]
    except Exception as e:
        print(f"[photo] Commons search failed for {subject!r}: {type(e).__name__}")
    seen, unique = set(), []
    for t in titles:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def find_photo(subjects: list[str], used: set[str] | None = None) -> dict | None:
    """First usable photo for the subjects, tried in order.

    Returns {"image": PIL.Image, "credit": str, "page": str, "subject": str} or
    None. `used` holds file titles already taken by another image of the same
    post, so two images never show the same photo.
    """
    used = used if used is not None else set()
    for subject in [s.strip() for s in subjects if s and s.strip()]:
        try:
            files = [f for f in _file_info(_candidates(subject)) if _usable(f) and f["title"] not in used]
        except Exception as e:
            print(f"[photo] Lookup failed for {subject!r}: {type(e).__name__}: {e}")
            continue
        for f in files[:3]:
            try:
                req = urllib.request.Request(f["url"], headers=_UA)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    image = Image.open(BytesIO(resp.read())).convert("RGB")
            except Exception as e:
                print(f"[photo] Download failed for {f['title']}: {type(e).__name__}")
                continue
            used.add(f["title"])
            author = f["author"] or "Wikimedia Commons"
            # The licences require saying the work was changed, not only who made it.
            credit = f"Photo: {author} / {f['license']}, Wikimedia Commons (cropped, text added)"
            print(f"[photo] {subject!r} → {f['title']} ({f['license']})")
            return {"image": image, "credit": credit, "page": f["page"], "subject": subject}
        print(f"[photo] No freely licensed photo found for {subject!r}")
    return None


if __name__ == "__main__":
    import sys

    for q in sys.argv[1:]:
        hit = find_photo([q])
        print(q, "→", hit and (hit["credit"], hit["image"].size, hit["page"]))
