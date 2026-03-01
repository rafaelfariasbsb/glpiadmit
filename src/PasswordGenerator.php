<?php

/**
 * @license GPL-3.0-or-later
 */

namespace GlpiPlugin\Glpiadmit;

class PasswordGenerator
{
    private const SPECIAL_CHARS = '!@#$%&*';
    private const MIN_LENGTH = 12;

    /**
     * Generate a cryptographically secure temporary password.
     * Guarantees at least 1 uppercase, 1 lowercase, 1 digit, 1 special character.
     * Uses random_int() (CSPRNG).
     */
    public static function generate(int $length = 16): string
    {
        $length = max($length, self::MIN_LENGTH);

        $upper   = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
        $lower   = 'abcdefghijklmnopqrstuvwxyz';
        $digits  = '0123456789';
        $special = self::SPECIAL_CHARS;
        $all     = $upper . $lower . $digits . $special;

        // Guarantee minimum complexity
        $chars = [
            $upper[random_int(0, strlen($upper) - 1)],
            $lower[random_int(0, strlen($lower) - 1)],
            $digits[random_int(0, strlen($digits) - 1)],
            $special[random_int(0, strlen($special) - 1)],
        ];

        // Fill remaining with random characters from full alphabet
        for ($i = count($chars); $i < $length; $i++) {
            $chars[] = $all[random_int(0, strlen($all) - 1)];
        }

        // Fisher-Yates shuffle with CSPRNG
        for ($i = count($chars) - 1; $i > 0; $i--) {
            $j = random_int(0, $i);
            [$chars[$i], $chars[$j]] = [$chars[$j], $chars[$i]];
        }

        return implode('', $chars);
    }
}
