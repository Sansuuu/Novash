"""
og_checker.py

Checks a page's Open Graph meta tags (used by social platforms like
Facebook, LinkedIn, and Twitter/X to build rich link previews).

Works entirely from an already-parsed BeautifulSoup object - it does
not make any HTTP requests of its own.
"""

from typing import Any, Dict, List, Optional

try:
    # Only used for the type hint below - a plain "Optional[object]"
    # would work just as well at runtime, but this is more precise
    # for readers/IDEs. Guarded in a try/except purely so this module
    # never fails to import in an environment where bs4 isn't
    # installed yet (matching the defensive style used elsewhere in
    # Novash's checkers).
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = Any  # type: ignore

# The four "core" Open Graph tags Novash has always required for a
# page to be considered fully OG-compliant. This set, its meaning,
# and the shape of the "status"/"tags"/"missing" fields below are
# UNCHANGED from the original implementation, since cli.py and
# score.py both already depend on this exact structure:
#   - cli.py reads og_result["status"] and iterates og_result["missing"]
#   - score.py's _open_graph_points() reads og_result["tags"] as a
#     dict[str, bool] and divides by len(tags) to compute partial
#     credit
# Changing what "tags"/"missing"/"status" mean here would silently
# change scoring/report behavior in those files without touching
# them, which is exactly what this update avoids.
CORE_OG_TAGS = ("og:title", "og:description", "og:image", "og:url")

# Two additional, commonly-recommended Open Graph tags that are now
# also checked and reported, but are NOT required for "status"/
# "found" to be True and are NOT added to "missing" - only the four
# core tags above drive those two fields, to avoid changing existing
# scoring/report behavior. Their presence/content is still fully
# reported via the new "content" and "issues" fields below.
EXTRA_OG_TAGS = ("og:type", "og:site_name")

ALL_OG_TAGS = CORE_OG_TAGS + EXTRA_OG_TAGS

# Maps each full "og:xxx" property name to the short key used in the
# new "content" dict (e.g. "og:site_name" -> "site_name"), matching
# the naming style requested for the richer structured output.
_SHORT_NAME = {
    "og:title": "title",
    "og:description": "description",
    "og:image": "image",
    "og:url": "url",
    "og:type": "type",
    "og:site_name": "site_name",
}


def _invalid_input_result() -> Dict[str, Any]:
    """
    Build the result returned when `soup` is None, or isn't a usable
    BeautifulSoup-like object at all. Every field is present with
    "nothing found" defaults, so callers never need to guard against
    a missing key.
    """
    return {
        "status": False,
        "found": False,
        "tags": {tag: False for tag in CORE_OG_TAGS},
        "missing": list(CORE_OG_TAGS),
        "content": {_SHORT_NAME[tag]: None for tag in ALL_OG_TAGS},
        "issues": [],
    }


def check_open_graph(soup: Optional["BeautifulSoup"]) -> Dict[str, Any]:
    """
    Check a page's Open Graph meta tags.

    Looks for <meta property="og:..." content="..."> tags for six
    fields: og:title, og:description, og:image, og:url (the four
    "core" tags), plus og:type and og:site_name (commonly recommended
    but not required). Uses the existing BeautifulSoup object passed
    in - no new network request is made.

    Args:
        soup (BeautifulSoup | None): Parsed HTML of the page, as
            returned by crawler.get_page(). May be None if the page
            failed to load/parse, or anything else if an invalid
            value was passed in by mistake - both are handled
            gracefully rather than raising.

    Returns:
        dict: {
            "status": bool,
                # True only if all FOUR CORE tags (og:title,
                # og:description, og:image, og:url) are present with
                # non-empty content. Unchanged meaning from the
                # original implementation.
            "found": bool,
                # Alias of "status", for callers that prefer that
                # naming (matches canonical_checker/robots_checker).
            "tags": dict[str, bool],
                # UNCHANGED shape: each of the four core "og:xxx"
                # names mapped to whether it was found with non-empty
                # content. This is what score.py's partial-credit
                # calculation reads - its meaning is preserved
                # exactly so scoring behavior doesn't silently change.
            "missing": list[str],
                # UNCHANGED shape: names of any of the four CORE tags
                # that are missing or empty, e.g. ["og:image", "og:url"].
            "content": dict[str, str | None],
                # NEW: the actual content value for all SIX tags,
                # keyed by short name (e.g. "title", "site_name").
                # None if that tag is missing or has empty content.
            "issues": list[str],
                # NEW: human-readable problems detected across all
                # six tags - duplicate tags and empty content
                # attributes. Purely informational; does not affect
                # "status"/"tags"/"missing" above.
        }
        The whole structure is plain dicts/lists/strings/bools/None,
        so it's always JSON-serializable.
    """
    # Guard clause: if crawling/parsing failed upstream, soup will be
    # None. Handle that up front so we don't raise an AttributeError
    # by calling .find_all() on None.
    if soup is None:
        return _invalid_input_result()

    core_tags_found: Dict[str, bool] = {}
    core_missing: List[str] = []
    content: Dict[str, Optional[str]] = {}
    issues: List[str] = []

    for tag_name in ALL_OG_TAGS:
        # Open Graph tags use the "property" attribute (not "name",
        # which is used by tags like meta description).
        # e.g. <meta property="og:title" content="My Page">
        #
        # find_all() (rather than find()) is used so duplicate tags
        # can be detected. Wrapped in try/except: if something other
        # than a real BeautifulSoup object was passed in (e.g. a
        # plain string), calling .find_all() will raise an
        # AttributeError/TypeError rather than doing what we want.
        # Treat that the same as "nothing found" instead of crashing
        # the caller.
        try:
            matches = soup.find_all("meta", attrs={"property": tag_name})
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

        content[_SHORT_NAME[tag_name]] = content_value if is_present else None

        if tag_name in CORE_OG_TAGS:
            core_tags_found[tag_name] = is_present
            if not is_present:
                core_missing.append(tag_name)

    # status/found is True only when every one of the four CORE tags
    # was found with real content - a partial set still counts as
    # incomplete. og:type/og:site_name do not affect this, matching
    # their "recommended but not required" role.
    status = len(core_missing) == 0

    return {
        "status": status,
        "found": status,
        "tags": core_tags_found,
        "missing": core_missing,
        "content": content,
        "issues": issues,
    }


if __name__ == "__main__":
    # Quick manual tests using small inline HTML samples, so this
    # file can be run standalone without a network request.
    from bs4 import BeautifulSoup as _BS
    import json

    # Case 1: all six tags present, no issues.
    complete_html = """
    <html><head>
        <meta property="og:title" content="Example Title">
        <meta property="og:description" content="Example description.">
        <meta property="og:image" content="https://example.com/image.png">
        <meta property="og:url" content="https://example.com">
        <meta property="og:type" content="website">
        <meta property="og:site_name" content="Example Site">
    </head><body></body></html>
    """
    print("Case 1 - all six tags present:")
    print(json.dumps(check_open_graph(_BS(complete_html, "html.parser")), indent=2))
    print()

    # Case 2: some core tags missing, one has empty content, extras absent.
    partial_html = """
    <html><head>
        <meta property="og:title" content="Example Title">
        <meta property="og:image" content="">
    </head><body></body></html>
    """
    print("Case 2 - partial/empty tags:")
    print(json.dumps(check_open_graph(_BS(partial_html, "html.parser")), indent=2))
    print()

    # Case 3: duplicate og:title tags.
    duplicate_html = """
    <html><head>
        <meta property="og:title" content="First Title">
        <meta property="og:title" content="Second Title">
        <meta property="og:description" content="Example description.">
        <meta property="og:image" content="https://example.com/image.png">
        <meta property="og:url" content="https://example.com">
    </head><body></body></html>
    """
    print("Case 3 - duplicate og:title tags:")
    print(json.dumps(check_open_graph(_BS(duplicate_html, "html.parser")), indent=2))
    print()

    # Case 4: no soup at all (failed crawl).
    print("Case 4 - soup is None:")
    print(json.dumps(check_open_graph(None), indent=2))
    print()

    # Case 5: something invalid passed in.
    print("Case 5 - invalid input (a plain string):")
    print(json.dumps(check_open_graph("not a soup object"), indent=2))
