# Novash

[![PyPI version](https://img.shields.io/pypi/v/novash.svg)](https://pypi.org/project/novash/)
[![Python versions](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Novash** is an open-source, command-line SEO checker for websites. Point it at a URL and it downloads the page, audits it across **9 categories** of on-page and technical SEO, scores the result out of 100 with a full transparent breakdown, and tells you exactly what to fix — all from your terminal, in color.

```
╭───────────────────╮
│ NOVASH SEO REPORT │
╰───────────────────╯
🌐 Website: https://example.com

📄 Title              ✓ Found
📝 Meta Description   ✓ Found
📌 H1 Tags            ✓ Found
🖼️  Images             ✗ 10 missing alt text
🤖 robots.txt         ✓ Found
🗺️  Sitemap            ✓ Found
🔗 Open Graph         ✓ Complete
🐦 Twitter/X Card     ⚠ Incomplete
🧩 Structured Data    ⚠ Not found (recommendation)
🖼️  Favicon            ✓ Found
🔗 Canonical          ✓ Found
🔗 Links              ✗ 24 broken

╭──────────────────────╮
│ ⚠️ SEO Score: 76/100 │
╰──────────────────────╯
```

---

## Features

Novash runs **12 checks** across every scan:

- 🔍 **Page crawling** — fetches and parses any public webpage, with built-in handling for timeouts, bad URLs, connection errors, and non-2xx responses.
- 📄 **Title** — detects a non-empty `<title>` tag.
- 📝 **Meta description** — detects a non-empty `<meta name="description">` tag.
- 📌 **H1 tags** — finds meaningful `<h1>` tags, automatically ignoring ones that are hidden (`display:none`, `visibility:hidden`, `aria-hidden`, the `hidden` attribute), empty, or shorter than 5 characters.
- 🖼️ **Images / alt text** — counts every `<img>` tag and reports how many are missing usable `alt` text.
- 🤖 **robots.txt** — fetches and parses the file: extracts `User-agent` rule groups and `Disallow`/`Allow` directives, lists declared `Sitemap:` URLs, detects a dangerous **site-wide block** (`User-agent: * ` + `Disallow: /`), and flags malformed lines, non-text/HTML responses, and duplicate directives.
- 🗺️ **Sitemap.xml** — checks for a valid, well-formed XML sitemap (`<urlset>` or `<sitemapindex>`), safely handling malformed XML or a "soft 404" HTML page served with a 200 status.
- 🔗 **Open Graph** — checks all six tags (`og:title`, `og:description`, `og:image`, `og:url`, `og:type`, `og:site_name`), detecting missing tags, empty content, and duplicates.
- 🐦 **Twitter/X Cards** — checks `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image` (primary) plus `twitter:site`/`twitter:creator` (optional), reporting a `complete` / `incomplete` / `missing` status.
- 🧩 **Structured Data (Schema.org / JSON-LD)** — parses every `<script type="application/ld+json">` block, handling arrays and `@graph` structures, detecting invalid JSON, missing `@type`, and duplicate schema types. Missing structured data is treated as a **recommendation**, never a fatal error.
- 🖼️ **Favicon** — checks `<link rel="icon">` (primary), `shortcut icon`, and `apple-touch-icon`, correctly distinguishing them even though browsers treat `rel` as a multi-token attribute.
- 🔗 **Canonical URL** — validates `<link rel="canonical">`: resolves relative hrefs, rejects unusable schemes (`javascript:`, etc.), and flags multiple canonical tags.
- 🔗 **Links** — checks every link on the page **in parallel** (up to 20 at a time) for broken links (4xx/5xx/timeouts), *and* performs a zero-extra-request composition analysis: internal vs. external, relative vs. absolute, empty/`#`/`javascript:`/`mailto:`/`tel:` hrefs, and descriptive vs. empty vs. generic (`"click here"`, `"read more"`, etc.) anchor text.
- 📊 **Weighted SEO scoring** — a transparent 100-point score built from all 9 scorable categories, with partial credit where it makes sense (see [Scoring](#scoring)).
- 💡 **Actionable suggestions** — a plain-language list of fixes generated from whatever the audit finds.
- 📤 **JSON export** — save the complete, structured report for use in dashboards, CI pipelines, or other tools.
- 🌐 **Standalone HTML export** — a self-contained report file with no JavaScript, no external CSS, and no external assets — safe to email, archive, or open offline.
- 🎨 **Rich colored terminal UI** — clear green/yellow/red status at a glance, powered by [Rich](https://github.com/Textualize/rich).

---

## Installation

Novash requires **Python 3.8+**.

### From PyPI

```bash
pip install novash
```

### From source

```bash
git clone https://github.com/<your-username>/novash.git
cd novash
pip install .
```

This installs Novash's dependencies (`requests`, `beautifulsoup4`, `rich`, `typer`) and registers the `novash` command on your PATH.

For development (editable install, so code changes take effect immediately):

```bash
pip install -e .
```

---

## Usage

Scan a website and print the report to your terminal:

```bash
novash scan https://example.com
```

Save the full report as JSON:

```bash
novash scan https://example.com --export report.json
```

Save a standalone HTML report:

```bash
novash scan https://example.com --html report.html
```

Do both at once:

```bash
novash scan https://example.com --export report.json --html report.html
```

Check the installed version:

```bash
novash --version
```

View help for any command:

```bash
novash --help
novash scan --help
```

---

## CLI Commands

| Command | Description |
|---|---|
| `novash scan <url>` | Crawl a URL, run all 12 checks, calculate the score, and print the report. |
| `novash scan <url> --export <file>` | Also save the full report as a pretty-printed JSON file. |
| `novash scan <url> --html <file>` | Also save the full report as a standalone HTML file. |
| `novash scan <url> --export <file> --html <file>` | Save both formats in a single scan (no duplicate work). |
| `novash --version` | Print the installed Novash version and exit. |
| `novash --help` | Show general help and available commands. |
| `novash scan --help` | Show detailed help for the `scan` command. |

### Options

| Option | Description |
|---|---|
| `--export <filename>` | Save the report as JSON, e.g. `--export report.json`. |
| `--html <filename>` | Save the report as a standalone HTML file, e.g. `--html report.html`. |

---

## Example Output

```
╭───────────────────╮
│ NOVASH SEO REPORT │
╰───────────────────╯
🌐 Website: https://example.com

📄 Title
✓ Title found:
  Example Domain

📝 Meta Description
✗ Meta description missing

📌 H1 Tags
✓ H1 tags found:
  - Example Domain

🖼️  Images
✓ Total images: 11
✓ Images with alt text: 1
✗ Images without alt text: 10

🤖 robots.txt
✓ robots.txt found

🗺️  Sitemap
✓ Sitemap found
  URL: https://example.com/sitemap.xml

🔗 Open Graph
✗ Missing Open Graph tags:
  - og:title

🐦 Twitter/X Card
✗ Twitter/X Card missing

🧩 Structured Data
⚠ No structured data found (recommendation, not required)

🖼️  Favicon
✓ Favicon found:
  /favicon.ico

🔗 Canonical
✓ Canonical URL found:
  https://example.com/

🔗 Links
✓ Total links: 38
✓ Working links: 14
✗ Broken links: 24

🚨 Broken Links
- https://example.com/old-page → 404

📊 Link Analysis
✓ Total links found: 50
✓ Internal links: 19
✓ External links: 30
✓ Empty href: 0
✓ JavaScript links: 0
✓ Mailto / Tel links: 0 / 0
✓ Relative / Absolute links: 19 / 30
✓ Descriptive anchor text: 49
⚠ Empty anchor text: 1
✓ Generic anchor text: 0

╭──────────────────────╮
│ ⚠️ SEO Score: 76/100 │
╰──────────────────────╯

💡 Suggestions
- Add a meta description.
- Add alt text to 10 images.
- Fix 24 broken links.
- Add og:title for better social sharing previews.
```

If every check passes, the Suggestions section shows a single line instead:

```
💡 Suggestions
✅ No SEO issues found.
```

---

## Scoring

Novash's score is out of **100 points**, split across 9 weighted categories:

| Category | Weight | Credit type |
|---|---|---|
| Title | 14.25 | Pass / fail |
| Meta description | 14.25 | Pass / fail |
| H1 | 9.5 | Pass / fail |
| Images (alt text) | 14.25 | Partial — proportional to % of images with alt text; no penalty if the page has no images |
| robots.txt | 9.5 | Pass / fail |
| Sitemap | 9.5 | Pass / fail |
| Open Graph | 14.25 | Partial — proportional to how many of the 4 core tags are present |
| Links | 9.5 | Partial — proportional to % of links that work; no penalty if the page has no links |
| Canonical URL | 5 | Pass / fail — a single, valid canonical URL earns full credit; missing, invalid, or multiple canonical tags earn 0 |

**14.25 × 4 + 9.5 × 4 + 5 = 100** exactly — every category's relative importance was preserved when Canonical was added, rather than bolting 5 points onto an already-full 100.

The score is color-coded in the terminal:

| Score | Color |
|---|---|
| 90–100 | 🟢 Green |
| 70–89 | 🟡 Yellow |
| 0–69 | 🔴 Red |

Twitter/X Cards, Structured Data, and Favicon are currently checked and reported but do **not** affect the score — they're treated as recommendations, consistent with how each is genuinely optional or "nice to have" for SEO rather than a hard requirement.

---

## JSON Export

`--export report.json` writes the complete, structured result of every check, plus the score breakdown and suggestions, as pretty-printed JSON — useful for feeding into dashboards, CI pipelines (e.g. fail a build if the score drops below a threshold), or your own tooling.

## HTML Export

`--html report.html` writes a fully self-contained HTML report: no JavaScript, no external CSS, fonts, or images. Every check gets its own color-coded card — Title, Meta Description, H1, Images, robots.txt, Sitemap, Open Graph, Twitter/X Card, Structured Data, Favicon, Canonical URL, and Links (including the full link composition breakdown) — plus the score panel and breakdown bars. It's safe to email as an attachment, archive indefinitely, or open directly in any browser with no internet connection.

---

## Roadmap

Planned improvements for future versions:

- [ ] Multi-page / full-site crawling (follow internal links automatically)
- [ ] Configurable scoring weights via a config file
- [ ] Batch scanning of multiple URLs from a file
- [ ] CI/CD integration helpers (exit codes tied to score thresholds)
- [ ] PDF report export, alongside JSON and HTML
- [ ] Publish to PyPI for `pip install novash`

Have an idea? Open an issue — see [Contributing](#contributing) below.

---

## Testing

Novash has a pytest suite covering every checker module (116 tests). All network calls are mocked, so the full suite runs in under a second with no real HTTP requests:

```bash
pip install pytest
pytest -v
```

## Contributing

Contributions are welcome! To get started:

1. Fork the repository and clone your fork.
2. Create a new branch for your change:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. Install in editable mode so your changes are picked up immediately:
   ```bash
   pip install -e .
   ```
4. Make your changes. Most modules include a `if __name__ == "__main__":` block with quick manual tests you can run directly (e.g. `python checks.py`, `python schema_checker.py`).
5. Commit and push your branch, then open a pull request describing what you changed and why.

Please keep pull requests focused — one feature or fix per PR makes review much easier. Bug reports and feature requests are just as welcome as code; feel free to open an issue.

### Publishing to PyPI (maintainers)

```bash
python -m pip install --upgrade build twine
python -m build
twine upload dist/*
```

---

## License

Novash is released under the [MIT License](LICENSE).
