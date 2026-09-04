from consiz.security import redact


def test_redacts_keys_and_passwords():
    txt = "use key sk-abcdefghijklmnopqrstuvwxyz123456 and password: hunter22 ok"
    out, found = redact(txt)
    assert "sk-abc" not in out and "hunter22" not in out
    assert "OpenAI-style key" in found and "Password assignment" in found


def test_luhn_guard():
    out, found = redact("order 1234567890123456 shipped")   # fails Luhn -> untouched
    assert found == []
    out, found = redact("card 4111 1111 1111 1111")        # valid test card
    assert "Card number" in found
