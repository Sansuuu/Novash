"""
main.py

Interactive entry point for Novash.

Prompts the user for a URL and prints a colorful SEO report. For a
scriptable command-line interface, see cli.py instead.
"""

from rich.console import Console

from report import run_report

console = Console()


def main():
    """
    Entry point: ask the user for a URL and run the report.
    """
    try:
        url = console.input("[bold cyan]Enter a website URL: [/bold cyan]").strip()
    except (EOFError, KeyboardInterrupt):
        # Handle Ctrl+D / Ctrl+C gracefully instead of a raw traceback.
        console.print("\n[yellow]No input received. Exiting.[/yellow]")
        return

    # Basic sanity check before we even try to crawl.
    if not url:
        console.print("[red]No URL entered. Please run the program again and enter a URL.[/red]")
        return

    # Wrap the whole report run so any unexpected error (e.g. from
    # a malformed page) doesn't crash the program with a raw
    # traceback for the end user.
    try:
        run_report(url)
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred while analyzing '{url}': {e}[/bold red]")


if __name__ == "__main__":
    main()
