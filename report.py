"""
report.py

Shared report-generation logic for Novash.

This module ties together crawler.py, checks.py, robots_checker.py,
sitemap_checker.py, og_checker.py, and score.py, and renders a
colorful, professional report using Rich. It's kept separate from
any single entry point (main.py, cli.py, etc.) so the same reporting
logic can be reused everywhere without duplication.
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from crawler import get_page
from checks import check_title, check_meta_description, check_h1, check_image_alts
from robots_checker import check_robots
from sitemap_checker import check_sitemap
from og_checker import check_open_graph
from link_checker import check_links
from score import calculate_score
from suggestions import generate_suggestions

# A single shared Console instance handles all colored/styled output.
console = Console()


def get_score_color(score):
    """
    Map a numeric SEO score to a Rich color name for display.

    Args:
        score (int): The SEO score out of 100.

    Returns:
        str: A Rich style name - "green", "yellow", or "red".
    """
    if score >= 90:
        return "green"
    elif score >= 70:
        return "yellow"
    else:
        return "red"


def print_check_line(passed, label, detail=None):
    """
    Print a single check result as a colored checkmark/X line, with
    an optional detail line underneath (e.g. the actual title text).

    Args:
        passed (bool): Whether the check passed.
        label (str): The text describing what was checked.
        detail (str | None): Extra content to show below the line
            (e.g. title text, description text). Omitted if None.
    """
    if passed:
        # Green checkmark for anything found/working correctly.
        console.print(f"[bold green]\u2713 {label}[/bold green]")
    else:
        # Red X for anything missing/failing.
        console.print(f"[bold red]\u2717 {label}[/bold red]")

    if detail:
        # Indent the detail slightly so it visually belongs to the
        # check line above it.
        console.print(f"  [dim]{detail}[/dim]")


def run_report(url):
    """
    Crawl a URL, run all SEO checks, score it, and print a rich,
    color-coded report.

    Args:
        url (str): The website URL to analyze.
    """
    # Download and parse the page. get_page() already handles
    # network errors, timeouts, and bad URLs internally, returning
    # None on any failure instead of raising.
    with console.status(f"[bold cyan]Crawling {url}...[/bold cyan]"):
        soup = get_page(url)

    # Always show the title panel first, regardless of outcome.
    console.print(
        Panel(
            Text("NOVASH SEO REPORT", style="bold white", justify="center"),
            style="bold blue",
            expand=False,
        )
    )
    console.print(f"[bold]\U0001F310 Website:[/bold] {url}\n")

    # If the page couldn't be fetched at all, there's nothing to
    # analyze - report that clearly and stop, rather than running
    # checks against None and printing a misleading score.
    if soup is None:
        console.print(
            "[bold red]\u274C Could not fetch the page. "
            "Please check the URL and try again.[/bold red]"
        )
        return

    # Run each individual SEO check. Each returns a dict with a
    # "status" bool plus extra details (title text, description
    # text, list of H1s, image counts).
    title_result = check_title(soup)
    meta_result = check_meta_description(soup)
    h1_result = check_h1(soup)
    image_result = check_image_alts(soup)

    # check_open_graph() reuses the same `soup` object already
    # parsed above - it makes no HTTP request of its own.
    og_result = check_open_graph(soup)

    # robots.txt and sitemap.xml both live at the site root, not on
    # the parsed page itself, so each is checked via its own HTTP
    # request rather than from `soup`. Both are wrapped in try/except
    # as an extra safety net - the checker functions already handle
    # their own network errors internally, but this ensures a fully
    # unexpected error can never crash the whole report.
    try:
        robots_result = check_robots(url)
    except Exception as e:
        robots_result = {
            "status": False,
            "message": f"robots.txt check failed unexpectedly: {e}",
            "url": None,
        }

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
    # above - the page itself is NOT crawled again. It makes its own
    # individual HTTP requests to each link found on the page, which
    # is inherent to checking whether those links work.
    try:
        link_result = check_links(soup, url)
    except Exception as e:
        link_result = {
            "total": 0,
            "working": 0,
            "broken": 0,
            "links": [],
        }

    # Build the results dict the weighted calculate_score() expects:
    # the full result dict from each of the eight checks, keyed by
    # category name.
    score_input = {
        "title": title_result,
        "meta_description": meta_result,
        "h1": h1_result,
        "images": image_result,
        "robots": robots_result,
        "sitemap": sitemap_result,
        "open_graph": og_result,
        "links": link_result,
    }
    score_result = calculate_score(score_input)

    # --- Title section ---
    console.print("[bold]\U0001F4C4 Title[/bold]")
    if title_result["status"]:
        print_check_line(True, "Title found:", title_result["title"])
    else:
        print_check_line(False, "Title missing")
    console.print()

    # --- Meta description section ---
    console.print("[bold]\U0001F4DD Meta Description[/bold]")
    if meta_result["status"]:
        print_check_line(True, "Meta description found:", meta_result["description"])
    else:
        print_check_line(False, "Meta description missing")
    console.print()

    # --- H1 tags section ---
    console.print("[bold]\U0001F4CC H1 Tags[/bold]")
    if h1_result["status"]:
        console.print("[bold green]\u2713 H1 tags found:[/bold green]")
        for h1_text in h1_result["h1_tags"]:
            console.print(f"  [dim]- {h1_text}[/dim]")
    else:
        print_check_line(False, "H1 missing")
    console.print()

    # --- Image alt text section ---
    console.print("[bold]\U0001F5BC\uFE0F  Images[/bold]")
    console.print(f"[bold green]\u2713 Total images:[/bold green] {image_result['total_images']}")
    console.print(f"[bold green]\u2713 Images with alt text:[/bold green] {image_result['with_alt']}")
    # Only flag the without-alt count red if there actually are any;
    # zero missing alt tags is itself a passing result.
    if image_result["without_alt"] > 0:
        console.print(
            f"[bold red]\u2717 Images without alt text:[/bold red] {image_result['without_alt']}"
        )
    else:
        console.print(
            f"[bold green]\u2713 Images without alt text:[/bold green] {image_result['without_alt']}"
        )
    console.print()

    # --- robots.txt section ---
    console.print("[bold]\U0001F916 robots.txt[/bold]")
    if robots_result["status"]:
        console.print("[bold green]\u2713 robots.txt found[/bold green]")
    else:
        console.print("[bold red]\u2717 robots.txt missing[/bold red]")
    console.print()

    # --- Sitemap section ---
    console.print("[bold]\U0001F5FA\uFE0F  Sitemap[/bold]")
    if sitemap_result["status"]:
        console.print("[bold green]\u2713 Sitemap found[/bold green]")
    else:
        console.print("[bold red]\u2717 Sitemap missing[/bold red]")
    console.print(f"  [dim]URL: {sitemap_result['url']}[/dim]")
    console.print()

    # --- Open Graph section ---
    console.print("[bold]\U0001F517 Open Graph[/bold]")
    if og_result["status"]:
        console.print("[bold green]\u2713 All Open Graph tags found[/bold green]")
    else:
        console.print("[bold red]\u2717 Missing Open Graph tags:[/bold red]")
        for tag_name in og_result["missing"]:
            console.print(f"  [dim]- {tag_name}[/dim]")
    console.print()

    # --- Links section ---
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

    # --- Score (always shown last, color-coded by range) ---
    score = score_result["score"]
    max_score = score_result["max_score"]
    color = get_score_color(score)

    # Pick an emoji that matches the score tier for a friendlier feel.
    if color == "green":
        emoji = "\U0001F389"  # party popper - great score
    elif color == "yellow":
        emoji = "\u26A0\uFE0F"  # warning - room for improvement
    else:
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
    check_results = {
        "title": title_result,
        "meta_description": meta_result,
        "h1": h1_result,
        "images": image_result,
        "open_graph": og_result,
        "links": link_result,
    }
    suggestions = generate_suggestions(check_results)

    console.print("[bold]\U0001F4A1 Suggestions[/bold]")
    if suggestions == ["No SEO issues found."]:
        console.print("[bold green]\u2705 No SEO issues found.[/bold green]")
    else:
        for suggestion in suggestions:
            console.print(f"[yellow]- {suggestion}[/yellow]")
