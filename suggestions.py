"""
suggestions.py

Suggestion generation for Novash.

Takes the combined results of all SEO checks and turns any failing
checks into plain-language, actionable suggestions.
"""

# Friendly, tag-specific reasons shown alongside each missing Open
# Graph tag, so the suggestion explains *why* it matters rather than
# just naming the tag.
OG_TAG_REASONS = {
    "og:title": "Add og:title for better social sharing previews.",
    "og:description": "Add og:description for better social sharing previews.",
    "og:image": "Add og:image for better social sharing previews.",
    "og:url": "Add og:url for better social sharing previews.",
}


def generate_suggestions(results):
    """
    Generate a list of actionable SEO suggestions based on check results.

    Args:
        results (dict): The combined results of all checks, e.g.
            {
                "title": {"status": False, "message": "...", "title": None},
                "meta_description": {"status": True, ...},
                "h1": {"status": False, "h1_tags": [], ...},
                "images": {"status": True, "total_images": 20,
                           "with_alt": 3, "without_alt": 17},
                "open_graph": {"status": False,
                               "tags": {"og:title": True, "og:image": False, ...},
                               "missing": ["og:image", "og:url"]},
                "links": {"total": 30, "working": 27, "broken": 3, ...}
            }
            Each value is expected to be the dict returned by the
            matching function in checks.py (check_title,
            check_meta_description, check_h1, check_image_alts),
            og_checker.py (check_open_graph), or link_checker.py
            (check_links). The "open_graph" and "links" keys are
            both optional - results without them simply skip that
            suggestion category.

    Returns:
        list[str]: A list of human-readable suggestions, one per
        issue found. If nothing is wrong (or results is missing/
        malformed), returns ["No SEO issues found."].
    """
    suggestions = []

    # Guard clause: if results is missing entirely, there's nothing
    # to analyze. Treat that the same as "no issues found" rather
    # than crashing, since we have no evidence of a problem.
    if not results or not isinstance(results, dict):
        return ["No SEO issues found."]

    # --- Title check ---
    # .get(..., {}) guards against the "title" key being absent
    # entirely; .get("status", False) then guards against that
    # sub-dict itself being malformed or missing "status".
    title_result = results.get("title") or {}
    if not title_result.get("status", False):
        suggestions.append("Add a page title.")

    # --- Meta description check ---
    meta_result = results.get("meta_description") or {}
    if not meta_result.get("status", False):
        suggestions.append("Add a meta description.")

    # --- H1 check ---
    h1_result = results.get("h1") or {}
    if not h1_result.get("status", False):
        suggestions.append("Add at least one H1 tag.")

    # --- Image alt text check ---
    # Only suggest fixing images if there actually are some missing
    # alt text. A page with zero images, or one where every image
    # already has alt text, needs no suggestion here.
    images_result = results.get("images") or {}
    # Use max(..., 0) as a safety net in case this value is ever
    # negative or the wrong type (falls back to 0 via try/except).
    try:
        without_alt = int(images_result.get("without_alt", 0))
    except (TypeError, ValueError):
        # If the value can't be interpreted as a number, treat it as
        # "unknown" and skip this suggestion rather than crashing.
        without_alt = 0

    without_alt = max(without_alt, 0)
    if without_alt > 0:
        suggestions.append(f"Add alt text to {without_alt} images.")

    # --- Open Graph check ---
    # "open_graph" is optional - results built before og_checker.py
    # existed simply won't have this key, and that's fine: .get()
    # returns {} and nothing is suggested.
    og_result = results.get("open_graph") or {}
    missing_og_tags = og_result.get("missing") or []

    # One specific, actionable suggestion per missing tag (rather
    # than a single generic "fix Open Graph tags" message), so the
    # person knows exactly what to add.
    for tag_name in missing_og_tags:
        # Fall back to a generic phrasing for any tag name that
        # isn't one of the four we recognize, so an unexpected/
        # unknown tag still produces a sensible suggestion instead
        # of being silently skipped.
        suggestion = OG_TAG_REASONS.get(
            tag_name,
            f"Add {tag_name} for better social sharing previews.",
        )
        suggestions.append(suggestion)

    # --- Broken links check ---
    # "links" is optional - results built before link_checker.py
    # existed simply won't have this key, and that's fine: .get()
    # returns {} and nothing is suggested.
    links_result = results.get("links") or {}
    try:
        broken_links = int(links_result.get("broken", 0))
    except (TypeError, ValueError):
        # If the value can't be interpreted as a number, treat it as
        # "unknown" and skip this suggestion rather than crashing.
        broken_links = 0

    broken_links = max(broken_links, 0)
    if broken_links > 0:
        # Singular/plural phrasing so a single broken link doesn't
        # read as "Fix 1 broken links."
        link_word = "link" if broken_links == 1 else "links"
        suggestions.append(f"Fix {broken_links} broken {link_word}.")

    # If every check passed, there's nothing to suggest.
    if not suggestions:
        return ["No SEO issues found."]

    return suggestions


if __name__ == "__main__":
    # Quick manual tests.

    # Case 1: everything failing.
    all_failing = {
        "title": {"status": False, "message": "Title missing", "title": None},
        "meta_description": {"status": False, "message": "Meta description missing", "description": None},
        "h1": {"status": False, "message": "No H1 tags found", "h1_tags": []},
        "images": {"status": True, "message": "Image check completed",
                   "total_images": 20, "with_alt": 3, "without_alt": 17},
        "open_graph": {"status": False,
                       "tags": {"og:title": True, "og:description": True,
                                "og:image": False, "og:url": False},
                       "missing": ["og:image", "og:url"]},
        "links": {"total": 30, "working": 25, "broken": 5},
    }
    print(generate_suggestions(all_failing))
    # Expected: ["Add a page title.", "Add a meta description.",
    #            "Add at least one H1 tag.", "Add alt text to 17 images.",
    #            "Add og:image for better social sharing previews.",
    #            "Add og:url for better social sharing previews.",
    #            "Fix 5 broken links."]

    # Case 2: everything passing, including Open Graph and links.
    all_passing = {
        "title": {"status": True, "message": "Title found", "title": "Example"},
        "meta_description": {"status": True, "message": "Meta description found", "description": "Example."},
        "h1": {"status": True, "message": "H1 tags found", "h1_tags": ["Example heading"]},
        "images": {"status": True, "message": "Image check completed",
                   "total_images": 5, "with_alt": 5, "without_alt": 0},
        "open_graph": {"status": True,
                       "tags": {"og:title": True, "og:description": True,
                                "og:image": True, "og:url": True},
                       "missing": []},
        "links": {"total": 10, "working": 10, "broken": 0},
    }
    print(generate_suggestions(all_passing))
    # Expected: ["No SEO issues found."]

    # Case 3: missing/empty input.
    print(generate_suggestions(None))
    print(generate_suggestions({}))
    # Expected: ["No SEO issues found."] for both

    # Case 4: results with no "open_graph" key at all (backwards
    # compatibility with code that hasn't been updated to include it).
    no_og_key = {
        "title": {"status": True, "title": "Example"},
        "meta_description": {"status": True, "description": "Example."},
        "h1": {"status": True, "h1_tags": ["Example heading"]},
        "images": {"status": True, "total_images": 0, "with_alt": 0, "without_alt": 0},
    }
    print(generate_suggestions(no_og_key))
    # Expected: ["No SEO issues found."]
