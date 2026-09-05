"""Tests for Context-First Analysis: Deep Folder/Subfolder inspection and Browser Website Context."""
import pytest
from consiz.models import CapturedContext, CaptureMethod, ContentType
from consiz.deterministic import folder_metadata, format_folder, build_folder_llm_context
from consiz.platform.win32.capture import clean_browser_title, build_browser_context, KNOWN_DOMAINS
from consiz.router import process


def test_deep_folder_subfolder_analysis(tmp_path):
    # Setup nested folder hierarchy
    (tmp_path / "README.md").write_text("# Master Project\nTop level guide.")
    (tmp_path / "requirements.txt").write_text("fastapi>=0.100\nuvicorn\n")
    
    # Subfolder 1: src with subfolder utils
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()")
    utils = src / "utils"
    utils.mkdir()
    (utils / "math.py").write_text("def add(a, b): return a + b")

    # Subfolder 2: docs with markdown spec
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "spec.md").write_text("# Technical Specification\nExplaining system internals.")

    # Subfolder 3: ignored clutter directory
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "dummy.js").write_text("// dummy")

    md = folder_metadata(str(tmp_path))

    # Assertions on subfolders discovery
    assert md["files"] == 5  # README.md, requirements.txt, app.py, math.py, spec.md (minus node_modules)
    assert md["folders"] >= 3  # src, src/utils, docs
    assert "node_modules" in md["skipped_folders"]

    # Verify subfolder inventory
    tree_paths = [sf["rel_path"] for sf in md["subfolders_tree"]]
    assert any("src" in p for p in tree_paths)
    assert any("docs" in p for p in tree_paths)

    # Verify documents extracted across subfolders
    previews = md["previews"]
    preview_names = [p[0] for p in previews]
    assert any("README.md" in n for n in preview_names)
    assert any("spec.md" in n for n in preview_names)

    # Verify format_folder and dossier
    formatted = format_folder(md)
    assert "Subfolders:" in formatted
    assert "Key Documents:" in formatted

    dossier = build_folder_llm_context(md)
    assert "--- Subfolder Architecture & Directory Tree ---" in dossier
    assert "--- Key Documents & File Contents Across Subfolders ---" in dossier
    assert "Technical Specification" in dossier


def test_browser_clean_title():
    # Chrome
    title1, brand1 = clean_browser_title("Attention Is All You Need - arXiv - Google Chrome")
    assert title1 == "Attention Is All You Need"
    assert brand1 == "arXiv"

    # Edge with and without zero-width space
    title2, brand2 = clean_browser_title("Python 3.14 Documentation - Python.org - Microsoft Edge")
    assert title2 == "Python 3.14 Documentation"
    assert brand2 == "Python.org"

    # Brave
    title3, brand3 = clean_browser_title("astropy/astropy: Core Python library - GitHub - Brave")
    assert "astropy" in title3
    assert brand3 == "GitHub"


def test_browser_context_known_domain():
    ctx = build_browser_context(0, "chrome.exe", "Quantum computing - Wikipedia - Google Chrome")
    assert ctx["browser"] == "Google Chrome"
    assert "Quantum computing" in ctx["page_title"]
    assert ctx["site_name"] == "Wikipedia"
    assert "encyclopedia" in ctx["site_context"].lower()


def test_router_web_context_routing():
    raw_text = "Transformers rely entirely on self-attention mechanisms without recurrent layers."
    ctx = CapturedContext(
        source_app="Google Chrome",
        capture_method=CaptureMethod.TEXT_SELECTION,
        raw_content=raw_text,
        source_title="Attention Is All You Need - arXiv",
        source_url="https://arxiv.org/abs/1706.03762",
        source_domain="arxiv.org",
        source_meta={"site_context": "Scientific research paper repository (arXiv.org)"}
    )

    res = process(ctx)
    # Result should acknowledge the source domain badge
    assert "arxiv.org" in res.source_app
    assert "🌐" in res.source_app
    assert res.content_type.startswith("TEXT_SELECTION")


def test_router_folder_routing(tmp_path):
    (tmp_path / "README.md").write_text("# Project Alpha\nMain readme.")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "code.py").write_text("print('hello')")

    ctx = CapturedContext(
        source_app="explorer.exe",
        capture_method=CaptureMethod.FOLDER_PATH,
        raw_content=str(tmp_path),
        paths=[str(tmp_path)]
    )

    res = process(ctx)
    assert res.title == "Folder Analysis"
    assert "📁" in res.source_app
    assert "Subfolders:" in res.body
