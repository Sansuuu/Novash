"""
schema_checker.py

Checks a page's structured data: <script type="application/ld+json">
blocks, following the Schema.org / JSON-LD conventions search engines
use to build rich results (review stars, breadcrumbs, FAQ dropdowns,
etc.).

Works entirely from an already-parsed BeautifulSoup object - it does
not make any HTTP requests of its own.
"""

import json
from typing import Any, Dict, List, Optional

try:
    # Only used for the type hint below. Guarded in a try/except so
    # this module never fails to import in an environment where bs4
    # isn't installed yet (matching the defensive style used
    # elsewhere in Novash's checkers, e.g. og_checker.py).
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = Any  # type: ignore

# Well-known Schema.org types Novash recognizes by name. This list is
# purely informational/for reference - it is NOT a required set.
# check_schema() never flags a page as failing for lacking any of
# these; missing structured data is a recommendation, not an error
# (see the module-level docstring and check_schema()'s docstring).
COMMON_SCHEMA_TYPES = (
    "Organization",
    "WebSite",
    "WebPage",
    "Article",
    "Product",
    "BreadcrumbList",
    "LocalBusiness",
    "Person",
    "FAQPage",
    "HowTo",
)


def _empty_result() -> Dict[str, Any]:
    """
    Build the result returned when there is no structured data to
    analyze at all: `soup` is None, isn't a usable BeautifulSoup-like
    object, or the page has zero JSON-LD <script> tags.
    """
    return {
        "status": "missing",
        "count": 0,
        "schemas": [],
        "missing": [],
        "issues": [],
    }


def _extract_type(schema_object: Dict[str, Any]) -> Optional[str]:
    """
    Extract a human-readable @type value from a single JSON-LD
    object.

    Args:
        schema_object (dict): A single parsed JSON-LD object (e.g.
            {"@type": "Organization", "name": "..."}).

    Returns:
        str | None: The type name, or a comma-joined list of names if
        @type is an array (e.g. ["Product", "Thing"] becomes
        "Product, Thing"). None if @type is missing, empty, or not a
        recognizable string/list.
    """
    type_value = schema_object.get("@type")

    if isinstance(type_value, str):
        stripped = type_value.strip()
        return stripped if stripped else None

    if isinstance(type_value, list) and type_value:
        # Coerce every entry to a string defensively - @type should
        # only ever contain strings, but malformed JSON-LD in the
        # wild sometimes doesn't follow the spec.
        names = [str(v).strip() for v in type_value if str(v).strip()]
        return ", ".join(names) if names else None

    return None


def _flatten_json_ld(node: Any) -> List[Dict[str, Any]]:
    """
    Recursively flatten a parsed JSON-LD value into a list of
    individual schema objects (plain dicts).

    Handles the three shapes JSON-LD commonly appears in:
        - a single object:      {"@type": "Organization", ...}
        - an array of objects:  [{"@type": "Organization"}, {"@type": "WebSite"}]
        - a @graph wrapper:      {"@context": "...", "@graph": [ {...}, {...} ]}

    @graph structures can in principle nest further arrays/objects,
    so this recurses rather than assuming a fixed depth. JSON is a
    finite, acyclic tree, so this always terminates.

    Args:
        node (Any): A parsed JSON value (dict, list, or something
            else entirely if the JSON-LD content wasn't actually an
            object/array, e.g. a bare string or number).

    Returns:
        list[dict]: Every individual schema object found. Non-dict,
        non-list values contribute nothing (they aren't valid schema
        objects) rather than raising.
    """
    if isinstance(node, list):
        objects: List[Dict[str, Any]] = []
        for item in node:
            objects.extend(_flatten_json_ld(item))
        return objects

    if isinstance(node, dict):
        graph = node.get("@graph")
        if isinstance(graph, list):
            objects = []
            for item in graph:
                objects.extend(_flatten_json_ld(item))
            # A @graph wrapper can, uncommonly, also declare its own
            # @type alongside @graph - include it too rather than
            # silently dropping that data.
            if "@type" in node:
                objects.append(node)
            return objects

        # A plain object (no @graph) - it's a single schema object,
        # even if it turns out to have no @type of its own (that gets
        # flagged separately as an issue).
        return [node]

    # Anything else (a bare string, number, bool, None) isn't a valid
    # schema object.
    return []


def check_schema(soup: Optional["BeautifulSoup"]) -> Dict[str, Any]:
    """
    Check a page's structured data (JSON-LD <script> blocks).

    Args:
        soup (BeautifulSoup | None): Parsed HTML of the page, as
            returned by crawler.get_page(). May be None if the page
            failed to load/parse, or anything else if an invalid
            value was passed in by mistake - both are handled
            gracefully rather than raising.

    Returns:
        dict: {
            "status": str,
                # "found"   - at least one JSON-LD block produced at
                #              least one usable schema object (even
                #              if imperfect - see "issues" below)
                # "missing" - no <script type="application/ld+json">
                #              blocks were found on the page at all
                #              (or soup was None/invalid). This is a
                #              RECOMMENDATION, not a fatal error - see
                #              note below.
                # "invalid" - one or more JSON-LD blocks were present,
                #              but NONE of them yielded any usable
                #              schema data (e.g. every block is
                #              malformed JSON or empty)
            "count": int,
                # Number of <script type="application/ld+json">
                # blocks found on the page (raw block count, before
                # any array/@graph expansion).
            "schemas": list[dict],
                # One entry per resolved schema object - a single
                # block can contribute multiple entries if it
                # contains an array or a @graph structure. Each entry:
                #   {"type": str | None, "valid_json": bool}
                # "type" is the @type value (or a comma-joined string
                # if @type was itself a list), or None if @type is
                # missing/malformed. "valid_json" is False only for
                # blocks that couldn't be parsed as JSON at all (in
                # which case "type" is always None too).
            "missing": list[str],
                # Intentionally always empty. Per Schema.org's own
                # guidance and this checker's design, NO specific
                # schema type is ever required, so nothing is ever
                # reported as "missing" in a mandatory sense. This
                # field is kept in the result for structural
                # consistency with Novash's other checkers (and in
                # case a future version wants to surface soft
                # recommendations here) rather than removed outright.
            "issues": list[str],
                # Human-readable problems detected: invalid/malformed
                # JSON, empty blocks, objects with no @type, and
                # duplicate schema types. Purely informational; does
                # NOT affect "status" beyond the found/invalid
                # distinction described above.
        }
        The whole structure is plain dicts/lists/strings/bools/None,
        so it's always JSON-serializable.

    Note on philosophy: a page having zero structured data is common
    and often perfectly fine - it is reported as "missing" (a
    recommendation to consider adding it), never as an "invalid" or
    fatal result. Only structured data that was actually *attempted*
    but is completely unusable is reported as "invalid".
    """
    if soup is None:
        return _empty_result()

    try:
        script_tags = soup.find_all("script")
    except (TypeError, AttributeError):
        # Something other than a real BeautifulSoup object was passed
        # in (e.g. a plain string) - treat the same as "nothing to
        # check" rather than crashing the caller.
        return _empty_result()

    # Match the JSON-LD script type case-insensitively - real-world
    # HTML occasionally varies casing (e.g. "Application/Ld+Json"),
    # and browsers/tools are lenient about it, so we are too.
    ld_json_tags = [
        tag for tag in script_tags
        if (tag.get("type") or "").strip().lower() == "application/ld+json"
    ]

    count = len(ld_json_tags)
    if count == 0:
        return _empty_result()

    schemas: List[Dict[str, Any]] = []
    issues: List[str] = []
    found_usable_data = False

    for index, tag in enumerate(ld_json_tags, start=1):
        # get_text() (rather than tag.string) safely handles a tag
        # with multiple internal text nodes/comments, returning "" if
        # there's nothing there instead of None.
        content = (tag.get_text() or "").strip()

        if not content:
            issues.append(f"JSON-LD block {index} is empty (no content).")
            schemas.append({"type": None, "valid_json": False})
            continue

        try:
            parsed = json.loads(content)
        except (ValueError, TypeError) as e:
            # json.JSONDecodeError is a subclass of ValueError, so
            # this also catches it. Malformed JSON must never crash
            # the caller - it's simply reported as an issue.
            issues.append(f"JSON-LD block {index} contains invalid JSON and could not be parsed.")
            schemas.append({"type": None, "valid_json": False})
            continue

        objects = _flatten_json_ld(parsed)

        if not objects:
            # Valid JSON, but nothing usable came out of it (e.g. the
            # content was just "{}", "[]", or a bare string/number).
            issues.append(f"JSON-LD block {index} is valid JSON but contains no schema data.")
            schemas.append({"type": None, "valid_json": True})
            continue

        for obj in objects:
            if not isinstance(obj, dict):
                # A non-object entry inside an array/@graph (e.g. a
                # bare string) isn't a valid schema object - skip it
                # rather than crashing or fabricating a fake entry.
                issues.append(f"JSON-LD block {index} contains a non-object entry that was skipped.")
                continue

            type_value = _extract_type(obj)
            if type_value is None:
                issues.append(f"JSON-LD block {index} has an object with no '@type' field.")

            schemas.append({"type": type_value, "valid_json": True})
            found_usable_data = True

    # --- Duplicate schema type detection ---
    # Having several DIFFERENT types together (Organization + WebSite
    # + BreadcrumbList, say) is completely normal and not flagged.
    # The same type appearing more than once is what's worth calling
    # out, since it usually indicates accidental duplication.
    type_counts: Dict[str, int] = {}
    for schema in schemas:
        type_name = schema["type"]
        if type_name and schema["valid_json"]:
            type_counts[type_name] = type_counts.get(type_name, 0) + 1

    for type_name, occurrences in type_counts.items():
        if occurrences > 1:
            issues.append(
                f"Schema type '{type_name}' appears {occurrences} times; "
                "consider consolidating duplicate schema blocks."
            )

    status = "found" if found_usable_data else "invalid"

    return {
        "status": status,
        "count": count,
        "schemas": schemas,
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
        print(_json.dumps(check_schema(soup), indent=2))
        print()

    # Case 1: a single, valid Organization schema.
    _run(
        "Case 1 - single valid Organization schema",
        """
        <html><head>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Organization", "name": "Example Co"}
        </script>
        </head></html>
        """,
    )

    # Case 2: an array of two schema objects in one block.
    _run(
        "Case 2 - array of two schemas in one block",
        """
        <html><head>
        <script type="application/ld+json">
        [
            {"@context": "https://schema.org", "@type": "Organization", "name": "Example Co"},
            {"@context": "https://schema.org", "@type": "WebSite", "name": "Example"}
        ]
        </script>
        </head></html>
        """,
    )

    # Case 3: a @graph structure.
    _run(
        "Case 3 - @graph structure",
        """
        <html><head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "WebPage", "name": "Home"},
                {"@type": "BreadcrumbList", "itemListElement": []}
            ]
        }
        </script>
        </head></html>
        """,
    )

    # Case 4: malformed JSON.
    _run(
        "Case 4 - malformed JSON",
        """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Organization", "name": "Missing closing brace"
        </script>
        </head></html>
        """,
    )

    # Case 5: empty JSON-LD block.
    _run(
        "Case 5 - empty block",
        """
        <html><head>
        <script type="application/ld+json"></script>
        </head></html>
        """,
    )

    # Case 6: valid JSON, but object has no @type.
    _run(
        "Case 6 - missing @type",
        """
        <html><head>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "name": "No type here"}
        </script>
        </head></html>
        """,
    )

    # Case 7: duplicate schema types across two blocks.
    _run(
        "Case 7 - duplicate schema types",
        """
        <html><head>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Organization", "name": "First"}
        </script>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Organization", "name": "Second"}
        </script>
        </head></html>
        """,
    )

    # Case 8: no structured data at all - "missing", not an error.
    _run(
        "Case 8 - no structured data at all",
        "<html><head><title>No JSON-LD here</title></head></html>",
    )

    # Case 9: one valid block and one malformed block together.
    _run(
        "Case 9 - one valid, one malformed",
        """
        <html><head>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Product", "name": "Widget"}
        </script>
        <script type="application/ld+json">
        this is not json at all
        </script>
        </head></html>
        """,
    )

    # Case 10: soup is None (failed crawl).
    print("Case 10 - soup is None:")
    print(_json.dumps(check_schema(None), indent=2))
    print()

    # Case 11: something invalid passed in.
    print("Case 11 - invalid input (a plain string):")
    print(_json.dumps(check_schema("not a soup object"), indent=2))
