"""
sitemap_checker.py

Checks whether a website has a valid sitemap.xml file at its root.
"""

import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urlunparse

import requests
from requests.exceptions import (
    Timeout,
    ConnectionError,
    HTTPError,
    InvalidURL,
    MissingSchema,
    RequestException,
)


def _build_sitemap_url(url):
    """
    Convert any URL into that site's root sitemap.xml URL.

    Examples:
        https://example.com               -> https://example.com/sitemap.xml
        https://example.com/some/page?q=1 -> https://example.com/sitemap.xml
        http://example.com:8080/blog      -> http://example.com:8080/sitemap.xml

    Args:
        url (str): Any URL on the target site.

    Returns:
        str: The sitemap.xml URL for that site's root.

    Raises:
        ValueError: If the URL has no scheme (http/https) or no
            network location (domain), since sitemap.xml can't be
            built from an incomplete URL.
    """
    parsed = urlparse(url)

    # A valid URL needs both a scheme (http/https) and a netloc
    # (domain, e.g. "example.com"). Without these we can't safely
    # build a sitemap.xml URL.
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"URL is missing a scheme or domain: {url}")

    # Rebuild the URL using only scheme + netloc, discarding any
    # path, query string, or fragment, then append "/sitemap.xml".
    # sitemap.xml conventionally lives at the site's root, regardless
    # of which page URL was originally provided.
    root = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    return f"{root}/sitemap.xml"


def _looks_like_sitemap(xml_content):
    """
    Check whether a string of XML content is a valid, well-formed
    sitemap document.

    A real sitemap.xml is either:
    - a <urlset> (a normal sitemap listing individual page URLs), or
    - a <sitemapindex> (an index that points to other sitemap files)

    Args:
        xml_content (str): The raw response body to inspect.

    Returns:
        bool: True if the content parses as XML and its root tag
        matches one of the expected sitemap root elements.
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        # Malformed XML - not a valid sitemap, but this must not
        # raise/crash the caller.
        return False

    # XML root tags are often namespaced, e.g.
    # "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset".
    # Strip any "{namespace}" prefix before comparing the tag name.
    tag = root.tag.split("}")[-1].lower()

    return tag in ("urlset", "sitemapindex")


def check_sitemap(url, timeout=10):
    """
    Check whether a website has a valid sitemap.xml file.

    Args:
        url (str): Any URL belonging to the site to check
            (e.g. "https://example.com" or "https://example.com/blog").
        timeout (int | float): Max seconds to wait for a response
            before giving up (default: 10).

    Returns:
        dict: {
            "status": bool,       # True if a valid sitemap was found
            "message": str,       # Human-readable result summary
            "url": str | None,    # The sitemap.xml URL that was checked
            "status_code": int | None  # HTTP status code, if a response was received
        }
    """
    # Basic type/sanity check before even building a URL.
    if not isinstance(url, str) or not url.strip():
        return {
            "status": False,
            "message": "Invalid URL: URL must be a non-empty string",
            "url": None,
            "status_code": None,
        }

    # Build the sitemap.xml URL from whatever page URL was given.
    try:
        sitemap_url = _build_sitemap_url(url.strip())
    except ValueError as e:
        return {
            "status": False,
            "message": f"Invalid URL: {e}",
            "url": None,
            "status_code": None,
        }

    # A realistic User-Agent avoids being blocked by sites that
    # reject requests with no/blank User-Agent.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; NovashBot/1.0; "
            "+https://example.com/bot)"
        )
    }

    try:
        response = requests.get(sitemap_url, headers=headers, timeout=timeout)

    except MissingSchema:
        # e.g. "example.com" instead of "https://example.com"
        return {
            "status": False,
            "message": f"Invalid URL (missing scheme like 'http://'): {sitemap_url}",
            "url": sitemap_url,
            "status_code": None,
        }

    except InvalidURL:
        return {
            "status": False,
            "message": f"Invalid URL: {sitemap_url}",
            "url": sitemap_url,
            "status_code": None,
        }

    except Timeout:
        return {
            "status": False,
            "message": f"Request timed out after {timeout}s: {sitemap_url}",
            "url": sitemap_url,
            "status_code": None,
        }

    except ConnectionError:
        # DNS failure, refused connection, no internet, etc.
        return {
            "status": False,
            "message": f"Failed to connect to: {sitemap_url}",
            "url": sitemap_url,
            "status_code": None,
        }

    except HTTPError as e:
        # Raised only if we explicitly call raise_for_status(), but
        # kept here for completeness/safety.
        return {
            "status": False,
            "message": f"HTTP error while requesting {sitemap_url}: {e}",
            "url": sitemap_url,
            "status_code": getattr(e.response, "status_code", None),
        }

    except RequestException as e:
        # Catch-all for any other requests-related error.
        return {
            "status": False,
            "message": f"An error occurred while requesting {sitemap_url}: {e}",
            "url": sitemap_url,
            "status_code": None,
        }

    # Anything other than 200 OK means sitemap.xml isn't actually
    # available (404 Not Found is the most common case).
    if response.status_code != 200:
        return {
            "status": False,
            "message": "Sitemap missing",
            "url": sitemap_url,
            "status_code": response.status_code,
        }

    # We got a 200 response - now inspect the content to make sure
    # it's actually a well-formed sitemap, not just any 200 page
    # (some sites redirect missing URLs to a 200 "not found" page).
    # _looks_like_sitemap() never raises, even on malformed XML.
    if _looks_like_sitemap(response.text):
        return {
            "status": True,
            "message": "Sitemap found",
            "url": sitemap_url,
            "status_code": response.status_code,
        }

    return {
        "status": False,
        "message": "Sitemap found but content is not a valid XML sitemap",
        "url": sitemap_url,
        "status_code": response.status_code,
    }


if __name__ == "__main__":
    # Quick manual tests.
    print(check_sitemap("https://pypi.org"))
    print(check_sitemap("https://pypi.org/some/deep/page?x=1"))
    print(check_sitemap("not a valid url"))
    print(check_sitemap(""))
