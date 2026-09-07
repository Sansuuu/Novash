"""
favicon_checker.py

Checks a page's favicon declarations:
    <link rel="icon" href="...">
    <link rel="shortcut icon" href="...">
    <link rel="apple-touch-icon" href="...">

Works entirely from an already-parsed BeautifulSoup object - it does
not make any HTTP requests of its own, and never verifies whether a
declared favicon URL actually resolves to a real file. Only the HTML
itself is inspected.
"""

from typing import Any, Dict, List, Optional

try:
    # Only used for the type hint below. Guarded in a try/except so
    # this module never fails to import in an environment where bs4
    # isn't installed yet (matching the defensive style used
    # elsewhere in Novash's checkers, e.g. og_checker.py).
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = Any  # type: ignore

# rel="icon" is treated as the primary/canonical favicon declaration.
PRIMARY_REL = "icon"

# These are also recognized and reported, but never required on
# their own - a page with only an apple-touch-icon (and no plain
# icon/shortcut icon) is still considered to have a usable favicon.
ADDITIONAL_RELS = ("shortcut icon", "apple-touch-icon")

ALL_RECOGNIZED_RELS = (PRIMARY_REL,) + ADDITIONAL_RELS


def _classify_rel(rel_tokens: List[str]) -> Optional[str]:
    """
    Classify a <link> tag's `rel` attribute into one of Novash's
    recognized favicon declaration types.

    BeautifulSoup treats `rel` as a multi-valued attribute, so
    rel="shortcut icon" parses as the token list ["shortcut", "icon"]
    - not the single string "shortcut icon". This function compares
    the token SET (case-insensitive, order-independent) against each
    recognized declaration so "icon" and "shortcut icon" are
    correctly told apart, rather than a naive search incorrectly
    treating "shortcut icon" tags as plain "icon" tags too (since
    "icon" is technically one of its tokens).

    Args:
        rel_tokens (list[str]): The raw `rel` attribute value as
            BeautifulSoup parses it (a list of tokens).

    Returns:
        str | None: One of "icon", "shortcut icon", or
        "apple-touch-icon" if recognized, otherwise None (e.g. for
        rel="stylesheet", which isn't a favicon declaration at all).
    """
    tokens = {token.lower() for token in rel_tokens if token}

    if tokens == {"icon"}:
        return "icon"
    if tokens == {"shortcut", "icon"}:
        return "shortcut icon"
    if tokens == {"apple-touch-icon"}:
        return "apple-touch-icon"

    return None


def _empty_result() -> Dict[str, Any]:
    """
    Build the result returned when there's nothing to analyze at
    all: `soup` is None, isn't a usable BeautifulSoup-like object, or
    the page has no recognized favicon <link> tags whatsoever.
    """
    return {
        "status": "missing",
        "found": False,
        "icons": [],
        "missing": [],
        "issues": [],
    }


def check_favicon(soup: Optional["BeautifulSoup"]) -> Dict[str, Any]:
    """
    Check a page's favicon declarations.

    Looks for <link> tags whose `rel` attribute is "icon" (the
    primary/canonical favicon declaration), "shortcut icon", or
    "apple-touch-icon" (both reported as additional declarations).
    Uses the existing BeautifulSoup object passed in - no network
    request is made, and declared favicon URLs are never verified to
    actually exist; only the HTML markup itself is inspected.

    Args:
        soup (BeautifulSoup | None): Parsed HTML of the page, as
            returned by crawler.get_page(). May be None if the page
            failed to load/parse, or anything else if an invalid
            value was passed in by mistake - both are handled
            gracefully rather than raising.

    Returns:
        dict: {
            "status": str,
                # "found"   - at least one recognized favicon <link>
                #              tag has a usable (non-empty) href
                # "missing" - no recognized favicon <link> tags were
                #              found on the page at all (or soup was
                #              None/invalid)
                # "invalid" - one or more recognized favicon <link>
                #              tags were present, but NONE of them
                #              had a usable href (e.g. every one has
                #              href="" or no href attribute at all)
            "found": bool,
                # True only when status == "found"; a plain
                # convenience boolean alongside "status".
            "icons": list[dict],
                # One entry per recognized favicon <link> tag found,
                # regardless of whether its href is usable:
                #   {"rel": list[str], "href": str | None}
                # "rel" is the tag's raw rel token list, lowercased
                # (e.g. ["icon"] or ["shortcut", "icon"]). "href" is
                # the (stripped) href value, or None if it was
                # missing/empty.
            "missing": list[str],
                # Intentionally always empty. Only "icon" is treated
                # as the primary declaration, and even that is not
                # strictly required for every page to "pass" - a page
                # simply either has a usable favicon declaration or it
                # doesn't (reflected in "status"/"found"). This field
                # is kept for structural consistency with Novash's
                # other checkers rather than removed outright.
            "issues": list[str],
                # Human-readable problems detected: a recognized tag
                # with an empty/missing href, and multiple
                # declarations of the same rel type. Purely
                # informational; does not add new items to "missing".
        }
        The whole structure is plain dicts/lists/strings/bools/None,
        so it's always JSON-serializable.
    """
    if soup is None:
        return _empty_result()

    try:
        link_tags = soup.find_all("link")
    except (TypeError, AttributeError):
        # Something other than a real BeautifulSoup object was passed
        # in (e.g. a plain string) - treat the same as "nothing to
        # check" rather than crashing the caller.
        return _empty_result()

    icons: List[Dict[str, Any]] = []
    issues: List[str] = []
    usable_found = False
    rel_type_counts: Dict[str, int] = {}

    for tag in link_tags:
        raw_rel = tag.get("rel")
        if not raw_rel:
            # No rel attribute at all - not a favicon declaration
            # (and not any other kind of <link> we care about here).
            continue

        rel_type = _classify_rel(raw_rel)
        if rel_type is None:
            # A <link> tag with some other rel (e.g. "stylesheet",
            # "canonical") - not relevant to favicons.
            continue

        rel_type_counts[rel_type] = rel_type_counts.get(rel_type, 0) + 1

        href = tag.get("href")
        href_value = href.strip() if href else ""

        if not href_value:
            issues.append(f'<link rel="{rel_type}"> tag found but has no usable href.')

        icons.append({
            "rel": [token.lower() for token in raw_rel],
            "href": href_value if href_value else None,
        })

        if href_value:
            usable_found = True

    if not icons:
        # No recognized favicon <link> tags at all.
        return _empty_result()

    # --- Duplicate declaration detection ---
    # Having different TYPES together (icon + apple-touch-icon, say)
    # is completely normal and expected. The same type appearing more
    # than once is what's worth calling out.
    for rel_type, count in rel_type_counts.items():
        if count > 1:
            issues.append(
                f'Multiple <link rel="{rel_type}"> declarations found ({count}); '
                "browsers typically only use one."
            )

    status = "found" if usable_found else "invalid"

    return {
        "status": status,
        "found": status == "found",
        "icons": icons,
        "missing": [],
        "issues": issues,
    }


if __name__ == "__main__":
    # Quick manual tests using small inline HTML samples, so this
    # file can be run standalone without a network request.
    from bs4 import BeautifulSoup as _BS
    import json as _json

    def _run(label: str, html: str) -> None:
        soup = _BS(html, "html.parser")
        print(f"{label}:")
        print(_json.dumps(check_favicon(soup), indent=2))
        print()

    # Case 1: a simple, valid favicon.
    _run(
        "Case 1 - simple valid favicon",
        '<html><head><link rel="icon" href="/favicon.ico"></head></html>',
    )

    # Case 2: shortcut icon and apple-touch-icon together (no plain "icon").
    _run(
        "Case 2 - shortcut icon + apple-touch-icon, no plain icon",
        """
        <html><head>
        <link rel="shortcut icon" href="/favicon.ico">
        <link rel="apple-touch-icon" href="/apple-touch-icon.png">
        </head></html>
        """,
    )

    # Case 3: favicon tag with empty href.
    _run(
        "Case 3 - empty href",
        '<html><head><link rel="icon" href=""></head></html>',
    )

    # Case 4: favicon tag with no href attribute at all.
    _run(
        "Case 4 - no href attribute",
        '<html><head><link rel="icon"></head></html>',
    )

    # Case 5: multiple <link rel="icon"> declarations.
    _run(
        "Case 5 - multiple icon declarations",
        """
        <html><head>
        <link rel="icon" href="/favicon-16.png">
        <link rel="icon" href="/favicon-32.png">
        </head></html>
        """,
    )

    # Case 6: no favicon declarations at all.
    _run(
        "Case 6 - no favicon at all",
        "<html><head><title>No favicon here</title></head></html>",
    )

    # Case 7: one usable icon, one broken (empty href) declaration together.
    _run(
        "Case 7 - one usable, one empty",
        """
        <html><head>
        <link rel="icon" href="/favicon.ico">
        <link rel="apple-touch-icon" href="">
        </head></html>
        """,
    )

    # Case 8: soup is None (failed crawl).
    print("Case 8 - soup is None:")
    print(_json.dumps(check_favicon(None), indent=2))
    print()

    # Case 9: something invalid passed in.
    print("Case 9 - invalid input (a plain string):")
    print(_json.dumps(check_favicon("not a soup object"), indent=2))
