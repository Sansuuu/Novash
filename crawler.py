"""
crawler.py

A simple utility for downloading and parsing a webpage using
requests + BeautifulSoup.
"""

import requests
from requests.exceptions import (
    Timeout,
    ConnectionError,
    HTTPError,
    InvalidURL,
    MissingSchema,
    RequestException,
)
from bs4 import BeautifulSoup


def get_page(url, timeout=10, parser="html.parser"):
    """
    Download a webpage and return it as a BeautifulSoup object.

    Args:
        url (str): The URL of the webpage to fetch.
        timeout (int | float): Max seconds to wait for a response
            before giving up (default: 10).
        parser (str): The parser BeautifulSoup should use
            (default: "html.parser"; "lxml" is faster if installed).

    Returns:
        BeautifulSoup | None: Parsed HTML of the page, or None if
        the request failed for any reason (network error, bad URL,
        timeout, non-2xx status code, etc.).
    """
    # Basic type/sanity check before even hitting the network.
    if not isinstance(url, str) or not url.strip():
        print("Invalid URL: URL must be a non-empty string.")
        return None

    # A User-Agent header helps avoid being blocked by sites that
    # reject requests with no/blank User-Agent (common bot filter).
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; SimpleCrawler/1.0; "
            "+https://example.com/bot)"
        )
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)

        # Raises HTTPError for 4xx/5xx responses so we can catch
        # them below instead of silently parsing an error page.
        response.raise_for_status()

    except MissingSchema:
        # e.g. "example.com" instead of "https://example.com"
        print(f"Invalid URL (missing scheme like 'http://'): {url}")
        return None

    except InvalidURL:
        print(f"Invalid URL: {url}")
        return None

    except Timeout:
        print(f"Request timed out after {timeout}s: {url}")
        return None

    except ConnectionError:
        # DNS failure, refused connection, no internet, etc.
        print(f"Failed to connect to: {url}")
        return None

    except HTTPError as e:
        # Server responded, but with an error status code.
        print(f"HTTP error for {url}: {e}")
        return None

    except RequestException as e:
        # Catch-all for any other requests-related error.
        print(f"An error occurred while requesting {url}: {e}")
        return None

    # Parse the raw HTML text into a BeautifulSoup object.
    try:
        soup = BeautifulSoup(response.text, parser)
    except Exception as e:
        print(f"Failed to parse HTML for {url}: {e}")
        return None

    return soup


if __name__ == "__main__":
    # Simple demo/manual test when running this file directly.
    test_url = "https://example.com"
    page = get_page(test_url)

    if page is not None:
        print(f"Successfully fetched: {test_url}")
        title = page.find("title")
        print(f"Page title: {title.get_text(strip=True) if title else 'N/A'}")
    else:
        print(f"Could not fetch: {test_url}")
