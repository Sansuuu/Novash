"""
robots_checker.py

Checks whether a website has a robots.txt file at its root, and
analyzes its contents: user-agent rule groups, Disallow/Allow
directives, declared Sitemap URLs, a dangerous site-wide block
(User-agent: * / Disallow: /), and malformed or suspicious lines.

No network requests are made to any URL found *inside* robots.txt
(e.g. declared Sitemap URLs) - only the robots.txt file itself is
fetched, exactly as before.
"""

from urllib.parse import urlparse, urlunparse

import requests
from requests.exceptions import (
    Timeout,
    ConnectionError,
    InvalidURL,
    MissingSchema,
    RequestException,
)

# Directives recognized as standard/common in robots.txt files.
# Anything else encountered is flagged as a suspicious/unknown
# directive rather than silently ignored - but parsing still
# continues rather than failing.
KNOWN_DIRECTIVES = {
    "user-agent",
    "disallow",
    "allow",
    "sitemap",
    "crawl-delay",
    "host",
    "clean-param",
    "noindex",  # non-standard but seen in the wild (historically honored by some engines)
}

# Hard cap on how many lines we'll parse, so a pathologically large
# or adversarial robots.txt file can't make parsing hang or consume
# excessive memory. Real robots.txt files are almost always well
# under this.
MAX_PARSE_LINES = 5000


def _build_robots_url(url):
    """
    Convert any URL into that site's root robots.txt URL.

    Examples:
        https://example.com               -> https://example.com/robots.txt
        https://example.com/some/page?q=1 -> https://example.com/robots.txt
        http://example.com:8080/blog      -> http://example.com:8080/robots.txt

    Args:
        url (str): Any URL on the target site.

    Returns:
        str: The robots.txt URL for that site's root.

    Raises:
        ValueError: If the URL has no scheme (http/https) or no
            network location (domain), since robots.txt can't be
            built from an incomplete URL.
    """
    parsed = urlparse(url)

    # A valid URL needs both a scheme (http/https) and a netloc
    # (domain, e.g. "example.com"). Without these we can't safely
    # build a robots.txt URL.
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"URL is missing a scheme or domain: {url}")

    # Rebuild the URL using only scheme + netloc, discarding any
    # path, query string, or fragment, then append "/robots.txt".
    # robots.txt always lives at the site's root, regardless of
    # which page URL was originally provided.
    root = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    return f"{root}/robots.txt"


def _looks_like_text(content):
    """
    Heuristic check for whether fetched content is usable plain text
    (as robots.txt is supposed to be), rather than binary data that
    happened to decode into a garbled string.

    Args:
        content (str): The response body, already decoded to a
            Python string by `requests`.

    Returns:
        bool: True if the content looks like normal text.
    """
    if not content:
        # Empty content is still valid, usable text (an empty
        # robots.txt is technically legal and means "allow all").
        return True

    # A NUL byte essentially never appears in legitimate text and is
    # a strong signal of binary content that was mis-decoded.
    if "\x00" in content:
        return False

    # Count "control" characters that aren't normal whitespace
    # (tab, newline, carriage return). A high proportion of these
    # suggests binary content rather than text.
    sample = content[:2000]
    non_printable = sum(
        1 for ch in sample if ord(ch) < 32 and ch not in ("\t", "\n", "\r")
    )
    if len(sample) > 0 and (non_printable / len(sample)) > 0.10:
        return False

    return True


def _looks_like_html(content):
    """
    Heuristic check for whether content is actually an HTML page
    (e.g. a "soft 404" error page served with a 200 status) rather
    than a real robots.txt file.

    Args:
        content (str): The response body.

    Returns:
        bool: True if the content appears to be HTML.
    """
    head = content.lstrip()[:200].lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<head" in head or "<body" in head


def _parse_robots_txt(content):
    """
    Parse robots.txt content into structured rule groups, declared
    sitemap URLs, and a list of detected issues.

    This is a lightweight, line-based parser following the general
    shape of the robots.txt spec (RFC 9309). It intentionally does
    not try to be a fully compliant parser - Novash only needs
    enough structure to report on and score the file - but it does
    not crash on malformed input; anything it can't make sense of is
    recorded as an issue instead.

    Args:
        content (str): The raw robots.txt text.

    Returns:
        dict: {
            "rules": list[dict],       # parsed User-agent rule groups
            "sitemaps": list[str],     # Sitemap: URLs declared in the file
            "issues": list[str],       # malformed/suspicious lines, etc.
            "blocks_everything": bool  # True if a "User-agent: *" /
                                       # "Disallow: /" block was found
        }
    """
    rules = []
    sitemaps = []
    issues = []

    # None until we see a "User-agent:" line; this is the rule group
    # currently being built up as subsequent Disallow/Allow lines
    # are read.
    current_rule = None

    lines = content.splitlines()

    if len(lines) > MAX_PARSE_LINES:
        issues.append(
            f"robots.txt has {len(lines)} lines; only the first "
            f"{MAX_PARSE_LINES} were parsed."
        )
        lines = lines[:MAX_PARSE_LINES]

    for line_number, raw_line in enumerate(lines, start=1):
        # Strip inline comments: everything from the first '#'
        # onward is a comment per the robots.txt spec.
        line = raw_line.split("#", 1)[0].strip()

        if not line:
            # Blank line (or a line that was only a comment) - just
            # skip it. Note: some strict interpretations treat a
            # blank line as ending the current rule group, but most
            # real-world robots.txt files (and major crawlers) don't
            # rely on that, so we don't either.
            continue

        if ":" not in line:
            # No colon at all means this isn't a valid "field: value"
            # directive line - flag it and move on rather than
            # crashing or silently dropping it.
            issues.append(f"Line {line_number}: malformed directive (no ':' found): {raw_line!r}")
            continue

        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()

        if field not in KNOWN_DIRECTIVES:
            issues.append(f"Line {line_number}: unknown/unsupported directive '{field}'")
            # Still worth trying to use it if it happens to be a
            # close variant, but for simplicity we just skip further
            # processing of this line's value.
            continue

        if field == "user-agent":
            if not value:
                issues.append(f"Line {line_number}: 'User-agent' directive has no value")
                continue

            if current_rule is not None and (current_rule["disallow"] or current_rule["allow"]):
                # The previous rule group already has directives
                # attached to it, so this User-agent line starts a
                # brand new group rather than extending the old one.
                rules.append(current_rule)
                current_rule = None

            if current_rule is None:
                current_rule = {"user_agents": [], "disallow": [], "allow": []}

            current_rule["user_agents"].append(value)

        elif field in ("disallow", "allow"):
            if current_rule is None or not current_rule["user_agents"]:
                # A Disallow/Allow line with no preceding User-agent
                # is invalid per spec - it has no group to attach to.
                issues.append(
                    f"Line {line_number}: '{field.title()}' directive found before any "
                    "'User-agent' line"
                )
                continue

            current_rule[field].append(value)

        elif field == "sitemap":
            if not value:
                issues.append(f"Line {line_number}: 'Sitemap' directive has no value")
                continue

            parsed_sitemap = urlparse(value)
            if parsed_sitemap.scheme not in ("http", "https") or not parsed_sitemap.netloc:
                issues.append(f"Line {line_number}: invalid Sitemap URL: {value!r}")
                continue

            sitemaps.append(value)

        elif field == "crawl-delay":
            try:
                float(value)
            except (TypeError, ValueError):
                issues.append(f"Line {line_number}: 'Crawl-delay' value is not numeric: {value!r}")
            # Valid or not, Crawl-delay doesn't need to be stored on
            # a rule group for Novash's purposes - it isn't used
            # elsewhere in the app - so nothing further to record.

        # "host" and "clean-param" are recognized (won't be flagged
        # as unknown) but Novash doesn't currently do anything
        # further with them beyond accepting their presence.

    if current_rule is not None:
        rules.append(current_rule)

    # --- Detect the dangerous site-wide block ---
    # A rule group that applies to "*" (all crawlers) and disallows
    # "/" (the entire site) with nothing under Allow is the classic
    # "please don't index anything" mistake.
    blocks_everything = False
    for rule in rules:
        applies_to_all = any(agent.strip() == "*" for agent in rule["user_agents"])
        disallows_root = any(path.strip() == "/" for path in rule["disallow"])
        has_allow_override = len(rule["allow"]) > 0

        if applies_to_all and disallows_root and not has_allow_override:
            blocks_everything = True
            break

    if blocks_everything:
        issues.append(
            "robots.txt blocks ALL crawlers from the entire site "
            "(User-agent: * / Disallow: /) - this will prevent search "
            "engines from indexing the site."
        )

    return {
        "rules": rules,
        "sitemaps": sitemaps,
        "issues": issues,
        "blocks_everything": blocks_everything,
    }


def _result(
    status,
    message,
    url,
    status_code=None,
    is_text=None,
    issues=None,
    sitemaps=None,
    rules=None,
    blocks_everything=False,
):
    """
    Build a complete, consistently-shaped result dict. Every code
    path through check_robots() returns through this helper so
    callers can always rely on every key being present, regardless
    of which branch produced the result.

    "status" is kept as the primary boolean (matching the original
    API this module has always exposed - True means robots.txt was
    successfully fetched with a 200 response). "found" is included
    as a plain alias of the same value, matching the naming used by
    Novash's other checkers (e.g. canonical_checker.check_canonical),
    for callers that prefer that name.
    """
    return {
        "status": status,
        "found": status,
        "message": message,
        "url": url,
        "status_code": status_code,
        "is_text": is_text,
        "issues": issues if issues is not None else [],
        "sitemaps": sitemaps if sitemaps is not None else [],
        "rules": rules if rules is not None else [],
        "blocks_everything": blocks_everything,
    }


def check_robots(url, timeout=10):
    """
    Check whether a website has a robots.txt file, and analyze its
    contents.

    Args:
        url (str): Any URL belonging to the site to check
            (e.g. "https://example.com" or "https://example.com/blog").
        timeout (int | float): Max seconds to wait for a response
            before giving up (default: 10).

    Returns:
        dict: {
            "status": bool,        # True if robots.txt exists and is reachable
                                    # (kept for backward compatibility)
            "found": bool,         # Same value as "status", alias
            "message": str,        # Human-readable result summary
            "url": str | None,     # The robots.txt URL that was checked
            "status_code": int | None,  # HTTP status code, if a response was received
            "is_text": bool | None,     # True if the response body looks like usable text
            "issues": list[str],   # Problems detected: malformed lines, a
                                    # site-wide block, non-text content, etc.
            "sitemaps": list[str], # Sitemap URLs declared in robots.txt
                                    # (never fetched - only extracted)
            "rules": list[dict],   # Parsed rule groups, each:
                                    # {"user_agents": [...], "disallow": [...], "allow": [...]}
            "blocks_everything": bool,  # True if User-agent: * / Disallow: / was found
        }
        Every key above is present in the result regardless of which
        code path produced it (missing URL, network error, 404,
        successful parse, etc.), so callers never need to guard
        against a key being absent. The whole structure is plain
        dicts/lists/strings/bools/None, so it's always JSON-serializable.
    """
    # Basic type/sanity check before even building a URL.
    if not isinstance(url, str) or not url.strip():
        return _result(
            status=False,
            message="Invalid URL: URL must be a non-empty string",
            url=None,
        )

    # Build the robots.txt URL from whatever page URL was given.
    try:
        robots_url = _build_robots_url(url.strip())
    except ValueError as e:
        return _result(
            status=False,
            message=f"Invalid URL: {e}",
            url=None,
        )

    # A realistic User-Agent avoids being blocked by sites that
    # reject requests with no/blank User-Agent.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; NovashBot/1.0; "
            "+https://example.com/bot)"
        )
    }

    try:
        response = requests.get(robots_url, headers=headers, timeout=timeout)

    except MissingSchema:
        # e.g. "example.com" instead of "https://example.com"
        return _result(
            status=False,
            message=f"Invalid URL (missing scheme like 'http://'): {robots_url}",
            url=robots_url,
        )

    except InvalidURL:
        return _result(
            status=False,
            message=f"Invalid URL: {robots_url}",
            url=robots_url,
        )

    except Timeout:
        return _result(
            status=False,
            message=f"Request timed out after {timeout}s: {robots_url}",
            url=robots_url,
        )

    except ConnectionError:
        # DNS failure, refused connection, no internet, etc.
        return _result(
            status=False,
            message=f"Failed to connect to: {robots_url}",
            url=robots_url,
        )

    except RequestException as e:
        # Catch-all for any other requests-related error.
        return _result(
            status=False,
            message=f"An error occurred while requesting {robots_url}: {e}",
            url=robots_url,
        )

    # Anything other than 200 OK means robots.txt is effectively
    # missing/unavailable for our purposes (404, 403, 500, etc.).
    if response.status_code != 200:
        return _result(
            status=False,
            message="robots.txt missing",
            url=robots_url,
            status_code=response.status_code,
        )

    # We have a 200 response - inspect the body itself rather than
    # assuming it's automatically valid. `response.text` is already
    # decoded to a Python string by requests (using the declared or
    # detected encoding), so this never raises even for odd/binary
    # content - it just may produce garbled text, which the checks
    # below try to detect.
    content = response.text or ""

    is_text = _looks_like_text(content)

    if not is_text:
        # Binary/garbled content masquerading as robots.txt - there's
        # nothing meaningful to parse, so we stop here rather than
        # feeding garbage into the line parser.
        return _result(
            status=True,
            message="robots.txt found, but the response does not appear to be usable text",
            url=robots_url,
            status_code=response.status_code,
            is_text=False,
            issues=["robots.txt response does not appear to be valid text content."],
        )

    parsed = _parse_robots_txt(content)
    issues = list(parsed["issues"])

    if _looks_like_html(content):
        # A 200 response whose body is an HTML page (a common "soft
        # 404" pattern) isn't a real robots.txt file, even though it
        # technically counts as "text".
        issues.insert(
            0,
            "Response looks like an HTML page rather than a plain-text "
            "robots.txt file (possible soft 404).",
        )

    message = "robots.txt found"
    if issues:
        message = "robots.txt found, with issues"

    return _result(
        status=True,
        message=message,
        url=robots_url,
        status_code=response.status_code,
        is_text=True,
        issues=issues,
        sitemaps=parsed["sitemaps"],
        rules=parsed["rules"],
        blocks_everything=parsed["blocks_everything"],
    )


if __name__ == "__main__":
    # Quick manual tests.
    import json

    print(json.dumps(check_robots("https://pypi.org"), indent=2))
    print(json.dumps(check_robots("https://pypi.org/some/deep/page?x=1"), indent=2))
    print(json.dumps(check_robots("not a valid url"), indent=2))
    print(json.dumps(check_robots(""), indent=2))
