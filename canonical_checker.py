"""
canonical_checker.py

Checks a page's canonical URL declaration:
    <link rel="canonical" href="...">

Works entirely from an already-parsed BeautifulSoup object - it does
not make any HTTP requests of its own.
"""

from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Only these URL schemes make sense for a canonical URL. Anything
# else (javascript:, data:, mailto:, ftp:, etc.) is not a usable
# canonical target.
ALLOWED_SCHEMES = ("http", "https")


def _resolve_and_validate(href: str, page_url: Optional[str]) -> Dict[str, Any]:
    """
    Resolve a single canonical href against the page's own URL and
    validate the result.

    Args:
        href (str): The raw, already-stripped href attribute value
            from a <link rel="canonical"> tag. Guaranteed non-empty
            by the caller.
        page_url (str | None): The URL of the page being checked,
            used to resolve a relative href into an absolute one.
            May be None/empty if unavailable.

    Returns:
        dict: {
            "url": str | None,   # The resolved absolute URL, or None if invalid
            "issue": str | None  # A description of what's wrong, or None if valid
        }
    """
    # urljoin() resolves relative hrefs ("/page", "../other") against
    # page_url into an absolute URL. If href is already absolute
    # (e.g. "https://example.com/page"), it's returned unchanged
    # regardless of page_url. If page_url is missing/empty, urljoin
    # falls back to using href as-is.
    resolved_url = urljoin(page_url or "", href)

    parsed = urlparse(resolved_url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return {
            "url": None,
            "issue": f"Canonical URL uses an invalid scheme: {resolved_url!r}",
        }

    if not parsed.netloc:
        # A scheme without a domain (rare, but possible with a
        # malformed href) isn't a usable canonical target either.
        return {
            "url": None,
            "issue": f"Canonical URL could not be resolved to a valid address: {resolved_url!r}",
        }

    return {"url": resolved_url, "issue": None}


def check_canonical(soup: Optional[BeautifulSoup], page_url: Optional[str]) -> Dict[str, Any]:
    """
    Check whether the page declares a valid canonical URL via
    <link rel="canonical" href="...">.

    Args:
        soup (BeautifulSoup | None): Parsed HTML of the page, as
            returned by crawler.get_page(). May be None if the page
            failed to load/parse.
        page_url (str | None): The URL of the page being checked.
            Used only to resolve a relative canonical href into an
            absolute URL - no network request is made with it.

    Returns:
        dict: {
            "found": bool,        # True if a usable canonical URL was found
            "url": str | None,    # The resolved absolute canonical URL, or None
            "issues": list[str]   # Any problems detected (empty if none)
        }
    """
    issues: List[str] = []

    # Guard clause: nothing to check without a parsed page.
    if soup is None:
        return {"found": False, "url": None, "issues": ["Canonical URL is missing."]}

    # Find every <link rel="canonical"> tag on the page. BeautifulSoup
    # treats "rel" as a multi-valued attribute internally, but
    # find_all() still matches correctly when given a plain string
    # like "canonical".
    canonical_tags = soup.find_all("link", rel="canonical")

    if not canonical_tags:
        return {"found": False, "url": None, "issues": ["Canonical URL is missing."]}

    if len(canonical_tags) > 1:
        issues.append(
            f"Multiple canonical tags found ({len(canonical_tags)}); "
            "a page should declare exactly one."
        )

    # Only the first canonical tag is treated as authoritative for
    # determining the resulting URL - browsers and search engines
    # generally only honor the first one anyway, and the multiplicity
    # itself is already flagged above as an issue.
    first_tag = canonical_tags[0]
    href = first_tag.get("href")
    href = href.strip() if href else ""

    if not href:
        issues.append("Canonical URL is missing.")
        return {"found": False, "url": None, "issues": issues}

    resolution = _resolve_and_validate(href, page_url)

    if resolution["issue"] is not None:
        issues.append(resolution["issue"])
        return {"found": False, "url": None, "issues": issues}

    return {"found": True, "url": resolution["url"], "issues": issues}


if __name__ == "__main__":
    # Quick manual tests using small inline HTML samples, so this
    # file can be run standalone without a network request.

    # Case 1: valid absolute canonical.
    html_valid = (
        '<html><head>'
        '<link rel="canonical" href="https://example.com/page">'
        '</head></html>'
    )
    soup1 = BeautifulSoup(html_valid, "html.parser")
    print(check_canonical(soup1, "https://example.com/page?utm_source=x"))

    # Case 2: relative canonical, resolved against page_url.
    html_relative = '<html><head><link rel="canonical" href="/page"></head></html>'
    soup2 = BeautifulSoup(html_relative, "html.parser")
    print(check_canonical(soup2, "https://example.com/some/other/page"))

    # Case 3: missing canonical tag entirely.
    html_missing = "<html><head><title>No canonical here</title></head></html>"
    soup3 = BeautifulSoup(html_missing, "html.parser")
    print(check_canonical(soup3, "https://example.com/page"))

    # Case 4: multiple canonical tags.
    html_multiple = (
        '<html><head>'
        '<link rel="canonical" href="https://example.com/a">'
        '<link rel="canonical" href="https://example.com/b">'
        '</head></html>'
    )
    soup4 = BeautifulSoup(html_multiple, "html.parser")
    print(check_canonical(soup4, "https://example.com/page"))

    # Case 5: invalid scheme.
    html_invalid_scheme = (
        '<html><head><link rel="canonical" href="javascript:alert(1)"></head></html>'
    )
    soup5 = BeautifulSoup(html_invalid_scheme, "html.parser")
    print(check_canonical(soup5, "https://example.com/page"))

    # Case 6: empty href.
    html_empty_href = '<html><head><link rel="canonical" href=""></head></html>'
    soup6 = BeautifulSoup(html_empty_href, "html.parser")
    print(check_canonical(soup6, "https://example.com/page"))

    # Case 7: soup is None.
    print(check_canonical(None, "https://example.com/page"))
