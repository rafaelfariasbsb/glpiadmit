import string

from app.utils.password import generate_temporary_password


class TestGenerateTemporaryPassword:
    def test_default_length(self):
        password = generate_temporary_password()
        assert len(password) == 16

    def test_custom_length(self):
        password = generate_temporary_password(length=24)
        assert len(password) == 24

    def test_minimum_length_enforced(self):
        password = generate_temporary_password(length=4)
        assert len(password) == 12

    def test_contains_uppercase(self):
        password = generate_temporary_password()
        assert any(c in string.ascii_uppercase for c in password)

    def test_contains_lowercase(self):
        password = generate_temporary_password()
        assert any(c in string.ascii_lowercase for c in password)

    def test_contains_digit(self):
        password = generate_temporary_password()
        assert any(c in string.digits for c in password)

    def test_contains_special(self):
        password = generate_temporary_password()
        assert any(c in "!@#$%&*" for c in password)

    def test_unique_passwords(self):
        """Senhas geradas devem ser diferentes (probabilisticamente)."""
        passwords = {generate_temporary_password() for _ in range(100)}
        assert len(passwords) == 100

    def test_no_invalid_chars(self):
        """Senhas devem conter apenas caracteres do alfabeto definido."""
        valid_chars = set(string.ascii_letters + string.digits + "!@#$%&*")
        for _ in range(50):
            password = generate_temporary_password()
            assert all(c in valid_chars for c in password)
