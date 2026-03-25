import re
from urllib.parse import urlparse


# Regex pre-check: must start with http(s)://
_URL_RE = re.compile(
    r"^(https?://)?"                          # optional scheme
    r"(([a-zA-Z0-9\-]+\.)+[a-zA-Z]{2,})"     # domain
    r"(:\d+)?"                                # optional port
    r"(/[^\s]*)?"                             # optional path
    r"(\?[^\s]*)?"                            # optional query
    r"(#[^\s]*)?$",                           # optional fragment
    re.IGNORECASE,
)


def is_valid_meeting_url(url: str) -> bool:
    """
    Returns True when *url* looks like a valid meeting link.

    Checks performed
    ----------------
    1. Basic regex shape (has a real domain).
    2. urllib.parse structural check (scheme + netloc present).
    3. The scheme must be http or https.
    """
    url = url.strip()

    # Auto-prepend scheme so bare domains like "meet.google.com/abc-xyz" work
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if not _URL_RE.match(url):
        return False

    try:
        parsed = urlparse(url)
        return bool(parsed.scheme in {"http", "https"} and parsed.netloc)
    except Exception:
        return False


def normalise_url(url: str) -> str:
    """Return the URL with a scheme guaranteed."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url