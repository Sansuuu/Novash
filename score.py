"""
score.py

Dedicated, transparent SEO scoring engine for Novash.

This module has exactly one job: turn the results of every SEO check
into a single numeric score, plus a transparent breakdown of how that
score was earned. It performs no I/O of its own - no printing, no
network requests, no file access - it only calculates and returns data.
"""

# --- Scoring weights ---
# Each category contributes up to this many raw points. These sum to
# 100 by design, so the final score maps directly to the raw total -
# no rescaling distortion.
#
# History: the original seven checks (everything except "links")
# summed to 90 and were rescaled up to 100. Adding a 10-point "links"
# category happened to bring the total to exactly 100 on its own.
# Adding "canonical" (5 points) meant the other eight weights below
# were each scaled down by 5% (multiplied by 0.95) from their
# previous values, so every existing category gives up a small,
# proportional slice of its weight rather than "canonical" simply
# being bolted on top of an already-100-point total. This preserves
# each category's *relative* importance to the others while making
# room for canonical's 5 points:
#   title:            15   -> 14.25
#   meta_description:  15   -> 14.25
#   h1:                10   -> 9.5
#   images:            15   -> 14.25
#   robots:            10   -> 9.5
#   sitemap:           10   -> 9.5
#   open_graph:        15   -> 14.25
#   links:             10   -> 9.5
#   canonical:          -   -> 5 (new)
# 57.0 (four 14.25s) + 38.0 (four 9.5s) + 5 = 100.0 exactly.
#
# TOTAL_WEIGHT below is still computed dynamically from this dict
# rather than hardcoded, so WEIGHTS can be edited again later without
# also having to update a separate constant by hand.
WEIGHTS = {
    "title": 14.25,
    "meta_description": 14.25,
    "h1": 9.5,
    "images": 14.25,
    "robots": 9.5,
    "sitemap": 9.5,
    "open_graph": 14.25,
    "links": 9.5,
    "canonical": 5,
}

# Sum of all weights above (100). Computed once here rather than
# hardcoded, so WEIGHTS can be edited without also having to update a
# separate constant by hand.
TOTAL_WEIGHT = sum(WEIGHTS.values())

# The four Open Graph tags Novash checks for (see og_checker.py).
# Used as a fallback list if a caller's "open_graph" result doesn't
# include the "tags" dict for some reason.
OG_TAG_NAMES = ("og:title", "og:description", "og:image", "og:url")


def _pass_fail_points(check_result, weight):
    """
    Score a simple pass/fail check: full weight if status is True,
    zero otherwise.

    Used for title, meta_description, h1, robots, and sitemap - each
    of these either exists on the page or it doesn't, with no partial
    credit in between.

    Args:
        check_result (dict | None): The result dict from the matching
            checker function (e.g. check_title()). Expected to have a
            "status" key, but this is guarded against being missing
            or malformed.
        weight (int | float): The maximum points this check is worth.

    Returns:
        float: Either `weight` (check passed) or 0 (check failed or
        the result was missing/malformed).
    """
    # .get(..., {}) handles check_result being None or missing
    # entirely; .get("status", False) then handles it being a dict
    # without a "status" key. Either way, defaults to "failed".
    if not isinstance(check_result, dict):
        return 0.0

    return float(weight) if check_result.get("status", False) else 0.0


def _images_points(images_result, weight):
    """
    Score the image alt-text check proportionally.

    Full points if every image has alt text, partial points scaled
    by the percentage that do, and full points (no penalty) if the
    page simply has no images at all - a page with zero images isn't
    doing anything wrong, so it shouldn't be punished for it.

    Args:
        images_result (dict | None): The result dict from
            check_image_alts(), expected to contain "total_images"
            and "with_alt" counts.
        weight (int | float): The maximum points this check is worth.

    Returns:
        float: Points earned, between 0 and `weight`.
    """
    if not isinstance(images_result, dict):
        return 0.0

    # Coerce to int defensively - if these values are ever missing,
    # None, or an unexpected type, fall back to 0 rather than raising.
    try:
        total_images = int(images_result.get("total_images", 0) or 0)
    except (TypeError, ValueError):
        total_images = 0

    try:
        with_alt = int(images_result.get("with_alt", 0) or 0)
    except (TypeError, ValueError):
        with_alt = 0

    # Guard against division by zero: a page with no images at all
    # has nothing to penalize, so it earns full marks for this
    # category rather than 0/0 being treated as "everything failed".
    if total_images <= 0:
        return float(weight)

    # Clamp with_alt into a sane range in case of bad/negative data,
    # then scale the weight by what fraction of images have alt text.
    with_alt = max(0, min(with_alt, total_images))
    return weight * (with_alt / total_images)


def _open_graph_points(og_result, weight):
    """
    Score the Open Graph check proportionally, based on how many of
    the four required tags (og:title, og:description, og:image,
    og:url) are present.

    Args:
        og_result (dict | None): The result dict from
            check_open_graph(), expected to contain a "tags" dict
            mapping each tag name to True/False.
        weight (int | float): The maximum points this check is worth.

    Returns:
        float: Points earned, between 0 and `weight`.
    """
    if not isinstance(og_result, dict):
        return 0.0

    tags = og_result.get("tags")

    if isinstance(tags, dict) and tags:
        # Normal case: use the actual per-tag booleans.
        found_count = sum(1 for is_present in tags.values() if is_present)
        total_tags = len(tags)
    else:
        # Fallback for a malformed/older result shape: derive the
        # count from the "missing" list instead, assuming the
        # standard four tags.
        missing = og_result.get("missing") or []
        total_tags = len(OG_TAG_NAMES)
        found_count = max(total_tags - len(missing), 0)

    # Guard against division by zero - if for some reason there are
    # zero known tags to check, there's nothing to penalize.
    if total_tags <= 0:
        return float(weight)

    return weight * (found_count / total_tags)


def _links_points(links_result, weight):
    """
    Score the broken-links check proportionally, based on the
    percentage of checked links that are working.

    Full points if there are no broken links (or no links at all -
    a page with zero outbound links isn't doing anything wrong),
    partial points scaled by the percentage that work. Individual
    broken links are never deducted one-by-one; only the overall
    working percentage matters.

    Args:
        links_result (dict | None): The result dict from
            check_links(), expected to contain "total" and "working"
            counts.
        weight (int | float): The maximum points this check is worth.

    Returns:
        float: Points earned, between 0 and `weight`.
    """
    if not isinstance(links_result, dict):
        return 0.0

    # Coerce to int defensively - if these values are ever missing,
    # None, or an unexpected type, fall back to 0 rather than raising.
    try:
        total_links = int(links_result.get("total", 0) or 0)
    except (TypeError, ValueError):
        total_links = 0

    try:
        working_links = int(links_result.get("working", 0) or 0)
    except (TypeError, ValueError):
        working_links = 0

    # Guard against division by zero: a page with no links at all
    # (or where the check couldn't run) has nothing to penalize, so
    # it earns full marks for this category.
    if total_links <= 0:
        return float(weight)

    # Clamp working_links into a sane range in case of bad/negative
    # data, then scale the weight by what fraction of links work.
    working_links = max(0, min(working_links, total_links))
    return weight * (working_links / total_links)


def _canonical_points(canonical_result, weight):
    """
    Score the canonical URL check: full weight for exactly one valid
    canonical URL, zero otherwise.

    This is a pass/fail category, not a proportional one - a page
    either has a single, valid canonical URL or it doesn't. This
    function does NOT re-validate the canonical URL itself (no
    network requests, no re-parsing HTML); it only reads the already-
    computed result produced by canonical_checker.check_canonical(),
    which is responsible for all of that validation logic.

    Per canonical_checker.check_canonical()'s contract:
        - "found": True + empty "issues"   -> a single, valid canonical URL
        - "found": False                   -> canonical URL is missing
        - "found": False + an "issues" entry -> canonical URL is invalid
          (e.g. an unusable scheme like javascript:)
        - "found": True + a non-empty "issues" entry -> multiple
          canonical tags were present (the first was used, but this
          is still a problem worth flagging)

    So concretely:
        - Valid single canonical URL (found=True, issues=[])  -> full weight
        - Missing canonical (found=False)                     -> 0
        - Invalid canonical (found=False, issues=[...])        -> 0
        - Multiple canonical tags (found=True, issues=[...])   -> 0

    Args:
        canonical_result (dict | None): The result dict from
            check_canonical(), expected to contain a "found" bool and
            an "issues" list. May be None or absent entirely if the
            caller hasn't been updated to include it yet (older code/
            data) - handled gracefully as 0 points rather than raising.
        weight (int | float): The maximum points this check is worth.

    Returns:
        float: Either `weight` (a single valid canonical URL was
        found) or 0 (missing, invalid, or multiple canonical tags -
        or the result was missing/malformed).
    """
    # Missing/malformed canonical_result (including older callers
    # that don't provide this key at all) is treated as "no usable
    # canonical URL" rather than raising - 0 points, not a crash.
    if not isinstance(canonical_result, dict):
        return 0.0

    found = bool(canonical_result.get("found", False))
    issues = canonical_result.get("issues") or []

    # Full points only when a canonical URL was found AND there are
    # no issues (which covers both "invalid scheme" cases, where
    # found is already False, and "multiple canonical tags" cases,
    # where found can be True but issues is non-empty).
    if found and not issues:
        return float(weight)

    return 0.0


def calculate_score(results):
    """
    Calculate an overall SEO score (out of 100) from the results of
    every Novash check, along with a transparent breakdown of how
    each category contributed.

    Args:
        results (dict): A dict containing the result of each check,
            keyed by category name:
            {
                "title": {"status": bool, ...},
                "meta_description": {"status": bool, ...},
                "h1": {"status": bool, ...},
                "images": {"total_images": int, "with_alt": int,
                           "without_alt": int, ...},
                "robots": {"status": bool, ...},
                "sitemap": {"status": bool, ...},
                "open_graph": {"status": bool,
                               "tags": {"og:title": bool, ...}, ...},
                "links": {"total": int, "working": int,
                          "broken": int, ...},
                "canonical": {"found": bool, "url": str | None,
                              "issues": list[str]},
            }
            Each value is the dict returned by the matching checker
            function (check_title, check_meta_description, check_h1,
            check_image_alts, check_robots, check_sitemap,
            check_open_graph, check_links, check_canonical). Any key
            that's missing or malformed - including "canonical" being
            absent entirely, for callers/data that predate this check
            - is treated as a failing/zero-point result rather than
            raising an error.

    Returns:
        dict: {
            "score": int,          # Final score out of 100 (0-100)
            "max_score": 100,
            "breakdown": {
                "title":           {"earned": float, "possible": float},
                "meta_description":{"earned": float, "possible": float},
                "h1":              {"earned": float, "possible": float},
                "images":          {"earned": float, "possible": float},
                "robots":          {"earned": float, "possible": float},
                "sitemap":         {"earned": float, "possible": float},
                "open_graph":      {"earned": float, "possible": float},
                "links":           {"earned": float, "possible": float},
                "canonical":       {"earned": float, "possible": float},
            }
        }
    """
    # Treat a missing/None results dict as "everything failed" rather
    # than raising - every category will simply score 0 points below.
    if not isinstance(results, dict):
        results = {}

    # --- Score each category individually ---
    # Simple pass/fail categories: full weight or zero, nothing in
    # between.
    title_earned = _pass_fail_points(results.get("title"), WEIGHTS["title"])
    meta_earned = _pass_fail_points(results.get("meta_description"), WEIGHTS["meta_description"])
    h1_earned = _pass_fail_points(results.get("h1"), WEIGHTS["h1"])
    robots_earned = _pass_fail_points(results.get("robots"), WEIGHTS["robots"])
    sitemap_earned = _pass_fail_points(results.get("sitemap"), WEIGHTS["sitemap"])

    # Proportional categories: partial credit based on percentage.
    images_earned = _images_points(results.get("images"), WEIGHTS["images"])
    og_earned = _open_graph_points(results.get("open_graph"), WEIGHTS["open_graph"])
    links_earned = _links_points(results.get("links"), WEIGHTS["links"])

    # Canonical: pass/fail, but with its own rules (see
    # _canonical_points' docstring) rather than a plain "status" key.
    canonical_earned = _canonical_points(results.get("canonical"), WEIGHTS["canonical"])

    # --- Build the transparent breakdown ---
    # Each entry shows exactly how many points were earned out of how
    # many were possible for that category, so nothing about the
    # final score is a black box. Points are rounded to 1 decimal
    # place for readability without losing the "partial credit"
    # nuance (e.g. 8.2 / 14.25 for images).
    breakdown = {
        "title": {"earned": round(title_earned, 1), "possible": WEIGHTS["title"]},
        "meta_description": {"earned": round(meta_earned, 1), "possible": WEIGHTS["meta_description"]},
        "h1": {"earned": round(h1_earned, 1), "possible": WEIGHTS["h1"]},
        "images": {"earned": round(images_earned, 1), "possible": WEIGHTS["images"]},
        "robots": {"earned": round(robots_earned, 1), "possible": WEIGHTS["robots"]},
        "sitemap": {"earned": round(sitemap_earned, 1), "possible": WEIGHTS["sitemap"]},
        "open_graph": {"earned": round(og_earned, 1), "possible": WEIGHTS["open_graph"]},
        "links": {"earned": round(links_earned, 1), "possible": WEIGHTS["links"]},
        "canonical": {"earned": round(canonical_earned, 1), "possible": WEIGHTS["canonical"]},
    }

    # --- Convert the raw total (out of 100) into a score out of 100 ---
    raw_total = (
        title_earned + meta_earned + h1_earned + images_earned
        + robots_earned + sitemap_earned + og_earned + links_earned
        + canonical_earned
    )

    # Guard against division by zero. TOTAL_WEIGHT is a fixed positive
    # constant (100) given the WEIGHTS above, but this keeps the
    # function safe even if WEIGHTS is ever edited down to empty.
    if TOTAL_WEIGHT > 0:
        scaled_score = (raw_total / TOTAL_WEIGHT) * 100
    else:
        scaled_score = 0.0

    # Round to a whole number and clamp into the valid 0-100 range as
    # a final safety net against any floating-point overshoot.
    final_score = max(0, min(round(scaled_score), 100))

    return {
        "score": final_score,
        "max_score": 100,
        "breakdown": breakdown,
    }
