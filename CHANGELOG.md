# Changelog

All notable changes to qwed-finance are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
versions follow [Semantic Versioning](https://semver.org/). Releases before
v2.1.0 are documented as [GitHub Releases](https://github.com/QWED-AI/qwed-finance/releases).

## [Unreleased]

### Security

- **ISO 20022 business rules read the parsed document**
  (GHSA-mrrj-6m2q-jch9): `CrossGuard.check_business_rules` /
  `verify_iso20022_with_rules` and `UCPIntegration.verify_iso20022_payment`
  now take `IntrBkSttlmAmt` values and `Ccy` attributes from the
  defusedxml-parsed tree (local names, any namespace) instead of regex
  extraction over raw text. Previously a namespace prefix outside the
  regex character class, combined with a decoy inside a processing
  instruction, let an over-limit, disallowed-currency pacs.008 pass the
  rules and approve.
- Amount elements containing child nodes (elements, comments, processing
  instructions) and amounts that are not plain `xs:decimal` (exponents,
  grouping separators) now fail closed as unparseable. Character
  references are decoded once, by the parser.

## [3.0.0] - 2026-09-27

### Changed

- **BREAKING (npm `@qwed-ai/finance`):** SDK bridge scripts now transport
  JSON payloads through the child process's stdin with runtime boundary
  validation. Hostile or malformed inputs — strings in numeric positions,
  quote-carrying country codes, oversized payloads, mistyped token shapes —
  are rejected instead of resolving to defaults (CVSS 9.8 / 9.0, #79).

### Added

- `VerificationReceipt.get_signature(key)`: HMAC-SHA256 over the full canonical
  receipt — all 15 fields, sorted compact JSON, verifier-held key with no
  default (#44, #89).
- ISO currency and amount business limits wired into receipts (#65, #67).
- `RELEASE.md` release checklist covering version sync across Python, npm,
  uv.lock, README, and the GitHub Action pin.

### Fixed

- Fail-closed AML: canonical country codes, declared amount constraints
  enforced, malformed amounts rejected (#80, #82).
- Fail-closed sanctions: full party-field screening across multi-line values,
  shared normalized matcher, parsed UCP extraction (#81, #83).
- Fail-closed amounts: ambiguous or missing ISO amounts, unevaluable UCP
  payment amounts, empty/zero-deviation Sortino (#84, #85, #86).
- Fail-closed XML/MT/ISO message validation batch (#87).

### Testing

- 412 tests, including HMAC signature known-answer vectors and adversarial
  receipt mutation coverage.

## [2.1.0] - 2026-05-02

### Changed

- Security Audit Hardening: fail-closed enforcement in the OpenResponses
  integration, unified AML high-risk country list across all paths, rate
  parsing heuristic removed (fail-closed, returns Decimal), and the
  Float → Decimal/mpmath migration for BondGuard, DerivativesGuard, and
  RiskGuard (#22, #23).
- 150 tests at release, including float-contamination and N-04 regression
  coverage.

[3.0.0]: https://github.com/QWED-AI/qwed-finance/compare/v2.1.0...v3.0.0
[2.1.0]: https://github.com/QWED-AI/qwed-finance/releases/tag/v2.1.0
