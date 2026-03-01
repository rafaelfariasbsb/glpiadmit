<?php

/**
 * @license GPL-3.0-or-later
 */

namespace GlpiPlugin\Glpiadmit;

class Validators
{

    /**
     * Remove accents and special characters from a name.
     * Uses intl transliterator with iconv fallback.
     */
    public static function normalizeName(string $name): string
    {
        $name = trim($name);

        if (extension_loaded('intl')) {
            $transliterated = transliterator_transliterate('Any-Latin; Latin-ASCII', $name);
            if ($transliterated !== false) {
                return $transliterated;
            }
        }

        // Fallback: iconv
        $converted = iconv('UTF-8', 'ASCII//TRANSLIT', $name);
        return $converted !== false ? $converted : $name;
    }

    /**
     * Generate sAMAccountName from first and last name.
     * Format: first initial + last name, lowercase, no accents, max 20 chars.
     *
     * @throws \InvalidArgumentException If first or last name is empty after normalization.
     */
    public static function generateSamAccountName(string $firstName, string $lastName): string
    {
        $first = strtolower(preg_replace('/[^a-z0-9]/', '', strtolower(self::normalizeName($firstName))));
        $last = strtolower(preg_replace('/[^a-z0-9]/', '', strtolower(self::normalizeName($lastName))));

        if ($first === '' || $last === '') {
            throw new \InvalidArgumentException('First and last name are required to generate sAMAccountName');
        }

        $sam = $first[0] . $last;

        return substr($sam, 0, 20);
    }

    /**
     * Generate userPrincipalName.
     */
    public static function generateUpn(string $sam, string $upnSuffix): string
    {
        return $sam . $upnSuffix;
    }

    /**
     * Generate display name.
     */
    public static function generateDisplayName(string $firstName, string $lastName): string
    {
        return trim($firstName) . ' ' . trim($lastName);
    }

    /**
     * Escape special characters in LDAP filter values (RFC 4515).
     * Uses PHP built-in ldap_escape() for complete and correct escaping.
     */
    public static function sanitizeLdapValue(string $value): string
    {
        return ldap_escape($value, '', LDAP_ESCAPE_FILTER);
    }

    /**
     * Escape special characters in DN components (RFC 4514).
     * Uses PHP built-in ldap_escape() for complete and correct escaping.
     */
    public static function sanitizeDnComponent(string $value): string
    {
        return ldap_escape($value, '', LDAP_ESCAPE_DN);
    }
}
