"""Tests for multi-format extractors in consiz/deterministic.py."""
import json
import os
import sqlite3
import zipfile
import pytest

from consiz.deterministic import extract_text, _x_archive, _x_html, _x_notebook, _x_sqlite


def test_zip_archive_extraction(tmp_path):
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("README.md", "# Test Archive\nThis is an inner readme.")
        zf.writestr("data.csv", "a,b\n1,2\n")
        zf.writestr("script.py", "print('hello')\n")

    text = extract_text(str(zip_path), 500)
    assert text is not None
    assert "Archive content: 3 files" in text
    assert "README.md" in text
    assert "Readme preview:" in text
    assert "This is an inner readme." in text


def test_html_extraction(tmp_path):
    html_path = tmp_path / "page.html"
    html_path.write_text(
        "<html><head><title>Test Page</title><style>body { color: red; }</style></head>"
        "<body><script>alert(1);</script><h1>Welcome</h1><p>This is clean text.</p></body></html>",
        encoding="utf-8"
    )

    text = extract_text(str(html_path), 500)
    assert text is not None
    assert "Test Page" in text
    assert "Welcome" in text
    assert "This is clean text." in text
    assert "alert(1)" not in text
    assert "color: red" not in text


def test_notebook_extraction(tmp_path):
    nb_path = tmp_path / "analysis.ipynb"
    nb_content = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Title\n", "Intro markdown."]},
            {"cell_type": "code", "source": ["import math\n", "print(math.pi)"]}
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 2
    }
    nb_path.write_text(json.dumps(nb_content), encoding="utf-8")

    text = extract_text(str(nb_path), 500)
    assert text is not None
    assert "Jupyter Notebook (2 cells)" in text
    assert "Title" in text
    assert "import math" in text


def test_sqlite_extraction(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);")
    cur.execute("INSERT INTO users (name, email) VALUES ('Alice', 'alice@example.com');")
    cur.execute("INSERT INTO users (name, email) VALUES ('Bob', 'bob@example.com');")
    conn.commit()
    conn.close()

    text = extract_text(str(db_path), 500)
    assert text is not None
    assert "SQLite database: 1 table(s) found" in text
    assert "Table 'users' (2 rows)" in text
    assert "name" in text
