"""
checks.py

SEO check functions for Novash.

Each check function takes a BeautifulSoup object (as produced by
crawler.get_page) and returns a result dict describing whether the
check passed.
"""


def check_title(soup):
    """
    Check whether the page has a non-empty <title> tag.

    Args:
        soup (BeautifulSoup | None): Parsed HTML of the page, or
            None if the page failed to load/parse.

    Returns:
        dict: {
            "status": bool,   # True if a usable title was found
            "message": str,   # Human-readable result summary
            "title": str|None # The title text, or None if missing
        }
    """
    # Guard clause: if crawling/parsing failed upstream, soup will
    # be None. Handle that up front so we don't raise an
    # AttributeError by calling .find() on None.
    if soup is None:
        return {
            "status": False,
            "message": "Title missing",
            "title": None,
        }

    # Look for the <title> tag anywhere in the parsed HTML.
    title_tag = soup.find("title")

    # No <title> tag present at all in the document.
    if title_tag is None:
        return {
            "status": False,
            "message": "Title missing",
            "title": None,
        }

    # Extract and clean up the text inside the tag (strips
    # leading/trailing whitespace and newlines).
    title_text = title_tag.get_text(strip=True)

    # A <title></title> tag that exists but has no real text counts
    # as "missing" for SEO purposes.
    if not title_text:
        return {
            "status": False,
            "message": "Title missing",
            "title": None,
        }

    # Title tag exists and has actual content.
    return {
        "status": True,
        "message": "Title found",
        "title": title_text,
    }


def check_meta_description(soup):
    """
    Check whether the page has a non-empty meta description tag:
    <meta name="description" content="...">

    Args:
        soup (BeautifulSoup | None): Parsed HTML of the page, or
            None if the page failed to load/parse.

    Returns:
        dict: {
            "status": bool,        # True if a usable description was found
            "message": str,        # Human-readable result summary
            "description": str|None # The description text, or None if missing
        }
    """
    # Guard clause: if crawling/parsing failed upstream, soup will
    # be None. Handle that up front so we don't raise an
    # AttributeError by calling .find() on None.
    if soup is None:
        return {
            "status": False,
            "message": "Meta description missing",
            "description": None,
        }

    # Look for a <meta> tag whose "name" attribute is "description".
    # This search is case-sensitive to "description" by default, but
    # most sites follow the standard lowercase convention.
    meta_tag = soup.find("meta", attrs={"name": "description"})

    # No matching <meta name="description"> tag present at all.
    if meta_tag is None:
        return {
            "status": False,
            "message": "Meta description missing",
            "description": None,
        }

    # Extract the "content" attribute, which holds the actual
    # description text. Use .get() since the attribute could be
    # absent even if the tag itself exists.
    description_text = meta_tag.get("content")

    # Strip whitespace so a content="   " counts as empty too.
    # Guard against None before calling .strip().
    description_text = description_text.strip() if description_text else ""

    # A meta tag that exists but has no real content counts as
    # "missing" for SEO purposes.
    if not description_text:
        return {
            "status": False,
            "message": "Meta description missing",
            "description": None,
        }

    # Meta description tag exists and has actual content.
    return {
        "status": True,
        "message": "Meta description found",
        "description": description_text,
    }


def _is_hidden(tag):
    """
    Best-effort check for whether an HTML element is hidden from
    visitors (and therefore not meaningful for on-page SEO signals).

    Checks for the most common ways content is hidden in HTML/CSS:
    - the boolean `hidden` attribute
    - `aria-hidden="true"` (hidden from assistive tech / not real content)
    - inline `style="display: none"` or `style="visibility: hidden"`

    This is not exhaustive (it can't detect hiding via an external
    CSS file or JavaScript), but it covers the common inline cases.

    Args:
        tag (bs4.element.Tag): The HTML tag to check.

    Returns:
        bool: True if the tag appears to be hidden.
    """
    # The plain HTML boolean attribute: <h1 hidden>...</h1>
    if tag.has_attr("hidden"):
        return True

    # aria-hidden="true" marks content as not meaningful/visible.
    if tag.get("aria-hidden", "").strip().lower() == "true":
        return True

    # Inline CSS that visually hides the element.
    style = tag.get("style", "").lower().replace(" ", "")
    if "display:none" in style or "visibility:hidden" in style:
        return True

    return False


def check_h1(soup):
    """
    Check whether the page contains any meaningful <h1> tags and
    collect their text content.

    An H1 is only counted if it is all of the following:
    - not hidden (no `hidden` attribute, `aria-hidden="true"`, or
      inline display:none / visibility:hidden style)
    - not empty (has real text after stripping whitespace)
    - at least 5 characters long (very short text, like a single
      icon character or "Hi", isn't a meaningful heading for SEO)

    Args:
        soup (BeautifulSoup | None): Parsed HTML of the page, or
            None if the page failed to load/parse.

    Returns:
        dict: {
            "status": bool,      # True if at least one meaningful H1 was found
            "message": str,      # Human-readable result summary
            "h1_tags": list[str] # Text of every meaningful H1 tag found (empty if none)
        }
    """
    # Guard clause: if crawling/parsing failed upstream, soup will
    # be None. Handle that up front so we don't raise an
    # AttributeError by calling .find_all() on None.
    if soup is None:
        return {
            "status": False,
            "message": "No H1 tags found",
            "h1_tags": [],
        }

    # find_all() returns a list of every <h1> tag on the page
    # (could be zero, one, or many).
    h1_elements = soup.find_all("h1")

    h1_tags = []
    for h1 in h1_elements:
        # Skip H1s that are hidden from visitors - they don't carry
        # real SEO/UX weight even if technically present in the HTML.
        if _is_hidden(h1):
            continue

        # Clean up the text content (strips whitespace/newlines).
        text = h1.get_text(strip=True)

        # Skip empty H1s and H1s shorter than 5 characters - too
        # short to be a meaningful heading (e.g. an icon glyph or "Hi").
        if len(text) < 5:
            continue

        h1_tags.append(text)

    # No meaningful H1 tags found on the page.
    if not h1_tags:
        return {
            "status": False,
            "message": "No H1 tags found",
            "h1_tags": [],
        }

    # At least one meaningful H1 tag was found.
    return {
        "status": True,
        "message": "H1 tags found",
        "h1_tags": h1_tags,
    }


def check_image_alts(soup):
    """
    Check all <img> tags on the page for alt text.

    Args:
        soup (BeautifulSoup | None): Parsed HTML of the page, or
            None if the page failed to load/parse.

    Returns:
        dict: {
            "status": bool,       # True if the check ran (see note below)
            "message": str,       # Human-readable result summary
            "total_images": int,  # Total number of <img> tags found
            "with_alt": int,      # Images that have non-empty alt text
            "without_alt": int    # Images missing alt text (or empty alt)
        }
    """
    # Guard clause: if crawling/parsing failed upstream, soup will
    # be None. There's nothing to count, so report zeros and a
    # False status to signal the check couldn't actually run.
    if soup is None:
        return {
            "status": False,
            "message": "Image check failed: no page to check",
            "total_images": 0,
            "with_alt": 0,
            "without_alt": 0,
        }

    # find_all() returns every <img> tag on the page (could be zero,
    # one, or many).
    img_tags = soup.find_all("img")
    total_images = len(img_tags)

    with_alt = 0
    without_alt = 0

    for img in img_tags:
        # .get("alt") returns None if the attribute is absent, or
        # the attribute's string value (which could be "") if present.
        alt_text = img.get("alt")

        # Strip whitespace so alt="   " counts as missing too.
        # Guard against None before calling .strip().
        alt_text = alt_text.strip() if alt_text else ""

        if alt_text:
            with_alt += 1
        else:
            without_alt += 1

    # The check itself always "succeeds" as long as we had a page
    # to inspect - status True just means the count was performed,
    # regardless of how many images are missing alt text.
    return {
        "status": True,
        "message": "Image check completed",
        "total_images": total_images,
        "with_alt": with_alt,
        "without_alt": without_alt,
    }


if __name__ == "__main__":
    # Quick manual test using the crawler from crawler.py.
    from crawler import get_page

    test_url = "https://pypi.org"
    soup = get_page(test_url)

    title_result = check_title(soup)
    print(title_result)

    meta_result = check_meta_description(soup)
    print(meta_result)

    h1_result = check_h1(soup)
    print(h1_result)

    image_result = check_image_alts(soup)
    print(image_result)
