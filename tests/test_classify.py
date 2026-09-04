import os
from consiz.classify import classify
from consiz.models import CapturedContext, CaptureMethod, ContentType


def ctx(text, method=CaptureMethod.TEXT_SELECTION, paths=None):
    return CapturedContext("test", method, text, paths=paths or [])


def test_question():
    assert classify(ctx("What is the capital of Australia?")).content_type == ContentType.QUESTION
    assert classify(ctx("how does TCP handshake work")).content_type == ContentType.QUESTION


def test_plain_text():
    r = classify(ctx("The quick brown fox jumps over the lazy dog. It was a sunny day."))
    assert r.content_type == ContentType.TEXT_SELECTION and r.confidence >= 0.75


def test_csv_text():
    r = classify(ctx("name,qty,price\napple,3,1.20\npear,5,0.80\nkiwi,2,2.10"))
    assert r.content_type == ContentType.CSV_DATA


def test_tsv_text():
    r = classify(ctx("a\tb\n1\t2\n3\t4\n5\t6"))
    assert r.content_type == ContentType.CSV_DATA


def test_prose_with_commas_is_not_csv():
    r = classify(ctx("Apples, pears, and kiwis are fruit.\nDogs, cats, and birds are animals.\nOne, two, three."))
    assert r.content_type != ContentType.CSV_DATA


def test_folder_and_file(tmp_path):
    f = tmp_path / "x.txt"; f.write_text("hi")
    assert classify(ctx(str(tmp_path), CaptureMethod.FOLDER_PATH, [str(tmp_path)])).content_type == ContentType.FOLDER
    assert classify(ctx(str(f), CaptureMethod.FILE_PATH, [str(f)])).content_type == ContentType.FILE
    c = tmp_path / "d.csv"; c.write_text("a,b\n1,2\n")
    assert classify(ctx(str(c), CaptureMethod.FILE_PATH, [str(c)])).content_type == ContentType.CSV_DATA


def test_selected_text_that_is_a_path(tmp_path):
    assert classify(ctx(str(tmp_path))).content_type == ContentType.FOLDER


def test_empty():
    assert classify(ctx("   ")).content_type == ContentType.UNSUPPORTED
