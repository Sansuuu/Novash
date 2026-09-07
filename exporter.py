"""
exporter.py

Export utilities for Novash.

Handles saving report data (or any dictionary) to disk as a
pretty-printed JSON file.
"""

import json
import os


def export_json(data, filename):
    """
    Save a Python dictionary as a pretty-printed JSON file.

    Args:
        data (dict): The data to export. Should be JSON-serializable
            (dicts, lists, strings, numbers, booleans, None).
        filename (str): Path/name of the file to write to, e.g.
            "report.json" or "reports/pypi_report.json".

    Returns:
        bool: True if the file was written successfully, False if
        any error occurred.
    """
    # Basic input validation before touching the filesystem.
    if not isinstance(data, dict):
        print("Export failed: data must be a dictionary.")
        return False

    if not isinstance(filename, str) or not filename.strip():
        print("Export failed: filename must be a non-empty string.")
        return False

    filename = filename.strip()

    try:
        # If the filename includes a directory path that doesn't
        # exist yet (e.g. "reports/output.json"), create it first
        # so open() doesn't fail with FileNotFoundError.
        directory = os.path.dirname(filename)
        if directory:
            os.makedirs(directory, exist_ok=True)

        # Open the file for writing text, using UTF-8 so any
        # non-ASCII characters (accents, symbols, emojis) are
        # handled correctly.
        with open(filename, "w", encoding="utf-8") as f:
            # indent=4 pretty-prints the JSON with 4-space
            # indentation for readability.
            # ensure_ascii=False keeps non-ASCII characters as-is
            # instead of escaping them (e.g. "é" instead of "\u00e9").
            json.dump(data, f, indent=4, ensure_ascii=False)

        return True

    except TypeError as e:
        # Raised by json.dump() when data contains something that
        # can't be converted to JSON (e.g. a custom object, a set).
        print(f"Export failed: data is not JSON-serializable ({e}).")
        return False

    except PermissionError:
        print(f"Export failed: permission denied writing to '{filename}'.")
        return False

    except OSError as e:
        # Catches other filesystem issues: invalid path, disk full,
        # read-only filesystem, etc.
        print(f"Export failed: could not write to '{filename}' ({e}).")
        return False

    except Exception as e:
        # Catch-all safety net for anything unexpected, so the
        # function never crashes the caller - it just reports False.
        print(f"Export failed: an unexpected error occurred ({e}).")
        return False


if __name__ == "__main__":
    # Quick manual test.
    sample_report = {
        "website": "https://pypi.org",
        "title": "PyPI · The Python Package Index",
        "meta_description": "The Python Package Index (PyPI) is a repository of software.",
        "h1_tags": ["Find, install and publish Python packages"],
        "score": 82,
        "max_score": 100,
    }

    success = export_json(sample_report, "sample_report.json")
    print(f"Export successful: {success}")

    # Test failure case: non-serializable data (a set isn't valid JSON).
    bad_data = {"tags": {1, 2, 3}}
    success = export_json(bad_data, "bad_report.json")
    print(f"Export successful (expected False): {success}")

    # Test failure case: wrong data type entirely.
    success = export_json(["not", "a", "dict"], "list_report.json")
    print(f"Export successful (expected False): {success}")
