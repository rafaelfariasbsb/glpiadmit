import pytest

from app.utils.validators import (
    normalize_name,
    generate_sam_account_name,
    generate_upn,
    generate_display_name,
    sanitize_ldap_value,
    sanitize_dn_component,
)


class TestNormalizeName:
    def test_remove_accents(self):
        assert normalize_name("Jose") == "Jose"
        assert normalize_name("Joao") == "Joao"

    def test_remove_cedilla(self):
        assert normalize_name("Conceicao") == "Conceicao"

    def test_strip_whitespace(self):
        assert normalize_name("  Rafael  ") == "Rafael"

    def test_empty_string(self):
        assert normalize_name("") == ""

    def test_preserves_ascii(self):
        assert normalize_name("John Smith") == "John Smith"


class TestGenerateSamAccountName:
    def test_basic(self):
        assert generate_sam_account_name("Rafael", "Silva") == "rsilva"

    def test_accented_names(self):
        assert generate_sam_account_name("Jose", "Goncalves") == "jgoncalves"

    def test_compound_last_name_uses_first(self):
        assert generate_sam_account_name("Maria", "Silva Santos") == "msilva"

    def test_max_20_chars(self):
        sam = generate_sam_account_name("A", "Abcdefghijklmnopqrstuvwxyz")
        assert len(sam) <= 20

    def test_lowercase(self):
        sam = generate_sam_account_name("RAFAEL", "SILVA")
        assert sam == "rsilva"

    def test_removes_invalid_chars(self):
        sam = generate_sam_account_name("Ana", "O'Brien")
        assert "'" not in sam

    def test_empty_first_name_raises(self):
        with pytest.raises(ValueError, match="obrigatorios"):
            generate_sam_account_name("", "Silva")

    def test_empty_last_name_raises(self):
        with pytest.raises(ValueError, match="obrigatorios"):
            generate_sam_account_name("Rafael", "")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            generate_sam_account_name("   ", "Silva")


class TestGenerateUpn:
    def test_basic(self):
        assert generate_upn("rsilva", "empresa.local") == "rsilva@empresa.local"

    def test_different_domain(self):
        assert generate_upn("jsmith", "corp.com") == "jsmith@corp.com"


class TestGenerateDisplayName:
    def test_basic(self):
        assert generate_display_name("Rafael", "Silva") == "Rafael Silva"

    def test_strips_whitespace(self):
        assert generate_display_name("  Rafael  ", "  Silva  ") == "Rafael Silva"


class TestSanitizeLdapValue:
    def test_escape_parentheses(self):
        assert sanitize_ldap_value("test(value)") == "test\\28value\\29"

    def test_escape_asterisk(self):
        assert sanitize_ldap_value("test*") == "test\\2a"

    def test_escape_backslash(self):
        assert sanitize_ldap_value("test\\value") == "test\\5cvalue"

    def test_escape_null(self):
        assert sanitize_ldap_value("test\x00value") == "test\\00value"

    def test_no_special_chars(self):
        assert sanitize_ldap_value("normalvalue") == "normalvalue"

    def test_multiple_special_chars(self):
        result = sanitize_ldap_value("a*b(c)d")
        assert result == "a\\2ab\\28c\\29d"


class TestSanitizeDnComponent:
    def test_escape_comma(self):
        assert sanitize_dn_component("Silva, Junior") == "Silva\\, Junior"

    def test_escape_plus(self):
        assert sanitize_dn_component("A+B") == "A\\+B"

    def test_escape_quotes(self):
        assert sanitize_dn_component('Silva "Jr"') == 'Silva \\"Jr\\"'

    def test_no_special_chars(self):
        assert sanitize_dn_component("Rafael Silva") == "Rafael Silva"

    def test_backslash_escaped_first(self):
        """Backslash deve ser escapado antes dos demais para evitar re-escape."""
        result = sanitize_dn_component("a\\,b")
        # \\ vira \\\\, depois , vira \\,
        assert result == "a\\\\\\,b"
