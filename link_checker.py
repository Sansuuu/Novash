"""
link_checker.py

Checks every link on a page to see whether it actually works, and
performs a purely HTML-based analysis of link composition (internal
vs external, anchor text quality, link types like mailto:/tel:/
javascript:, etc.) with no additional network requests.

Given the BeautifulSoup object Novash already has (from crawler.py),
this module finds all <a href="..."> links, resolves them to
absolute URLs, and checks each one - in parallel, using a thread
pool - to see if it responds successfully or is broken.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from requests.exceptions import (
    Timeout,
    ConnectionError,
    TooManyRedirects,
    InvalidURL,
    MissingSchema,
    RequestException,
)

try:
    # Only used for the type hint below. Guarded in a try/except so
    # this module never fails to import in an environment where bs4
    # isn't installed yet (matching the defensive style used
    # elsewhere in Novash's checkers, e.g. og_checker.py).
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = Any  # type: ignore

# Number of links checked in parallel. Link checks are I/O-bound
# (waiting on network responses), so a modest thread pool gives a
# big speedup over checking links one at a time without overwhelming
# the target sites with concurrent requests.
MAX_WORKERS = 20

# href prefixes that are never real web links and should be skipped
# entirely rather than being resolved/requested when building the
# list of links to actually check for broken/working status.
IGNORED_PREFIXES = ("#", "mailto:", "tel:", "javascript:", "data:")

# A realistic User-Agent avoids being blocked by sites that reject
# requests with no/blank User-Agent.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; NovashBot/1.0; "
        "+https://example.com/bot)"
    )
}

# Common "weak"/non-descriptive anchor text - phrases that tell a
# reader (or a screen reader user, or a search engine) nothing about
# where the link actually goes. This is a small, curated list of the
# most frequently seen offenders rather than an exhaustive one.
GENERIC_ANCHOR_TEXTS = frozenset({
    "click here",
    "here",
    "read more",
    "learn more",
    "more",
    "link",
    "click",
    "this link",
    "more info",
    "details",
})


def _extract_candidate_urls(soup, base_url):
    """
    Find every usable <a href="..."> link on the page and convert it
    into an absolute URL.

    Args:
        soup (BeautifulSoup): Parsed HTML of the page.
        base_url (str): The page's own URL, used to resolve any
            relative hrefs (e.g. "/about") into absolute URLs.

    Returns:
        list[str]: Unique, absolute http(s) URLs worth checking, in
        the order they were first seen on the page.
    """
    # dict.fromkeys() de-duplicates while preserving first-seen
    # order - simpler than a set + separate order-tracking list.
    seen = {}

    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href")

        # Skip empty/whitespace-only hrefs.
        if not href or not href.strip():
            continue

        href = href.strip()

        # Skip anchors, mailto:, tel:, javascript:, and data: links -
        # none of these are real pages to check.
        if href.lower().startswith(IGNORED_PREFIXES):
            continue

        # Resolve relative URLs ("/about", "../page.html") against
        # the page's own URL to get a full absolute URL. Already-
        # absolute URLs pass through urljoin() unchanged.
        absolute_url = urljoin(base_url, href)

        # Only check standard web links - skip anything that resolved
        # to a non-http(s) scheme (e.g. ftp:, an unrecognized custom
        # scheme, or a malformed URL with no scheme at all).
        parsed = urlparse(absolute_url)
        if parsed.scheme not in ("http", "https"):
            continue

        # Using the URL as a dict key automatically skips duplicates
        # (e.g. the same nav link appearing multiple times on a page).
        seen.setdefault(absolute_url, True)

    return list(seen.keys())


def _empty_analysis() -> Dict[str, Any]:
    """
    Build the zeroed-out analysis structure used when there's nothing
    to analyze at all (no soup, or no <a href> tags on the page), so
    every code path through check_links() returns the same, complete
    set of keys.
    """
    return {
        "total_links": 0,
        "internal_links": 0,
        "external_links": 0,
        "empty_href": 0,
        "hash_links": 0,
        "javascript_links": 0,
        "mailto_links": 0,
        "tel_links": 0,
        "relative_links": 0,
        "absolute_links": 0,
        "descriptive_text": 0,
        "empty_text": 0,
        "generic_text": 0,
        "generic_text_links": [],
        "empty_text_links": [],
    }


def _analyze_links(soup: "BeautifulSoup", base_url: Optional[str]) -> Dict[str, Any]:
    """
    Analyze every <a href="..."> tag on the page purely from the
    already-parsed HTML - no network requests are made here at all,
    unlike check_links()'s broken-link checking below.

    This looks at every link found (including ones that
    _extract_candidate_urls() deliberately skips, like mailto:/tel:/
    javascript:/# links), since the point here is to characterize the
    full composition of links on the page, not just the ones worth
    making a request to.

    Args:
        soup (BeautifulSoup): Parsed HTML of the page. Must not be
            None - callers should use _empty_analysis() directly in
            that case.
        base_url (str | None): The page's own URL, used to resolve
            relative hrefs and determine internal vs external links.
            If None/empty, internal/external classification is
            skipped for every link (there's nothing to compare
            against), but every other classification still runs.

    Returns:
        dict: See check_links()'s docstring for the full "analysis"
        key shape. Every count is an int; "generic_text_links" and
        "empty_text_links" are lists of {"href": str, "text": str}
        dicts identifying specifically which links have weak or
        missing anchor text, since those are the most actionable
        categories to review individually.
    """
    result = _empty_analysis()

    base_netloc = ""
    if base_url:
        base_netloc = urlparse(base_url).netloc.lower()

    for a_tag in soup.find_all("a", href=True):
        raw_href = a_tag.get("href") or ""
        href = raw_href.strip()
        text = a_tag.get_text(strip=True) or ""

        result["total_links"] += 1

        # --- Anchor text classification (independent of href type) ---
        if not text:
            result["empty_text"] += 1
            result["empty_text_links"].append({"href": raw_href, "text": text})
        elif text.lower() in GENERIC_ANCHOR_TEXTS:
            result["generic_text"] += 1
            result["generic_text_links"].append({"href": raw_href, "text": text})
        else:
            result["descriptive_text"] += 1

        # --- href-type classification (mutually exclusive categories) ---
        if not href:
            result["empty_href"] += 1
            continue

        lower_href = href.lower()

        if lower_href.startswith("#"):
            result["hash_links"] += 1
            continue

        if lower_href.startswith("javascript:"):
            result["javascript_links"] += 1
            continue

        if lower_href.startswith("mailto:"):
            result["mailto_links"] += 1
            continue

        if lower_href.startswith("tel:"):
            result["tel_links"] += 1
            continue

        # Whatever's left is a "real" web link candidate (or at least
        # not one of the special cases above) - classify it as
        # relative/absolute and, if possible, internal/external.
        parsed_href = urlparse(href)
        is_absolute = bool(parsed_href.scheme) or href.startswith("//")

        if is_absolute:
            result["absolute_links"] += 1
        else:
            result["relative_links"] += 1

        if base_url:
            resolved_url = urljoin(base_url, href)
            resolved_netloc = urlparse(resolved_url).netloc.lower()

            if resolved_netloc and base_netloc:
                if resolved_netloc == base_netloc:
                    result["internal_links"] += 1
                else:
                    result["external_links"] += 1
            # If either netloc couldn't be determined (a genuinely
            # malformed URL), this link is simply left out of the
            # internal/external counts rather than guessed at.

    return result


def _check_single_link(url, timeout):
    """
    Make a request to a single URL and classify it as working or
    broken.

    Args:
        url (str): The absolute URL to check.
        timeout (int | float): Max seconds to wait for a response.

    Returns:
        dict: {
            "url": str,
            "status_code": int | None,
            "status": "working" | "broken"
        }
        status_code is None only when no response was received at
        all (timeout, connection failure, etc.) - the link is still
        reported as "broken" in that case.
    """
    try:
        # allow_redirects=True (the default) means requests follows
        # redirects automatically and reports the FINAL response's
        # status code - e.g. a 301 that lands on a working page ends
        # up reported as working (200), which is the useful, real-
        # world answer for "is this link still good".
        response = requests.get(
            url, headers=HEADERS, timeout=timeout, allow_redirects=True
        )
        status_code = response.status_code

    except (Timeout, ConnectionError, InvalidURL, MissingSchema, TooManyRedirects):
        # Any of these mean we simply couldn't reach the link at
        # all - no status code to report.
        return {"url": url, "status_code": None, "status": "broken"}

    except RequestException:
        # Catch-all for any other requests-related error, so one bad
        # link can never crash the overall check.
        return {"url": url, "status_code": None, "status": "broken"}

    # 200-399 counts as working (includes redirects that were
    # already followed above, and other non-error 2xx/3xx codes).
    # 400+ counts as broken (client errors, server errors).
    status = "working" if 200 <= status_code < 400 else "broken"

    return {"url": url, "status_code": status_code, "status": status}


def check_links(soup, base_url, timeout=5):
    """
    Check every link on a page: which ones work (via live requests),
    and how the page's links are composed overall (via pure HTML
    analysis - no extra requests).

    Links are checked concurrently using a thread pool (up to
    MAX_WORKERS at a time), which is significantly faster than
    checking them one at a time - especially on pages with many
    links, since most of the work is simply waiting on network
    responses. A single failing/hanging link can never block or
    stop the others, since each check runs independently and errors
    are contained to that link's own result.

    Args:
        soup (BeautifulSoup | None): Parsed HTML of the page, as
            returned by crawler.get_page(). May be None if the page
            failed to load/parse.
        base_url (str): The page's own URL, used to resolve relative
            links into absolute URLs before checking them, and to
            determine which links are internal vs external.
        timeout (int | float): Max seconds to wait for each link's
            response before considering it broken (default: 5).

    Returns:
        dict: {
            "total": int,     # Number of unique, checkable http(s)
                               # links (excludes #, mailto:, tel:,
                               # javascript:, data:, and duplicates) -
                               # UNCHANGED from the original behavior;
                               # this is what drives the working/
                               # broken counts below.
            "working": int,   # Number that responded with 200-399
            "broken": int,    # Number that failed or responded 400+
            "links": list[dict],  # Per-link detail, see _check_single_link()
            "analysis": {
                # Pure HTML-based composition analysis - NO network
                # requests are made for any of this. Every <a href>
                # tag on the page is considered here, including ones
                # "total"/"links" above deliberately exclude (#,
                # mailto:, tel:, javascript:), since the point is to
                # characterize the page's link composition as a
                # whole, not just the checkable ones.
                "total_links": int,       # every <a> tag with an href attribute present
                "internal_links": int,    # same domain as base_url
                "external_links": int,    # different domain than base_url
                "empty_href": int,        # href="" or whitespace-only
                "hash_links": int,        # href starts with "#"
                "javascript_links": int,  # href starts with "javascript:"
                "mailto_links": int,      # href starts with "mailto:"
                "tel_links": int,         # href starts with "tel:"
                "relative_links": int,    # e.g. "/about", "../page.html"
                "absolute_links": int,    # e.g. "https://example.com/page"
                "descriptive_text": int,  # anchor text present and not generic
                "empty_text": int,        # no anchor text at all
                "generic_text": int,      # anchor text like "click here", "read more"
                "generic_text_links": list[dict],  # [{"href": str, "text": str}, ...]
                "empty_text_links": list[dict],    # [{"href": str, "text": str}, ...]
            }
        }
        "total"/"working"/"broken"/"links" preserve the exact shape
        and meaning this function has always returned, so existing
        callers (cli.py, score.py) keep working unchanged. "analysis"
        is purely additive.
    """
    # Guard clause: nothing to check without a parsed page. Every
    # return path includes the same complete set of top-level keys
    # (including "analysis"), so callers never need to guard against
    # a key being absent depending on which branch produced the
    # result.
    if soup is None:
        return {"total": 0, "working": 0, "broken": 0, "links": [], "analysis": _empty_analysis()}

    if not isinstance(base_url, str) or not base_url.strip():
        return {"total": 0, "working": 0, "broken": 0, "links": [], "analysis": _empty_analysis()}

    base_url = base_url.strip()

    # --- Pure HTML analysis (no network requests) ---
    try:
        analysis = _analyze_links(soup, base_url)
    except (TypeError, AttributeError):
        # Something other than a real BeautifulSoup object was passed
        # in (e.g. a plain string) - treat the same as "nothing to
        # analyze" rather than crashing the caller.
        analysis = _empty_analysis()

    # Gather every unique, checkable absolute URL on the page.
    try:
        urls = _extract_candidate_urls(soup, base_url)
    except (TypeError, AttributeError):
        # Something other than a real BeautifulSoup object was passed
        # in - already handled gracefully above for the analysis, and
        # handled the same way here so this can never crash the
        # caller either.
        return {"total": 0, "working": 0, "broken": 0, "links": [], "analysis": analysis}

    # Nothing to check - skip spinning up a thread pool entirely.
    if not urls:
        return {"total": 0, "working": 0, "broken": 0, "links": [], "analysis": analysis}

    # Check all links in parallel using a thread pool. Link checking
    # is I/O-bound (mostly waiting on network responses), which is
    # exactly the kind of work threads are good at speeding up in
    # Python, even with the GIL.
    #
    # Pre-size `links` to match `urls` and fill it in by index (via
    # the future -> index mapping below) rather than appending as
    # results arrive, so the output order matches the order links
    # were found on the page - completion order from as_completed()
    # would otherwise scramble it.
    links = [None] * len(urls)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit every link check up front and remember which future
        # corresponds to which URL/position.
        future_to_index = {
            executor.submit(_check_single_link, url, timeout): index
            for index, url in enumerate(urls)
        }

        # as_completed() yields futures as they finish, regardless of
        # submission order, so slow/hanging links don't block faster
        # ones from being processed first.
        for future in as_completed(future_to_index):
            index = future_to_index[future]

            try:
                links[index] = future.result()
            except Exception as e:
                # _check_single_link() already catches all the
                # requests-related errors it expects and never raises
                # on its own - but this is a final safety net so that
                # even a completely unexpected error in one thread
                # can't stop the rest of the links from being
                # reported. The failing link is simply recorded as
                # broken instead.
                links[index] = {
                    "url": urls[index],
                    "status_code": None,
                    "status": "broken",
                }

    working_count = sum(1 for link in links if link["status"] == "working")
    broken_count = sum(1 for link in links if link["status"] == "broken")

    return {
        "total": len(links),
        "working": working_count,
        "broken": broken_count,
        "links": links,
        "analysis": analysis,
    }


if __name__ == "__main__":
    # Quick manual test against a real page.
    from crawler import get_page
    import json

    test_url = "https://pypi.org"
    soup = get_page(test_url)
    result = check_links(soup, test_url, timeout=5)

    print(f"Total (checkable): {result['total']}")
    print(f"Working: {result['working']}")
    print(f"Broken: {result['broken']}")
    for link in result["links"][:5]:
        print(link)
    print()
    print("Analysis:")
    print(json.dumps(result["analysis"], indent=2))
