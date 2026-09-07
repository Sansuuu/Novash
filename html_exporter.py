"""
html_exporter.py

Generates a standalone, self-contained HTML report from a completed
Novash scan.

The output file has no external dependencies of any kind: no
JavaScript, no external CSS/font/image files, no CDN links. Every
style is inlined in a single <style> block, so the file can be
opened directly in a browser, emailed as an attachment, or archived
indefinitely without breaking.
"""

import html
import os


def _esc(value):
    """
    Safely convert any value to an HTML-escaped string.

    Every piece of text that ultimately came from a scanned website
    (page titles, meta descriptions, H1 text, URLs, etc.) is
    "user-controlled" from Novash's point of view - it could contain
    literal HTML, script tags, or other markup. This function makes
    sure that text is always escaped before being inserted into the
    report, so it's displayed as plain text rather than being
    interpreted as HTML.

    Args:
        value: Any value - str, int, None, etc.

    Returns:
        str: An HTML-safe string. None becomes an empty string.
    """
    if value is None:
        return ""
    # html.escape() converts &, <, >, " and ' into their HTML-safe
    # entity equivalents (e.g. "<" becomes "&lt;").
    return html.escape(str(value))


def _status_badge(state):
    """
    Build the small colored status badge shown on each report card.

    Args:
        state (str): One of "passed", "warning", or "failed".

    Returns:
        str: An HTML <span> element styled according to the state.
    """
    labels = {
        "passed": "Passed",
        "warning": "Warning",
        "failed": "Failed",
    }
    label = labels.get(state, "Unknown")
    # The `state` value itself is always one of our own three known
    # strings (never user-controlled), so no escaping is needed for
    # the CSS class name - but the label text still goes through
    # _esc() for consistency/safety.
    return f'<span class="badge badge-{state}">{_esc(label)}</span>'


def _card(title, state, body_html):
    """
    Wrap a section's content in a consistently styled "card" with a
    header, status badge, and body.

    Args:
        title (str): The card's heading (e.g. "Title", "Images").
            Not user-controlled (always a hardcoded section name),
            but still escaped for consistency.
        state (str): "passed", "warning", or "failed" - controls the
            card's left border color and badge.
        body_html (str): Pre-built, already-escaped HTML for the
            card's content.

    Returns:
        str: The complete card as an HTML string.
    """
    return f"""
    <div class="card card-{state}">
        <div class="card-header">
            <h2>{_esc(title)}</h2>
            {_status_badge(state)}
        </div>
        <div class="card-body">
            {body_html}
        </div>
    </div>
    """


def _score_state(score):
    """
    Map a numeric score (0-100) to a visual state, mirroring the
    same thresholds used elsewhere in Novash's CLI report.

    Args:
        score (int | float): The score to classify.

    Returns:
        str: "passed" (>=90), "warning" (70-89), or "failed" (<70).
    """
    if score >= 90:
        return "passed"
    elif score >= 70:
        return "warning"
    return "failed"


def _build_title_section(title_result):
    """Build the HTML card for the title check."""
    title_result = title_result if isinstance(title_result, dict) else {}
    passed = bool(title_result.get("status", False))
    state = "passed" if passed else "failed"

    if passed:
        body = f"<p>Page title:</p><p class='detail'>{_esc(title_result.get('title'))}</p>"
    else:
        body = "<p>No page title was found.</p>"

    return _card("Page Title", state, body)


def _build_meta_section(meta_result):
    """Build the HTML card for the meta description check."""
    meta_result = meta_result if isinstance(meta_result, dict) else {}
    passed = bool(meta_result.get("status", False))
    state = "passed" if passed else "failed"

    if passed:
        body = f"<p>Meta description:</p><p class='detail'>{_esc(meta_result.get('description'))}</p>"
    else:
        body = "<p>No meta description was found.</p>"

    return _card("Meta Description", state, body)


def _build_h1_section(h1_result):
    """Build the HTML card for the H1 tag check."""
    h1_result = h1_result if isinstance(h1_result, dict) else {}
    passed = bool(h1_result.get("status", False))
    state = "passed" if passed else "failed"
    h1_tags = h1_result.get("h1_tags") or []

    if passed and h1_tags:
        items = "".join(f"<li>{_esc(tag)}</li>" for tag in h1_tags)
        body = f"<p>H1 tags found:</p><ul>{items}</ul>"
    else:
        body = "<p>No meaningful H1 tag was found.</p>"

    return _card("H1 Tags", state, body)


def _build_images_section(images_result):
    """Build the HTML card for the image alt-text check."""
    images_result = images_result if isinstance(images_result, dict) else {}

    try:
        total = int(images_result.get("total_images", 0) or 0)
    except (TypeError, ValueError):
        total = 0
    try:
        with_alt = int(images_result.get("with_alt", 0) or 0)
    except (TypeError, ValueError):
        with_alt = 0
    try:
        without_alt = int(images_result.get("without_alt", 0) or 0)
    except (TypeError, ValueError):
        without_alt = 0

    # A page with no images has nothing wrong with it. If every
    # image has alt text, that's a clean pass. If every single image
    # is missing alt text, that's a full failure. Anything in
    # between is a partial/warning state.
    if total == 0 or without_alt == 0:
        state = "passed"
    elif with_alt == 0:
        state = "failed"
    else:
        state = "warning"

    body = (
        f"<p>Total images: <strong>{total}</strong></p>"
        f"<p>With alt text: <strong>{with_alt}</strong></p>"
        f"<p>Without alt text: <strong>{without_alt}</strong></p>"
    )

    return _card("Images / Alt Text", state, body)


def _build_robots_section(robots_result):
    """Build the HTML card for the robots.txt check."""
    robots_result = robots_result if isinstance(robots_result, dict) else {}
    passed = bool(robots_result.get("status", False))
    state = "passed" if passed else "failed"
    body = "<p>robots.txt found.</p>" if passed else "<p>robots.txt is missing.</p>"
    return _card("robots.txt", state, body)


def _build_sitemap_section(sitemap_result):
    """Build the HTML card for the sitemap.xml check."""
    sitemap_result = sitemap_result if isinstance(sitemap_result, dict) else {}
    passed = bool(sitemap_result.get("status", False))
    state = "passed" if passed else "failed"
    sitemap_url = sitemap_result.get("url")

    body = "<p>Sitemap found.</p>" if passed else "<p>Sitemap is missing.</p>"
    if sitemap_url:
        body += f"<p class='detail'>URL: {_esc(sitemap_url)}</p>"

    return _card("Sitemap", state, body)


def _build_open_graph_section(og_result):
    """Build the HTML card for the Open Graph tags check."""
    og_result = og_result if isinstance(og_result, dict) else {}
    tags = og_result.get("tags") or {}
    missing = og_result.get("missing") or []

    found_count = sum(1 for is_present in tags.values() if is_present) if tags else 0
    total_count = len(tags) if tags else 4

    if not missing:
        state = "passed"
    elif found_count == 0:
        state = "failed"
    else:
        state = "warning"

    if not missing:
        body = "<p>All Open Graph tags found.</p>"
    else:
        items = "".join(f"<li>{_esc(tag)}</li>" for tag in missing)
        body = (
            f"<p>{found_count}/{total_count} Open Graph tags found. Missing:</p>"
            f"<ul>{items}</ul>"
        )

    return _card("Open Graph", state, body)


def _build_twitter_section(twitter_result):
    """
    Build the HTML card for the Twitter/X Card check.

    Mirrors cli.py's terminal treatment exactly: "complete" is a
    pass, "incomplete" is a warning (some primary tags present),
    and "missing" is treated as a genuine failure (red), matching
    cli.py's choice to NOT soften this one the way Schema/Favicon are
    softened - Twitter Cards are checked for the same 4 primary tags
    Open Graph requires, so the same severity applies.
    """
    twitter_result = twitter_result if isinstance(twitter_result, dict) else {}
    status = twitter_result.get("status", "missing")
    missing = twitter_result.get("missing") or []
    issues = twitter_result.get("issues") or []

    if status == "complete":
        state = "passed"
        body = "<p>Twitter/X Card complete.</p>"
    elif status == "incomplete":
        state = "warning"
        items = "".join(f"<li>{_esc(tag)}</li>" for tag in missing)
        body = f"<p>Twitter/X Card incomplete. Missing:</p><ul>{items}</ul>"
    else:
        state = "failed"
        body = "<p>No Twitter/X Card tags found.</p>"

    if issues:
        issue_items = "".join(f"<li>{_esc(issue)}</li>" for issue in issues)
        body += f"<p>Issues:</p><ul>{issue_items}</ul>"

    return _card("Twitter / X Card", state, body)


def _build_schema_section(schema_result):
    """
    Build the HTML card for the Structured Data (Schema.org / JSON-LD)
    check.

    Per Novash's design, missing structured data is a recommendation,
    not a failure - "missing" uses the warning (yellow) state here,
    matching cli.py's terminal treatment, rather than the failed
    (red) state used for most other missing checks.
    """
    schema_result = schema_result if isinstance(schema_result, dict) else {}
    status = schema_result.get("status", "missing")
    count = schema_result.get("count", 0)
    schemas = schema_result.get("schemas") or []
    issues = schema_result.get("issues") or []

    if status == "found":
        state = "passed"
        found_types = [s.get("type") for s in schemas if isinstance(s, dict) and s.get("type")]
        body = f"<p>Structured data found ({_esc(count)} block(s)).</p>"
        if found_types:
            items = "".join(f"<li>{_esc(t)}</li>" for t in found_types)
            body += f"<ul>{items}</ul>"
    elif status == "invalid":
        state = "failed"
        body = "<p>Structured data present but invalid.</p>"
    else:
        state = "warning"
        body = "<p>No structured data found (recommended, not required).</p>"

    if issues:
        issue_items = "".join(f"<li>{_esc(issue)}</li>" for issue in issues)
        body += f"<p>Issues:</p><ul>{issue_items}</ul>"

    return _card("Structured Data", state, body)


def _build_favicon_section(favicon_result):
    """
    Build the HTML card for the favicon check.

    Per Novash's design, a missing or invalid favicon is a low-weight
    website-quality recommendation, not a serious SEO problem - both
    "missing" and "invalid" use the warning (yellow) state here,
    matching cli.py's terminal treatment. Only "found" uses the
    passed (green) state.
    """
    favicon_result = favicon_result if isinstance(favicon_result, dict) else {}
    status = favicon_result.get("status", "missing")
    icons = favicon_result.get("icons") or []
    issues = favicon_result.get("issues") or []

    if status == "found":
        state = "passed"
        primary = next(
            (icon for icon in icons if icon.get("rel") == ["icon"] and icon.get("href")),
            None,
        )
        if primary:
            body = f"<p>Favicon found:</p><p class='detail'>{_esc(primary['href'])}</p>"
        else:
            body = "<p>Favicon found.</p>"
    elif status == "invalid":
        state = "warning"
        body = "<p>Favicon declared but not usable (recommendation).</p>"
    else:
        state = "warning"
        body = "<p>No favicon found (recommendation).</p>"

    if issues:
        issue_items = "".join(f"<li>{_esc(issue)}</li>" for issue in issues)
        body += f"<p>Issues:</p><ul>{issue_items}</ul>"

    return _card("Favicon", state, body)


def _build_canonical_section(canonical_result):
    """Build the HTML card for the canonical URL check."""
    canonical_result = canonical_result if isinstance(canonical_result, dict) else {}
    found = bool(canonical_result.get("found", False))
    url = canonical_result.get("url")
    issues = canonical_result.get("issues") or []

    if found and not issues:
        state = "passed"
        body = f"<p>Canonical URL found:</p><p class='detail'>{_esc(url)}</p>"
    elif found:
        # found=True but with issues (e.g. multiple canonical tags) -
        # the first tag is still usable, so this is a warning rather
        # than an outright failure.
        state = "warning"
        body = f"<p>Canonical URL found:</p><p class='detail'>{_esc(url)}</p>"
    else:
        state = "failed"
        body = "<p>No canonical URL found.</p>"

    if issues:
        issue_items = "".join(f"<li>{_esc(issue)}</li>" for issue in issues)
        body += f"<p>Issues:</p><ul>{issue_items}</ul>"

    return _card("Canonical URL", state, body)


def _build_links_section(links_result):
    """Build the HTML card for the broken-links check."""
    links_result = links_result if isinstance(links_result, dict) else {}

    try:
        total = int(links_result.get("total", 0) or 0)
    except (TypeError, ValueError):
        total = 0
    try:
        working = int(links_result.get("working", 0) or 0)
    except (TypeError, ValueError):
        working = 0
    try:
        broken = int(links_result.get("broken", 0) or 0)
    except (TypeError, ValueError):
        broken = 0

    if total == 0 or broken == 0:
        state = "passed"
    elif working == 0:
        state = "failed"
    else:
        state = "warning"

    body = (
        f"<p>Total links: <strong>{total}</strong></p>"
        f"<p>Working: <strong>{working}</strong></p>"
        f"<p>Broken: <strong>{broken}</strong></p>"
    )

    if broken > 0:
        broken_links = [
            link for link in (links_result.get("links") or [])
            if isinstance(link, dict) and link.get("status") == "broken"
        ]
        if broken_links:
            items = "".join(
                f"<li>{_esc(link.get('url'))} "
                f"&rarr; {_esc(link.get('status_code') if link.get('status_code') is not None else 'no response')}"
                f"</li>"
                for link in broken_links
            )
            body += f"<p>Broken links:</p><ul>{items}</ul>"

    # Link composition analysis (internal/external, anchor text
    # quality, etc.) - purely additive detail from link_checker.py's
    # "analysis" field, if present. Older report data without this
    # key simply omits this block rather than raising.
    analysis = links_result.get("analysis")
    if isinstance(analysis, dict) and analysis:
        body += (
            "<p>Link analysis:</p>"
            "<ul>"
            f"<li>Total links found: {_esc(analysis.get('total_links', 0))}</li>"
            f"<li>Internal: {_esc(analysis.get('internal_links', 0))} / "
            f"External: {_esc(analysis.get('external_links', 0))}</li>"
            f"<li>Relative: {_esc(analysis.get('relative_links', 0))} / "
            f"Absolute: {_esc(analysis.get('absolute_links', 0))}</li>"
            f"<li>Empty href: {_esc(analysis.get('empty_href', 0))}</li>"
            f"<li>JavaScript links: {_esc(analysis.get('javascript_links', 0))}</li>"
            f"<li>Mailto: {_esc(analysis.get('mailto_links', 0))} / "
            f"Tel: {_esc(analysis.get('tel_links', 0))}</li>"
            f"<li>Descriptive anchor text: {_esc(analysis.get('descriptive_text', 0))}</li>"
            f"<li>Empty anchor text: {_esc(analysis.get('empty_text', 0))}</li>"
            f"<li>Generic anchor text (e.g. \"click here\"): {_esc(analysis.get('generic_text', 0))}</li>"
            "</ul>"
        )

    return _card("Links", state, body)


def _build_score_breakdown(breakdown):
    """
    Build the HTML for the score breakdown table, including a small
    proportional progress bar per category.
    """
    breakdown = breakdown if isinstance(breakdown, dict) else {}

    if not breakdown:
        return "<p>No score breakdown available.</p>"

    rows = []
    for category, values in breakdown.items():
        if not isinstance(values, dict):
            continue

        try:
            earned = float(values.get("earned", 0) or 0)
        except (TypeError, ValueError):
            earned = 0.0
        try:
            possible = float(values.get("possible", 0) or 0)
        except (TypeError, ValueError):
            possible = 0.0

        # Guard against division by zero for the progress bar width.
        percent = (earned / possible * 100) if possible > 0 else 0
        percent = max(0, min(percent, 100))

        if percent >= 90:
            bar_state = "passed"
        elif percent >= 50:
            bar_state = "warning"
        else:
            bar_state = "failed"

        # Category names come from Novash's own internal dict keys
        # (e.g. "meta_description"), not from the scanned website, so
        # this is safe text, but still escaped for consistency.
        display_name = _esc(category.replace("_", " ").title())

        rows.append(f"""
        <div class="breakdown-row">
            <div class="breakdown-label">{display_name}</div>
            <div class="breakdown-bar-track">
                <div class="breakdown-bar-fill breakdown-{bar_state}" style="width:{percent:.0f}%;"></div>
            </div>
            <div class="breakdown-value">{earned:g} / {possible:g}</div>
        </div>
        """)

    return "".join(rows)


def _build_suggestions_section(suggestions):
    """Build the HTML card for the suggestions list."""
    suggestions = suggestions if isinstance(suggestions, list) else []

    if not suggestions or suggestions == ["No SEO issues found."]:
        state = "passed"
        body = "<p>&#9989; No SEO issues found.</p>"
    else:
        state = "warning"
        items = "".join(f"<li>{_esc(s)}</li>" for s in suggestions)
        body = f"<ul>{items}</ul>"

    return _card("Suggestions", state, body)


# The full CSS for the report, inlined so the output file has zero
# external dependencies. Kept as one constant so it's easy to review
# and edit in one place.
_CSS = """
* { box-sizing: border-box; }
body {
    margin: 0;
    padding: 0;
    background: #f4f6f8;
    color: #1f2933;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.5;
}
.container {
    max-width: 900px;
    margin: 0 auto;
    padding: 24px 16px 64px;
}
header.masthead {
    text-align: center;
    padding: 32px 16px;
}
header.masthead h1 {
    margin: 0 0 4px;
    font-size: 28px;
    letter-spacing: 0.5px;
}
header.masthead p.website {
    margin: 0;
    color: #52606d;
    word-break: break-all;
}
.score-panel {
    text-align: center;
    border-radius: 16px;
    padding: 32px 16px;
    margin: 24px 0;
    color: #ffffff;
}
.score-panel.passed { background: #1f9d55; }
.score-panel.warning { background: #d69e2e; }
.score-panel.failed { background: #c53030; }
.score-panel .score-number {
    font-size: 56px;
    font-weight: 700;
    line-height: 1;
}
.score-panel .score-label {
    font-size: 16px;
    opacity: 0.9;
    margin-top: 4px;
}
.breakdown {
    background: #ffffff;
    border-radius: 12px;
    padding: 16px 20px;
    margin: 24px 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.breakdown h2 {
    margin-top: 0;
    font-size: 18px;
}
.breakdown-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 10px 0;
}
.breakdown-label {
    flex: 0 0 140px;
    font-size: 14px;
    color: #3e4c59;
}
.breakdown-bar-track {
    flex: 1 1 auto;
    background: #e4e7eb;
    border-radius: 6px;
    height: 10px;
    overflow: hidden;
}
.breakdown-bar-fill {
    height: 100%;
    border-radius: 6px;
}
.breakdown-passed { background: #1f9d55; }
.breakdown-warning { background: #d69e2e; }
.breakdown-failed { background: #c53030; }
.breakdown-value {
    flex: 0 0 70px;
    text-align: right;
    font-size: 13px;
    color: #52606d;
}
.cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px;
    margin-top: 8px;
}
.card {
    background: #ffffff;
    border-radius: 12px;
    padding: 16px 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    border-left: 6px solid #cbd2d9;
}
.card-passed { border-left-color: #1f9d55; }
.card-warning { border-left-color: #d69e2e; }
.card-failed { border-left-color: #c53030; }
.card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}
.card-header h2 {
    font-size: 16px;
    margin: 0;
}
.card-body p {
    margin: 6px 0;
    font-size: 14px;
    word-break: break-word;
}
.card-body p.detail {
    color: #52606d;
}
.card-body ul {
    margin: 6px 0;
    padding-left: 20px;
    font-size: 14px;
}
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    color: #ffffff;
    white-space: nowrap;
}
.badge-passed { background: #1f9d55; }
.badge-warning { background: #d69e2e; }
.badge-failed { background: #c53030; }
footer.novash-footer {
    text-align: center;
    color: #9aa5b1;
    font-size: 12px;
    margin-top: 32px;
}
@media (max-width: 480px) {
    header.masthead h1 { font-size: 22px; }
    .score-panel .score-number { font-size: 44px; }
    .breakdown-label { flex-basis: 100px; }
}
"""


def _build_html_document(report_data):
    """
    Assemble the complete standalone HTML document as a string.

    Args:
        report_data (dict): The full Novash report dictionary.

    Returns:
        str: A complete, self-contained HTML document.
    """
    website = report_data.get("website")
    score_result = report_data.get("score") or {}

    try:
        score = int(score_result.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0
    max_score = score_result.get("max_score", 100)
    breakdown = score_result.get("breakdown") or {}

    score_state = _score_state(score)

    sections = "".join([
        _build_title_section(report_data.get("title")),
        _build_meta_section(report_data.get("meta_description")),
        _build_h1_section(report_data.get("h1")),
        _build_images_section(report_data.get("images")),
        # "robots_txt" matches the key Novash's CLI/report modules
        # use when building the report dict; fall back to "robots"
        # in case a caller uses the shorter key instead.
        _build_robots_section(report_data.get("robots_txt") or report_data.get("robots")),
        _build_sitemap_section(report_data.get("sitemap")),
        _build_open_graph_section(report_data.get("open_graph")),
        _build_twitter_section(report_data.get("twitter")),
        _build_schema_section(report_data.get("schema")),
        _build_favicon_section(report_data.get("favicon")),
        _build_canonical_section(report_data.get("canonical")),
        _build_links_section(report_data.get("links")),
    ])

    breakdown_html = _build_score_breakdown(breakdown)
    suggestions_html = _build_suggestions_section(report_data.get("suggestions"))

    # Everything below is either a hardcoded string or has already
    # been escaped by the _build_*_section() helpers above - the
    # only remaining user-controlled values inserted directly here
    # are `website` and the score numbers, both escaped/coerced here.
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Novash SEO Report</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
    <header class="masthead">
        <h1>Novash SEO Report</h1>
        <p class="website">{_esc(website)}</p>
    </header>

    <div class="score-panel {score_state}">
        <div class="score-number">{score}/{_esc(max_score)}</div>
        <div class="score-label">Overall SEO Score</div>
    </div>

    <div class="breakdown">
        <h2>Score Breakdown</h2>
        {breakdown_html}
    </div>

    <div class="cards">
        {sections}
    </div>

    <div class="cards" style="grid-template-columns: 1fr; margin-top: 16px;">
        {suggestions_html}
    </div>

    <footer class="novash-footer">
        Generated by Novash &mdash; open-source SEO checker
    </footer>
</div>
</body>
</html>
"""


def export_html(report_data, filename):
    """
    Generate a standalone HTML report file from a completed Novash
    scan and save it to disk.

    The output file is fully self-contained - no JavaScript, no
    external CSS, fonts, or images - so it works offline and can be
    opened directly in any browser.

    Args:
        report_data (dict): The complete report dictionary already
            produced by Novash, e.g.:
            {
                "website": str,
                "title": {...}, "meta_description": {...},
                "h1": {...}, "images": {...},
                "robots_txt": {...}, "sitemap": {...},
                "open_graph": {...}, "twitter": {...},
                "schema": {...}, "favicon": {...},
                "canonical": {...}, "links": {...},
                "score": {"score": int, "max_score": int,
                          "breakdown": {...}},
                "suggestions": [str, ...],
            }
            Any missing or malformed key is handled gracefully and
            simply renders as a failing/empty state rather than
            raising an error.
        filename (str): Path/name of the HTML file to write, e.g.
            "report.html" or "reports/pypi_report.html".

    Returns:
        bool: True if the file was written successfully, False if
        any error occurred.
    """
    # Basic input validation before doing any real work.
    if not isinstance(report_data, dict):
        return False

    if not isinstance(filename, str) or not filename.strip():
        return False

    filename = filename.strip()

    try:
        html_document = _build_html_document(report_data)
    except Exception:
        # Any unexpected error while building the HTML (malformed
        # report_data shape we didn't anticipate, etc.) results in a
        # clean False rather than a half-written file or a crash.
        return False

    try:
        # If the filename includes a directory path that doesn't
        # exist yet (e.g. "reports/output.html"), create it first so
        # open() doesn't fail with FileNotFoundError.
        directory = os.path.dirname(filename)
        if directory:
            os.makedirs(directory, exist_ok=True)

        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_document)

        return True

    except OSError:
        # Covers permission errors, invalid paths, disk full, etc.
        return False

    except Exception:
        # Final safety net - export_html() must never raise or print,
        # only return True/False.
        return False
