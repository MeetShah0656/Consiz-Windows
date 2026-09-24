"""Tests for consiz/languages.py."""
import pytest
from consiz import languages


def test_language_normalization():
    assert languages.normalize("hindi") == "hindi"
    assert languages.normalize("HINDI") == "hindi"
    assert languages.normalize("  Gujarati  ") == "gujarati"
    assert languages.normalize("unknown_lang") == "auto"
    assert languages.normalize(None) == "auto"


def test_language_labels():
    assert languages.label("hindi") == "हिन्दी"
    assert languages.label("gujarati") == "ગુજરાતી"
    assert languages.label("english") == "English"
    assert languages.label("auto") == "Auto"


def test_prompt_rules():
    auto_rule = languages.prompt_rule("auto")
    assert "reply in the same language" in auto_rule
    assert "KIND: ..." in auto_rule

    hindi_rule = languages.prompt_rule("hindi")
    assert "ALWAYS write the answer in Hindi" in hindi_rule
    assert "Devanagari script" in hindi_rule

    gujarati_rule = languages.prompt_rule("gujarati")
    assert "ALWAYS write the answer in Gujarati" in gujarati_rule
    assert "Gujarati script" in gujarati_rule


def test_script_detection():
    # Gujarati text
    gu_text = "આ પ્રોજેક્ટ ખુબ સરસ રીતે બનાવવામાં આવ્યો છે."
    assert languages.detect(gu_text) == "gujarati"

    # Hindi text (Devanagari)
    hi_text = "यह एक बहुत ही महत्वपूर्ण दस्तावेज़ है।"
    assert languages.detect(hi_text) == "hindi"

    # Punjabi text (Gurmukhi)
    pa_text = "ਇਹ ਇੱਕ ਬਹੁਤ ਹੀ ਮਹੱਤਵਪੂਰਨ ਫਾਇਲ ਹੈ।"
    assert languages.detect(pa_text) == "punjabi"

    # Bengali text
    bn_text = "এটি একটি খুব গুরুত্বপূর্ণ নথি।"
    assert languages.detect(bn_text) == "bengali"

    # Pure English returns None
    en_text = "This is pure english prose without non-latin scripts."
    assert languages.detect(en_text) is None


def test_effective_language():
    assert languages.effective("hindi", "some text") == "hindi"
    assert languages.effective("auto", "આ એક ગુજરાતી વાક્ય છે") == "gujarati"
    assert languages.effective("auto", "Just simple english") == "auto"
