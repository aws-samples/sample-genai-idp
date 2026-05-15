// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Compare two version strings (PEP 440 / semver-ish).
 *
 * Handles the common cases produced by `publish.py`:
 *   - `0.5.10`   < `0.5.11`
 *   - `0.5.11.dev1` < `0.5.11`            (pre-releases sort before final)
 *   - `0.5.11rc1`  < `0.5.11`
 *   - `0.5.11`     < `0.5.12`
 *
 * Returns:
 *   - negative when `a < b`
 *   - 0       when `a == b`
 *   - positive when `a > b`
 *
 * Unparsable inputs sort as zero-versions (i.e. older than any well-formed
 * version), so a corrupt response can't make us claim an "update" is needed.
 */
export const compareVersions = (a: string, b: string): number => {
  const pa = parseVersion(a);
  const pb = parseVersion(b);

  // Compare numeric segments first.
  const len = Math.max(pa.numbers.length, pb.numbers.length);
  for (let i = 0; i < len; i += 1) {
    const na = pa.numbers[i] ?? 0;
    const nb = pb.numbers[i] ?? 0;
    if (na !== nb) return na - nb;
  }

  // Equal numeric segments: a pre-release (dev/rc/alpha/beta/etc.) sorts
  // BEFORE a final release with the same numbers.
  if (pa.preRelease && !pb.preRelease) return -1;
  if (!pa.preRelease && pb.preRelease) return 1;

  // Both are pre-releases — compare the pre-release tag lexicographically;
  // best-effort, good enough for `dev1` < `dev2` etc.
  if (pa.preRelease && pb.preRelease) {
    return pa.preRelease.localeCompare(pb.preRelease, undefined, { numeric: true });
  }

  return 0;
};

/**
 * True iff `latest` is strictly newer than `current`.
 */
export const isNewerVersion = (current: string, latest: string): boolean => compareVersions(current, latest) < 0;

interface ParsedVersion {
  numbers: number[];
  preRelease: string;
}

const parseVersion = (input: string): ParsedVersion => {
  if (!input) return { numbers: [], preRelease: '' };
  const trimmed = input.trim().replace(/^v/i, '');

  // Split into "X.Y.Z" prefix + everything that follows (the pre-release tag).
  // e.g. "0.5.11.dev1" → ["0","5","11"], "dev1"
  //      "0.5.11rc1"   → ["0","5","11"], "rc1"
  //      "0.5.11"      → ["0","5","11"], ""
  const match = trimmed.match(/^([0-9]+(?:\.[0-9]+)*)([.\-_]?[A-Za-z].*)?$/);
  if (!match) return { numbers: [], preRelease: trimmed };
  const numericPart = match[1];
  const suffix = (match[2] ?? '').replace(/^[.\-_]/, '').toLowerCase();
  const numbers = numericPart.split('.').map((n) => parseInt(n, 10) || 0);
  return { numbers, preRelease: suffix };
};
