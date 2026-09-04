import pytest
from consiz.deterministic import analyze_csv, folder_metadata, file_metadata
from consiz.grounding import check_numbers


CSV = "item,qty,price\napple,3,1.5\npear,5,2\nkiwi,2,4\n"


def test_csv_exact_math():
    r = analyze_csv(CSV, is_path=False)
    assert r.row_count == 3
    q = r.computed_stats["columns"]["qty"]
    assert q["sum"] == 10 and q["mean"] == pytest.approx(3.3333) and q["min"] == 2 and q["max"] == 5
    assert r.computed_stats["columns"]["price"]["sum"] == 7.5
    assert r.computed_stats["columns"]["item"]["unique"] == 3


def test_csv_currency_coercion():
    r = analyze_csv("m,rev\njan,\"$1,200\"\nfeb,$800\n", is_path=False)
    assert r.computed_stats["columns"]["rev"]["sum"] == 2000


def test_csv_malformed():
    with pytest.raises(ValueError):
        analyze_csv("", is_path=False)


def test_folder_and_file(tmp_path):
    (tmp_path / "a.txt").write_text("hello world")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("print(1)")
    md = folder_metadata(str(tmp_path))
    assert md["files"] == 2 and md["folders"] == 1
    fm = file_metadata(str(tmp_path / "a.txt"))
    assert fm["preview"] == "hello world"


def test_grounding_flags_invented_numbers():
    stats = {"columns": {"qty": {"sum": 10, "mean": 3.33}}}
    assert check_numbers("The total quantity is 10 with a mean of 3.33.", stats) == []
    assert len(check_numbers("The total is 42.", stats)) == 1
