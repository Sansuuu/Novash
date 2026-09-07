"""
cli.py

Novash command-line interface, built with Typer.

Usage:
    python cli.py scan <url>

Example:
    python cli.py scan https://github.com

This file is self-contained: it downloads the page, runs all SEO
checks, calculates the score, and prints the report - all in one
place, using the existing crawler.py, checks.py, and score.py
modules for the underlying logic.
"""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from crawler import get_page
from checks import check_title, check_meta_description, check_h1, check_image_alts
from score import calculate_score
from exporter import export_json
from html_exporter import export_html
from suggestions import generate_suggestions
from robots_checker import check_robots
from sitemap_checker import check_sitemap
from og_checker import check_open_graph
from link_checker import check_links
from canonical_checker import check_canonical
from twitter_checker import check_twitter_cards
from schema_checker import check_schema
from favicon_checker import check_favicon

# --- Version handling for --version ---
# Prefer reading the version from the installed package's metadata
# (which comes from pyproject.toml's `version = "0.1.0"`), so the
# version string lives in exactly one place. Falls back to a
# hardcoded constant only if Novash isn't installed as a package
# (e.g. running `python cli.py` directly from source without
# `pip install .` first) - that fallback is kept in sync with
# pyproject.toml by hand.
from importlib.metadata import version as _pkg_version, PackageNotFoundError

try:
    __version__ = _pkg_version("novash")
except PackageNotFoundError:
    __version__ = "0.1.0"

# The Typer app object represents the CLI itself.
app = typer.Typer(
    name="novash",
    help="Novash: a simple command-line SEO checker.",
)

# A single shared Console instance handles all colored/styled output.
console = Console()


def _version_callback(show_version: bool):
    """
    Eager callback invoked as soon as Typer parses --version, before
    any command runs. Prints the version and exits immediately.

    Args:
        show_version (bool): True if --version was passed on the
            command line.
    """
    if show_version:
        console.print(f"Novash {__version__}")
        # typer.Exit stops further processing (e.g. it won't then
        # complain that no command was given).
        raise typer.Exit()


@app.callback()
def novash_cli(
    version: bool = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the Novash version and exit.",
    ),
):
    """
    Novash: a simple command-line SEO checker.

    Run the scan command with a URL, e.g.:

        python cli.py scan https://github.com

    Use --version to print the installed Novash version and exit:

        novash --version
    """
    # This callback body intentionally does nothing else. Typer
    # collapses an app with only one @app.command() into a single
    # top-level command with no subcommand name. Having this
    # callback present keeps "scan" as an explicit subcommand,
    # matching the required usage: `python cli.py scan <url>`.
    # is_eager=True on the --version option above means Typer
    # resolves and runs _version_callback() before this function
    # body would run, so `novash --version` never requires a `scan`
    # subcommand or a URL.
    pass


@app.command()
def scan(
    url: str = typer.Argument(
        ...,
        help="The full website URL to analyze, e.g. https://github.com",
    ),
    export: str = typer.Option(
        None,
        "--export",
        help="Save the full report as a JSON file, e.g. --export report.json",
    ),
    html_filename: str = typer.Option(
        None,
        "--html",
        help="Save the full report as a standalone HTML file, e.g. --html report.html",
    ),
):
    """
    Scan a website and print a full Novash SEO report.

    Downloads the page, checks the title, meta description, H1 tags,
    and image alt text, calculates an overall SEO score, and prints
    a color-coded report to the terminal.

    Use --export <filename> to also save the full report as a JSON
    file, e.g.:

        python cli.py scan https://github.com --export report.json

    Use --html <filename> to also save the full report as a
    standalone HTML file, e.g.:

        python cli.py scan https://github.com --html report.html

    Both can be used together:

        python cli.py scan https://github.com --export report.json --html report.html
    """
    # --- Step 1: Basic input validation ---
    # Typer already requires a value for `url`, but guard against a
    # blank/whitespace-only string slipping through.
    if not url.strip():
        console.print("[bold red]Error: URL cannot be empty.[/bold red]")
        raise typer.Exit(code=1)

    url = url.strip()

    # --- Step 2: Download the page ---
    # get_page() handles its own errors internally (timeouts, bad
    # URLs, connection failures) and returns None on failure instead
    # of raising, so we just need to check for None afterward.
    with console.status(f"[bold cyan]Crawling {url}...[/bold cyan]"):
        soup = get_page(url)

    # Print the report title inside a panel, shown regardless of
    # whether the crawl succeeded.
    console.print(
        Panel(
            Text("NOVASH SEO REPORT", style="bold white", justify="center"),
            style="bold blue",
            expand=False,
        )
    )
    console.print(f"[bold]\U0001F310 Website:[/bold] {url}\n")

    # If the page couldn't be fetched, there's nothing to analyze -
    # report that and stop instead of running checks against None.
    if soup is None:
        console.print(
            "[bold red]\u274C Could not fetch the page. "
            "Please check the URL and try again.[/bold red]"
        )
        raise typer.Exit(code=1)

    # --- Step 3: Run all SEO checks ---
    # Each check function returns a dict with a "status" bool plus
    # extra details (title text, description text, list of H1s,
    # image counts).
    title_result = check_title(soup)
    meta_result = check_meta_description(soup)
    h1_result = check_h1(soup)
    image_result = check_image_alts(soup)

    # check_open_graph() reuses the same `soup` object that was
    # already parsed from the page above - it does NOT make its own
    # HTTP request, since all six og: tags live in the same HTML
    # document already fetched by get_page(). og_checker.py is
    # designed to handle bad input (None soup, unexpected types)
    # internally and never raise - but this is wrapped in try/except
    # too, as an extra safety net (matching the same pattern already
    # used below for sitemap_result and link_result), so a completely
    # unexpected error can never crash the rest of the scan.
    try:
        og_result = check_open_graph(soup)
    except Exception as e:
        og_result = {
            "status": False,
            "found": False,
            "tags": {},
            "missing": [],
            "content": {},
            "issues": [f"Open Graph check failed unexpectedly: {e}"],
        }

    # check_canonical() also reuses the same `soup` object already
    # parsed above, and takes the page's own URL only to resolve a
    # relative canonical href - it makes NO HTTP request of its own.
    canonical_result = check_canonical(soup, url)

    # check_twitter_cards() also reuses the same `soup` object
    # already parsed above - it does NOT make its own HTTP request,
    # since all six twitter: tags live in the same HTML document
    # already fetched by get_page(). twitter_checker.py is designed
    # to handle bad input (None soup, unexpected types) internally
    # and never raise - but this is wrapped in try/except too, as an
    # extra safety net (matching the same pattern already used for
    # og_result, sitemap_result, and link_result), so a completely
    # unexpected error can never crash the rest of the scan.
    try:
        twitter_result = check_twitter_cards(soup)
    except Exception as e:
        twitter_result = {
            "status": "missing",
            "tags": {},
            "missing": [],
            "issues": [f"Twitter/X Card check failed unexpectedly: {e}"],
        }

    # check_schema() also reuses the same `soup` object already
    # parsed above - it does NOT make its own HTTP request, since
    # any <script type="application/ld+json"> blocks live in the
    # same HTML document already fetched by get_page().
    # schema_checker.py is designed to handle bad input (None soup,
    # malformed JSON, unexpected types) internally and never raise -
    # but this is wrapped in try/except too, as an extra safety net
    # (matching the same pattern already used for og_result and
    # twitter_result), so a completely unexpected error can never
    # crash the rest of the scan.
    try:
        schema_result = check_schema(soup)
    except Exception as e:
        schema_result = {
            "status": "missing",
            "count": 0,
            "schemas": [],
            "missing": [],
            "issues": [f"Structured data check failed unexpectedly: {e}"],
        }

    # check_favicon() also reuses the same `soup` object already
    # parsed above - it does NOT make its own HTTP request, since it
    # only inspects <link> tags already present in the HTML document
    # already fetched by get_page(); it never verifies whether a
    # declared favicon URL actually resolves. favicon_checker.py is
    # designed to handle bad input (None soup, unexpected types)
    # internally and never raise - but this is wrapped in try/except
    # too, as an extra safety net (matching the same pattern already
    # used for og_result, twitter_result, and schema_result), so a
    # completely unexpected error can never crash the rest of the
    # scan.
    try:
        favicon_result = check_favicon(soup)
    except Exception as e:
        favicon_result = {
            "status": "missing",
            "found": False,
            "icons": [],
            "missing": [],
            "issues": [f"Favicon check failed unexpectedly: {e}"],
        }

    # robots.txt lives at the site root, not on the parsed page
    # itself, so it's checked separately via its own HTTP request
    # rather than from `soup`.
    robots_result = check_robots(url)

    # sitemap.xml also lives at the site root and is checked via
    # its own HTTP request. check_sitemap() already handles its own
    # network/parsing errors internally and returns a result dict
    # instead of raising - but it's wrapped in try/except here too,
    # as an extra safety net so a completely unexpected error can
    # never crash the rest of the scan.
    try:
        sitemap_result = check_sitemap(url)
    except Exception as e:
        sitemap_result = {
            "status": False,
            "message": f"Sitemap check failed unexpectedly: {e}",
            "url": None,
            "status_code": None,
        }

    # check_links() reuses the same `soup` object already parsed
    # above - the page itself is NOT crawled again. It does make its
    # own individual HTTP requests to each link found on the page,
    # which is an inherent part of checking whether those links
    # work, not a duplicate of the main page crawl. Wrapped in
    # try/except as a safety net so a completely unexpected error
    # (not already handled inside check_links) can't crash the scan.
    try:
        link_result = check_links(soup, url)
    except Exception as e:
        link_result = {
            "total": 0,
            "working": 0,
            "broken": 0,
            "links": [],
            "analysis": {
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
            },
        }

    # --- Step 4: Calculate the score ---
    # Build the results dict the weighted calculate_score() expects:
    # the full result dict from each of the nine checks, keyed by
    # category name. calculate_score() itself handles all the
    # weighting (including partial credit for images, Open Graph,
    # and links), so no manual point deductions are needed here.
    score_input = {
        "title": title_result,
        "meta_description": meta_result,
        "h1": h1_result,
        "images": image_result,
        "robots": robots_result,
        "sitemap": sitemap_result,
        "open_graph": og_result,
        "links": link_result,
        "canonical": canonical_result,
    }
    score_result = calculate_score(score_input)

    # --- Low-weight favicon penalty (applied here, not in score.py) ---
    # score.py has no favicon category yet, and this integration is
    # scoped to cli.py only, so rather than silently having zero
    # scoring effect, a small, capped deduction is applied directly
    # on top of calculate_score()'s result - the same approach this
    # file used for robots.txt before score.py formally supported it.
    # Capped at 2 points (out of 100) so a missing/invalid favicon is
    # visible in the score without being "heavily" penalized, per
    # this integration's requirement that it stay a low-weight
    # website-quality recommendation rather than a serious SEO issue.
    FAVICON_PENALTY = 2
    if favicon_result["status"] != "found":
        score_result["score"] = max(score_result["score"] - FAVICON_PENALTY, 0)

    # --- Step 5: Display the report ---

    # Title section: green check + actual title text, or red X.
    console.print("[bold]\U0001F4C4 Title[/bold]")
    if title_result["status"]:
        console.print("[bold green]\u2713 Title found:[/bold green]")
        console.print(f"  [dim]{title_result['title']}[/dim]")
    else:
        console.print("[bold red]\u2717 Title missing[/bold red]")
    console.print()

    # Meta description section: same green/red pattern.
    console.print("[bold]\U0001F4DD Meta Description[/bold]")
    if meta_result["status"]:
        console.print("[bold green]\u2713 Meta description found:[/bold green]")
        console.print(f"  [dim]{meta_result['description']}[/dim]")
    else:
        console.print("[bold red]\u2717 Meta description missing[/bold red]")
    console.print()

    # H1 section: list every H1 tag found, one per line.
    console.print("[bold]\U0001F4CC H1 Tags[/bold]")
    if h1_result["status"]:
        console.print("[bold green]\u2713 H1 tags found:[/bold green]")
        for h1_text in h1_result["h1_tags"]:
            console.print(f"  [dim]- {h1_text}[/dim]")
    else:
        console.print("[bold red]\u2717 H1 missing[/bold red]")
    console.print()

    # Image alt text section: totals plus a red flag only if any
    # images are missing alt text.
    console.print("[bold]\U0001F5BC\uFE0F  Images[/bold]")
    console.print(f"[bold green]\u2713 Total images:[/bold green] {image_result['total_images']}")
    console.print(f"[bold green]\u2713 Images with alt text:[/bold green] {image_result['with_alt']}")
    if image_result["without_alt"] > 0:
        console.print(
            f"[bold red]\u2717 Images without alt text:[/bold red] {image_result['without_alt']}"
        )
    else:
        console.print(
            f"[bold green]\u2713 Images without alt text:[/bold green] {image_result['without_alt']}"
        )
    console.print()

    # robots.txt section: a single line, green check or red X.
    console.print("[bold]\U0001F916 robots.txt[/bold]")
    if robots_result["status"]:
        console.print("[bold green]\u2713 robots.txt found[/bold green]")
    else:
        console.print("[bold red]\u2717 robots.txt missing[/bold red]")
    console.print()

    # Sitemap section: green check or red X, plus the sitemap URL
    # that was checked underneath.
    console.print("[bold]\U0001F5FA\uFE0F  Sitemap[/bold]")
    if sitemap_result["status"]:
        console.print("[bold green]\u2713 Sitemap found[/bold green]")
    else:
        console.print("[bold red]\u2717 Sitemap missing[/bold red]")
    console.print(f"  [dim]URL: {sitemap_result['url']}[/dim]")
    console.print()

    # Open Graph section: a single green line if all four tags are
    # present, or a red line plus a bulleted list of exactly which
    # tags are missing.
    console.print("[bold]\U0001F517 Open Graph[/bold]")
    if og_result["status"]:
        console.print("[bold green]\u2713 All Open Graph tags found[/bold green]")
    else:
        console.print("[bold red]\u2717 Missing Open Graph tags:[/bold red]")
        for tag_name in og_result["missing"]:
            console.print(f"  [dim]- {tag_name}[/dim]")
    console.print()

    # Twitter/X Card section: green line if all four primary tags are
    # present ("complete"), yellow with the missing primary tags
    # listed if partially present ("incomplete"), or a red line if
    # none are present at all ("missing"). Any issues (duplicate
    # tags, empty content) are listed underneath regardless of status.
    console.print("[bold]\U0001F426 Twitter/X Card[/bold]")
    if twitter_result["status"] == "complete":
        console.print("[bold green]\u2713 Twitter/X Card complete[/bold green]")
    elif twitter_result["status"] == "incomplete":
        console.print("[bold yellow]\u26A0 Twitter/X Card incomplete. Missing:[/bold yellow]")
        for tag_name in twitter_result["missing"]:
            console.print(f"  [dim]- {tag_name}[/dim]")
    else:
        console.print("[bold red]\u2717 Twitter/X Card missing[/bold red]")
    if twitter_result["issues"]:
        for issue in twitter_result["issues"]:
            console.print(f"  [yellow]\u26A0 {issue}[/yellow]")
    console.print()

    # Structured Data (Schema.org / JSON-LD) section. Per design,
    # missing structured data is a RECOMMENDATION, not a failure -
    # so the "missing" state uses yellow/warning styling rather than
    # red, unlike most other checks in this report. "invalid" (JSON-LD
    # was present but completely unusable) does use red, since that's
    # a genuine, fixable problem rather than an absence. Note: schema
    # is intentionally NOT included in score_input below and has no
    # effect on the SEO score - score.py has no schema category yet,
    # so per this integration's scope, structured data stays purely
    # informational rather than being bolted onto scoring ad hoc.
    console.print("[bold]\U0001F9E9 Structured Data[/bold]")
    if schema_result["status"] == "found":
        console.print(
            f"[bold green]\u2713 Structured data found "
            f"({schema_result['count']} block(s))[/bold green]"
        )
        found_types = [schema["type"] for schema in schema_result["schemas"] if schema["type"]]
        for schema_type in found_types:
            console.print(f"  [dim]- {schema_type}[/dim]")
    elif schema_result["status"] == "invalid":
        console.print("[bold red]\u2717 Structured data present but invalid[/bold red]")
    else:
        console.print(
            "[bold yellow]\u26A0 No structured data found "
            "(recommended, not required)[/bold yellow]"
        )
    if schema_result["issues"]:
        for issue in schema_result["issues"]:
            console.print(f"  [yellow]\u26A0 {issue}[/yellow]")
    console.print()

    # Favicon section. Per requirement, a missing/invalid favicon is
    # a low-weight website-quality recommendation, not a serious SEO
    # problem - so, like Structured Data above, "missing"/"invalid"
    # use yellow/warning styling here rather than red. favicon is
    # intentionally NOT included in score_input below and has no
    # effect on the SEO score - score.py has no favicon category yet,
    # so per this integration's scope (cli.py only), the favicon
    # check stays purely informational rather than being bolted onto
    # scoring ad hoc.
    console.print("[bold]\U0001F5BC\uFE0F  Favicon[/bold]")
    if favicon_result["status"] == "found":
        primary_icon = next(
            (icon for icon in favicon_result["icons"] if icon["rel"] == ["icon"] and icon["href"]),
            None,
        )
        if primary_icon:
            console.print("[bold green]\u2713 Favicon found:[/bold green]")
            console.print(f"  [dim]{primary_icon['href']}[/dim]")
        else:
            # A usable favicon was found, just not via a plain
            # rel="icon" tag (e.g. only apple-touch-icon).
            console.print("[bold green]\u2713 Favicon found[/bold green]")
    elif favicon_result["status"] == "invalid":
        console.print(
            "[bold yellow]\u26A0 Favicon declared but not usable "
            "(recommendation)[/bold yellow]"
        )
    else:
        console.print(
            "[bold yellow]\u26A0 No favicon found (recommendation)[/bold yellow]"
        )
    if favicon_result["issues"]:
        for issue in favicon_result["issues"]:
            console.print(f"  [yellow]\u26A0 {issue}[/yellow]")
    console.print()

    # Canonical section: green check + resolved URL if a valid
    # canonical was found, or a red X if missing. Any issues
    # returned by check_canonical() (e.g. multiple canonical tags,
    # an invalid scheme) are listed underneath regardless of
    # found/missing status.
    console.print("[bold]\U0001F517 Canonical[/bold]")
    if canonical_result["found"]:
        console.print("[bold green]\u2713 Canonical URL found:[/bold green]")
        console.print(f"  [dim]{canonical_result['url']}[/dim]")
    else:
        console.print("[bold red]\u2717 Canonical URL missing[/bold red]")
    if canonical_result["issues"]:
        for issue in canonical_result["issues"]:
            console.print(f"  [yellow]\u26A0 {issue}[/yellow]")
    console.print()

    # Links section: totals plus a red flag only if any links are
    # broken, with the specific broken URLs and status codes listed
    # underneath so they're easy to act on.
    console.print("[bold]\U0001F517 Links[/bold]")
    console.print(f"[bold green]\u2713 Total links:[/bold green] {link_result['total']}")
    console.print(f"[bold green]\u2713 Working links:[/bold green] {link_result['working']}")
    if link_result["broken"] > 0:
        console.print(f"[bold red]\u2717 Broken links:[/bold red] {link_result['broken']}")
        console.print()
        console.print("[bold]\U0001F6A8 Broken Links[/bold]")
        for link in link_result["links"]:
            if link["status"] == "broken":
                status_display = link["status_code"] if link["status_code"] is not None else "no response"
                console.print(f"[red]- {link['url']} \u2192 {status_display}[/red]")
    else:
        console.print(f"[bold green]\u2713 Broken links:[/bold green] {link_result['broken']}")
    console.print()

    # Link composition analysis: purely HTML-based statistics from
    # link_checker.py's "analysis" field - no additional HTTP
    # requests are made for any of this (it's derived from the same
    # `soup` already parsed above, alongside the working/broken check
    # above it). .get(...) with defaults guards against an older/
    # fallback link_result shape that might be missing this key.
    link_analysis = link_result.get("analysis") or {}
    console.print("[bold]\U0001F4CA Link Analysis[/bold]")
    console.print(f"[bold green]\u2713 Total links found:[/bold green] {link_analysis.get('total_links', 0)}")
    console.print(f"[bold green]\u2713 Internal links:[/bold green] {link_analysis.get('internal_links', 0)}")
    console.print(f"[bold green]\u2713 External links:[/bold green] {link_analysis.get('external_links', 0)}")
    console.print(f"[bold green]\u2713 Empty href:[/bold green] {link_analysis.get('empty_href', 0)}")
    console.print(f"[bold green]\u2713 JavaScript links:[/bold green] {link_analysis.get('javascript_links', 0)}")
    console.print(
        f"[bold green]\u2713 Mailto / Tel links:[/bold green] "
        f"{link_analysis.get('mailto_links', 0)} / {link_analysis.get('tel_links', 0)}"
    )
    console.print(
        f"[bold green]\u2713 Relative / Absolute links:[/bold green] "
        f"{link_analysis.get('relative_links', 0)} / {link_analysis.get('absolute_links', 0)}"
    )
    console.print(f"[bold green]\u2713 Descriptive anchor text:[/bold green] {link_analysis.get('descriptive_text', 0)}")
    empty_text_count = link_analysis.get("empty_text", 0)
    if empty_text_count > 0:
        console.print(f"[bold yellow]\u26A0 Empty anchor text:[/bold yellow] {empty_text_count}")
    else:
        console.print(f"[bold green]\u2713 Empty anchor text:[/bold green] {empty_text_count}")
    generic_text_count = link_analysis.get("generic_text", 0)
    if generic_text_count > 0:
        console.print(f"[bold yellow]\u26A0 Generic anchor text (e.g. \"click here\"):[/bold yellow] {generic_text_count}")
    else:
        console.print(f"[bold green]\u2713 Generic anchor text:[/bold green] {generic_text_count}")
    console.print()

    # --- Score panel: color-coded by range (green/yellow/red) ---
    score = score_result["score"]
    max_score = score_result["max_score"]

    if score >= 90:
        color = "green"
        emoji = "\U0001F389"  # party popper - great score
    elif score >= 70:
        color = "yellow"
        emoji = "\u26A0\uFE0F"  # warning - room for improvement
    else:
        color = "red"
        emoji = "\U0001F6A8"  # rotating light - needs attention

    console.print(
        Panel(
            Text(f"{emoji} SEO Score: {score}/{max_score}", style=f"bold {color}", justify="center"),
            style=color,
            expand=False,
        )
    )
    console.print()

    # --- Suggestions section ---
    # Build the results dict that generate_suggestions() expects,
    # keyed the same way as the report data below.
    check_results = {
        "title": title_result,
        "meta_description": meta_result,
        "h1": h1_result,
        "images": image_result,
        "open_graph": og_result,
        "links": link_result,
    }
    suggestions = generate_suggestions(check_results)

    # generate_suggestions() (in suggestions.py) doesn't know about
    # Twitter/X Cards, so its suggestions are built here instead,
    # directly from twitter_result, and merged into the same list -
    # this keeps a single unified Suggestions section in the report
    # without needing to modify suggestions.py.
    twitter_suggestions = [
        f"Add {tag_name} for better Twitter/X card previews."
        for tag_name in twitter_result["missing"]
    ]
    if twitter_suggestions:
        if suggestions == ["No SEO issues found."]:
            suggestions = twitter_suggestions
        else:
            suggestions = suggestions + twitter_suggestions

    # generate_suggestions() also doesn't know about structured data,
    # so its suggestion (if any) is built here too, directly from
    # schema_result, and merged into the same list. Kept deliberately
    # soft/recommendation-toned for the "missing" case, per this
    # integration's requirement not to treat absent structured data
    # as a severe SEO failure.
    schema_suggestions = []
    if schema_result["status"] == "missing":
        schema_suggestions.append(
            "Consider adding structured data (JSON-LD), such as Organization "
            "or WebSite schema, to help search engines understand the page "
            "and enable rich results."
        )
    elif schema_result["status"] == "invalid":
        schema_suggestions.append(
            "Fix the invalid structured data (JSON-LD) on this page so "
            "search engines can read it."
        )
    elif schema_result["issues"]:
        schema_suggestions.append(
            "Review structured data issues (e.g. missing @type or duplicate "
            "schema types) to get the full SEO benefit."
        )
    if schema_suggestions:
        if suggestions == ["No SEO issues found."]:
            suggestions = schema_suggestions
        else:
            suggestions = suggestions + schema_suggestions

    # generate_suggestions() also doesn't know about the favicon
    # check, so its suggestion (if any) is built here too, directly
    # from favicon_result, and merged into the same list. Phrased
    # softly, matching this check's low-weight/recommendation status.
    favicon_suggestions = []
    if favicon_result["status"] == "missing":
        favicon_suggestions.append(
            "Add a favicon (e.g. <link rel=\"icon\" href=\"/favicon.ico\">) "
            "for better branding in browser tabs and bookmarks."
        )
    elif favicon_result["status"] == "invalid":
        favicon_suggestions.append(
            "Fix the favicon declaration on this page - a <link> tag was "
            "found but has no usable href."
        )
    if favicon_suggestions:
        if suggestions == ["No SEO issues found."]:
            suggestions = favicon_suggestions
        else:
            suggestions = suggestions + favicon_suggestions

    console.print("[bold]\U0001F4A1 Suggestions[/bold]")
    if suggestions == ["No SEO issues found."]:
        # Special case: everything passed, so show a single
        # celebratory line instead of a bulleted list.
        console.print("[bold green]\u2705 No SEO issues found.[/bold green]")
    else:
        # One bullet per suggestion, in yellow to signal "needs
        # attention" without being as alarming as red.
        for suggestion in suggestions:
            console.print(f"[yellow]- {suggestion}[/yellow]")
    console.print()

    # --- Step 6: Optional exports (JSON and/or HTML) ---
    # report_data is built once here - regardless of which export
    # flag(s) were passed - and reused for both export formats below.
    # This is just assembling a dict from results already computed
    # above; it does NOT re-run any SEO checks or make any new
    # network requests, so requesting both --export and --html never
    # duplicates work.
    if export or html_filename:
        report_data = {
            "website": url,
            "title": title_result,
            "meta_description": meta_result,
            "h1": h1_result,
            "images": image_result,
            "robots_txt": robots_result,
            "sitemap": sitemap_result,
            "open_graph": og_result,
            "twitter": twitter_result,
            "schema": schema_result,
            "favicon": favicon_result,
            "canonical": canonical_result,
            "links": link_result,
            "score": score_result,
            "suggestions": suggestions,
        }

        # Initialized to True so the "did anything fail" check below
        # works correctly even when only one of the two export flags
        # was actually requested (the untouched one is simply never
        # considered a failure).
        success = True
        html_success = True

        # JSON export - only runs if the user passed --export.
        if export:
            # export_json() handles its own errors internally and
            # returns True/False instead of raising.
            success = export_json(report_data, export)

            if success:
                console.print(f"[bold green]\u2713 Report exported to {export}[/bold green]")
            else:
                # A failed export is reported clearly but does not
                # crash the rest of the scan/exports.
                console.print(f"[bold red]\u2717 Failed to export report to {export}[/bold red]")

        # HTML export - only runs if the user passed --html. Wrapped
        # in its own try/except as a safety net: export_html() is
        # designed to always return True/False rather than raise,
        # but this ensures a truly unexpected error here still can't
        # crash the scan or prevent the JSON export above from
        # having already succeeded.
        if html_filename:
            try:
                html_success = export_html(report_data, html_filename)
            except Exception as e:
                html_success = False
                console.print(
                    f"[bold red]\u2717 HTML export failed unexpectedly: {e}[/bold red]"
                )
            else:
                if html_success:
                    console.print(
                        f"[bold green]\u2713 HTML report exported to {html_filename}[/bold green]"
                    )
                else:
                    console.print(
                        f"[bold red]\u2717 Failed to export HTML report to {html_filename}[/bold red]"
                    )

        # Exit with a non-zero code if any requested export failed,
        # so scripts/CI can detect the problem - but only after both
        # exports have been attempted, so one failure never prevents
        # the other from running.
        export_failed = (export and not success) or (html_filename and not html_success)
        if export_failed:
            raise typer.Exit(code=1)


def main():
    """
    Entry point used by the installed `novash` console script
    (see pyproject.toml's [project.scripts]). Simply launches the
    Typer app the same way running this file directly does.
    """
    app()


if __name__ == "__main__":
    # Launches the Typer app, which parses sys.argv and dispatches
    # to the matching command (here, just "scan").
    app()
