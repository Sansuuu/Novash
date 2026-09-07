"""
twitter_checker.py

Checks a page's Twitter/X Card meta tags (used by Twitter/X to build
rich link previews, similar in spirit to Open Graph tags but with
their own separate set of <meta name="twitter:..."> tags).

Works entirely from an already-parsed BeautifulSoup object - it does
not make any HTTP requests of its own.
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

# The four "primary" Twitter Card tags. A page needs all four, with
# real (non-empty) content, to be considered a complete Twitter Card.
PRIMARY_TWITTER_TAGS = ("twitter:card", "twitter:title", "twitter:description", "twitter:image")

# Two additional, optional Twitter Card tags. Their presence is still
# checked and reported, but they are never treated as required -
# they don't affect "status" and are never added to "missing".
OPTIONAL_TWITTER_TAGS = ("twitter:site", "twitter:creator")

ALL_TWITTER_TAGS = PRIMARY_TWITTER_TAGS + OPTIONAL_TWITTER_TAGS

# Maps each full "twitter:xxx" tag name to the short key used in the
# "tags" dict of the result (e.g. "twitter:description" -> "description").
_SHORT_NAME = {
    "twitter:card": "card",
    "twitter:title": "title",
    "twitter:description": "description",
    "twitter:image": "image",
    "twitter:site": "site",
    "twitter:creator": "creator",
}


def _invalid_input_result() -> Dict[str, Any]:
    """
    Build the result returned when `soup` is None, or isn't a usable
    BeautifulSoup-like object at all. Every field is present with
    "nothing found" defaults, so callers never need to guard against
    a missing key.
    """
    return {
        "status": "missing",
        "tags": {_SHORT_NAME[tag]: None for tag in ALL_TWITTER_TAGS},
        "missing": list(PRIMARY_TWITTER_TAGS),
        "issues": [],
    }


def check_twitter_cards(soup: Optional["BeautifulSoup"]) -> Dict[str, Any]:
    """
    Check a page's Twitter/X Card meta tags.

    Looks for <meta name="twitter:..." content="..."> tags for six
    fields: twitter:card, twitter:title, twitter:description, and
    twitter:image (the four "primary" tags required for a complete
    card), plus twitter:site and twitter:creator (optional - never
    treated as required). Uses the existing BeautifulSoup object
    passed in - no network request is made.

    Note: unlike Open Graph tags (which use the "property" attribute),
    Twitter Card tags use the standard "name" attribute, e.g.:
        <meta name="twitter:card" content="summary_large_image">

    Args:
        soup (BeautifulSoup | None): Parsed HTML of the page, as
            returned by crawler.get_page(). May be None if the page
            failed to load/parse, or anything else if an invalid
            value was passed in by mistake - both are handled
            gracefully rather than raising.

    Returns:
        dict: {
            "status": str,
                # "complete"   - all four primary tags present with
                #                 non-empty content
                # "incomplete" - some, but not all, primary tags present
                # "missing"    - none of the primary tags are present
                #                 (or soup was None/invalid)
            "tags": dict[str, str | None],
                # The content value for all SIX tags, keyed by short
                # name (e.g. "card", "creator"). None if that tag is
                # missing or has empty content.
            "missing": list[str],
                # Names of any PRIMARY tags (only) that are missing
                # or empty, e.g. ["twitter:image"]. Optional tags
                # (twitter:site, twitter:creator) are never listed
                # here, per their "not required" status.
            "issues": list[str],
                # Human-readable problems detected across all six
                # tags: duplicate tags and empty content attributes.
                # Purely informational; does not affect "status" or
                # "missing" above.
        }
        The whole structure is plain dicts/lists/strings/None, so
        it's always JSON-serializable.
    """
    # Guard clause: if crawling/parsing failed upstream, soup will be
    # None. Handle that up front so we don't raise an AttributeError
    # by calling .find_all() on None.
    if soup is None:
        return _invalid_input_result()

    tags: Dict[str, Optional[str]] = {}
    primary_missing: List[str] = []
    issues: List[str] = []
    primary_found_count = 0

    for tag_name in ALL_TWITTER_TAGS:
        # Twitter Card tags use the "name" attribute (not "property",
        # which Open Graph tags use).
        # e.g. <meta name="twitter:title" content="My Page">
        #
        # find_all() (rather than find()) is used so duplicate tags
        # can be detected. Wrapped in try/except: if something other
        # than a real BeautifulSoup object was passed in (e.g. a
        # plain string), calling .find_all() will raise an
        # AttributeError/TypeError rather than doing what we want.
        # Treat that the same as "nothing found" instead of crashing
        # the caller.
        try:
            matches = soup.find_all("meta", attrs={"name": tag_name})
        except (TypeError, AttributeError):
            return _invalid_input_result()

        if len(matches) > 1:
            issues.append(
                f"Duplicate {tag_name} tags found ({len(matches)}); "
                "only the first is used."
            )

        first_tag = matches[0] if matches else None
        raw_content = first_tag.get("content") if first_tag else None
        content_value = raw_content.strip() if raw_content else ""
        is_present = bool(content_value)

        if first_tag is not None and not is_present:
            # The tag exists in the HTML but its content attribute is
            # empty/whitespace-only - distinct from the tag being
            # absent entirely, and worth calling out separately.
            issues.append(f"{tag_name} tag exists but has an empty content attribute.")

        tags[_SHORT_NAME[tag_name]] = content_value if is_present else None

        if tag_name in PRIMARY_TWITTER_TAGS:
            if is_present:
                primary_found_count += 1
            else:
                primary_missing.append(tag_name)

    # status reflects only the four PRIMARY tags. Optional tags
    # (twitter:site, twitter:creator) never affect it.
    if primary_found_count == len(PRIMARY_TWITTER_TAGS):
        status = "complete"
    elif primary_found_count == 0:
        status = "missing"
    else:
        status = "incomplete"

    return {
        "status": status,
        "tags": tags,
        "missing": primary_missing,
        "issues": issues,
    }


if __name__ == "__main__":
    # Quick manual tests using small inline HTML samples, so this
    # file can be run standalone without a network request.
    from bs4 import BeautifulSoup as _BS
    import json

    # Case 1: complete card, including both optional tags.
    complete_html = """
    <html><head>
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:title" content="Example Title">
        <meta name="twitter:description" content="Example description.">
        <meta name="twitter:image" content="https://example.com/image.png">
        <meta name="twitter:site" content="@example">
        <meta name="twitter:creator" content="@exampleauthor">
    </head><body></body></html>
    """
    print("Case 1 - complete card with optional tags:")
    print(json.dumps(check_twitter_cards(_BS(complete_html, "html.parser")), indent=2))
    print()

    # Case 2: incomplete - some primary tags missing, one empty,
    # optional tags entirely absent.
    partial_html = """
    <html><head>
        <meta name="twitter:card" content="summary">
        <meta name="twitter:image" content="">
    </head><body></body></html>
    """
    print("Case 2 - incomplete/empty tags:")
    print(json.dumps(check_twitter_cards(_BS(partial_html, "html.parser")), indent=2))
    print()

    # Case 3: duplicate twitter:title tags.
    duplicate_html = """
    <html><head>
        <meta name="twitter:card" content="summary">
        <meta name="twitter:title" content="First Title">
        <meta name="twitter:title" content="Second Title">
        <meta name="twitter:description" content="Example description.">
        <meta name="twitter:image" content="https://example.com/image.png">
    </head><body></body></html>
    """
    print("Case 3 - duplicate twitter:title tags:")
    print(json.dumps(check_twitter_cards(_BS(duplicate_html, "html.parser")), indent=2))
    print()

    # Case 4: no Twitter Card tags at all.
    missing_html = "<html><head><title>No Twitter tags here</title></head></html>"
    print("Case 4 - no Twitter Card tags at all:")
    print(json.dumps(check_twitter_cards(_BS(missing_html, "html.parser")), indent=2))
    print()

    # Case 5: soup is None (failed crawl).
    print("Case 5 - soup is None:")
    print(json.dumps(check_twitter_cards(None), indent=2))
    print()

    # Case 6: something invalid passed in.
    print("Case 6 - invalid input (a plain string):")
    print(json.dumps(check_twitter_cards("not a soup object"), indent=2))
