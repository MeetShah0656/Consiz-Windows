"""Getting Consiz to people: the download page on the server and the release script that builds the zip."""
import hashlib
import importlib.util
import pathlib
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("make_release", ROOT / "scripts" / "make_release.py")
make_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_release)


# ---------------------------------------------------------------- the home page and /download
@pytest.fixture
def web(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("google.auth")
    from fastapi.testclient import TestClient
    from server import app as srv
    for name in ("DOWNLOAD_URL", "LATEST_VERSION", "DOWNLOAD_SHA256"):
        monkeypatch.delenv(name, raising=False)
    return TestClient(srv.app, follow_redirects=False)


def test_the_home_page_says_so_when_there_is_no_download_yet(web):
    page = web.get("/").text
    assert "has not been published yet" in page and 'href="/download"' not in page
    assert "Windows protected your PC" in page and "More info" in page, "the steps are there either way"
    assert 'href="/privacy"' in page, "the privacy link Google checks must stay"
    r = web.get("/download")
    assert r.status_code == 404 and "not been published" in r.text


def test_with_a_download_link_the_page_shows_a_button_and_download_forwards_to_it(web, monkeypatch):
    url = "https://github.com/MeetShah0656/Consiz-Windows/releases/download/v0.4.0/Consiz-0.4.0-windows.zip"
    monkeypatch.setenv("DOWNLOAD_URL", url)
    monkeypatch.setenv("LATEST_VERSION", "0.4.0")
    monkeypatch.setenv("DOWNLOAD_SHA256", "ab" * 32)
    page = web.get("/").text
    assert 'href="/download"' in page and "Download Consiz for Windows 0.4.0" in page and ("ab" * 32) in page
    r = web.get("/download")
    assert r.status_code == 302 and r.headers["location"] == url


@pytest.mark.parametrize("bad", ["http://example.com/Consiz.zip", "javascript:alert(1)", "ftp://x/y", "//evil.example/x"])
def test_only_an_https_link_is_ever_offered(web, monkeypatch, bad):
    monkeypatch.setenv("DOWNLOAD_URL", bad)
    assert 'href="/download"' not in web.get("/").text
    assert web.get("/download").status_code == 404


# ---------------------------------------------------------------- the release script
def _app_folder(tmp_path, extra=()):
    dist = tmp_path / "dist" / "Consiz"
    (dist / "_internal" / "certifi").mkdir(parents=True)
    (dist / "Consiz.exe").write_bytes(b"MZ" + b"0" * 5000)
    (dist / "_internal" / "base.dll").write_bytes(b"d" * 3000)
    (dist / "_internal" / "certifi" / "cacert.pem").write_text("public certificate authorities")
    for name in extra:
        (dist / name).write_text("x")
    return dist


def test_the_zip_has_one_top_folder_and_a_matching_checksum(tmp_path):
    dist = _app_folder(tmp_path)
    target = tmp_path / "release" / "Consiz-0.4.0-windows.zip"
    sha = make_release.make_zip(dist, target)
    with zipfile.ZipFile(target) as z:
        names = z.namelist()
        assert z.testzip() is None
    assert "Consiz/Consiz.exe" in names and "Consiz/_internal/base.dll" in names
    assert all(n.startswith("Consiz/") for n in names), "unzipping must not scatter files into the person's folder"
    assert sha == hashlib.sha256(target.read_bytes()).hexdigest()


def test_a_clean_folder_passes_and_the_public_certificate_list_is_allowed(tmp_path):
    assert make_release.check_folder(_app_folder(tmp_path)) >= 0


@pytest.mark.parametrize("private", [".env", "prefs.json", "session.json", "consiz.log", "profile.md", "id.pfx", "private.key"])
def test_private_files_stop_the_release(tmp_path, private):
    dist = _app_folder(tmp_path, extra=(private,))
    with pytest.raises(make_release.ReleaseError, match="private or unwanted"):
        make_release.check_folder(dist)


def test_a_folder_without_the_exe_or_its_support_folder_is_refused(tmp_path):
    with pytest.raises(make_release.ReleaseError, match="no Consiz.exe"):
        make_release.check_folder(tmp_path)
    dist = _app_folder(tmp_path)
    (dist / "_internal" / "base.dll").unlink()
    (dist / "_internal" / "certifi" / "cacert.pem").unlink()
    (dist / "_internal" / "certifi").rmdir()
    (dist / "_internal").rmdir()
    with pytest.raises(make_release.ReleaseError, match="_internal"):
        make_release.check_folder(dist)


def test_the_script_prints_the_publish_command_and_changes_nothing_online(tmp_path, capsys, monkeypatch):
    dist = _app_folder(tmp_path)
    out = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["make_release.py", "--dist", str(dist), "--out", str(out), "--version", "9.9.9",
                                     "--repo", "someone/repo"])
    assert make_release.main() == 0
    text = capsys.readouterr().out
    assert "gh release create v9.9.9" in text and "--repo someone/repo" in text and "nothing has been published yet" in text
    assert "DOWNLOAD_URL=https://github.com/someone/repo/releases/download/v9.9.9/Consiz-9.9.9-windows.zip" in text
    sha_file = (out / "Consiz-9.9.9-windows.zip.sha256").read_text()
    assert sha_file.split()[0] in text and sha_file.split()[1] == "Consiz-9.9.9-windows.zip"
    assert (out / "RELEASE_NOTES.md").read_text().startswith("# Consiz 9.9.9 for Windows")
