# Changelog

All notable changes to qwed-finance are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
versions follow [Semantic Versioning](https://semver.org/). Releases before
v2.1.0 are documented as [GitHub Releases](https://github.com/QWED-AI/qwed-finance/releases).

## [Unreleased]

### Security

- **A computed value of zero no longer verifies any claim (#98).**
  `RiskGuard.verify_var`, `RiskGuard.verify_expected_shortfall`,
  `BondGuard.verify_convexity` and `BondGuard.verify_ytm` compared a claim
  as a percentage of the computed value and skipped the comparison when
  that value was zero or negative, so any claim verified — a zero-volatility
  VaR verified `$5,000,000`, a zero-maturity convexity verified `9999`. A
  computed value of zero is now compared absolutely: the claim verifies
  only if it rounds to zero at the precision the result is reported in.
  A non-zero value is compared relative to its absolute value.
- The same four methods refuse inputs their formula cannot evaluate, as
  `verified=False` with an `UNVERIFIABLE (reason)` computed value, instead
  of verifying or raising: NaN, Infinity, `bool` and non-numeric inputs; a
  negative portfolio value, volatility, VaR amount or tail loss; a tail
  loss average below the VaR amount, which no distribution has; a holding
  period at or below zero; a confidence level outside (0, 1); a face value
  or price at or below zero, a negative coupon rate, a maturity at or
  below zero, shorter than one coupon period or longer than 1,200 coupon
  periods (100 years of monthly coupons); a `frequency` that is not a
  positive integer (`2.0` is refused); and a yield at which the discount
  factor `1 + y/frequency` is at or below zero. A maturity shorter than
  one coupon period is refused rather than priced; pricing the stub is
  #119. The coupon-period count is taken in Decimal, and a count from a
  float maturity within `1e-9` coupon periods of a whole number is that
  number (float representation error stays below `1e-12`), so `0.57 * 100`
  years is no longer truncated to 56 periods and `2/12` years is two
  monthly periods. For a lower-precision NumPy float the tolerance grows
  with its machine epsilon (four epsilons of the count), so
  `np.float32(5/6)` years at six coupons a year is five periods, where
  main truncated it to four; a maturity in a float too imprecise to tell
  neighbouring counts apart (float16 beyond about 127 periods) is refused.
  A Decimal or int maturity is never rounded this way.
  NumPy integer and float scalars are accepted as before; NumPy's `bool_`
  is refused like `bool`.
- `verify_ytm` refuses a claim when its yield solver runs out of
  iterations without pricing the bond, instead of comparing against
  wherever the solver stopped — typically its lower bound of 0.01 %,
  which verified a claim of `0.0100%` for a bond yielding 0.0099 %. The
  solver counts as converged when the price residual is within `1e-13`
  of the price, relative to it, rather than within an absolute `1e-10`,
  which let a bond with a tiny face value converge at any yield; the
  candidate from its last allowed step is checked too. A percentage
  claim is converted exactly, so it gets the same verdict as the same
  value written as a decimal fraction.
- Claims those methods cannot read — not a string, unparseable, NaN or
  Infinity, or too large to compare — are refused the same way instead of
  raising `InvalidOperation`. A claim refused as `UNVERIFIABLE` is echoed
  in `llm_value` as one escaped line of at most 80 characters (a
  non-string claim as `<non-string claim>`), never as raw text, so it
  cannot write a workflow command into the GitHub Action's log. Every
  `UNVERIFIABLE` refusal in `verify_sortino_ratio` echoes the same way.

### Added

- **Receipts are signed when they enter the audit trail, and exports
  carry the signatures (#90, follow-up to #44).** `AuditLog` now holds a
  `ReceiptSigner`, resolved from `QWED_RECEIPT_SIGNING_KEY` (hex, at
  least 32 bytes decoded) by default: `AuditLog.log` signs every receipt
  with the #44 HMAC primitive as it is retained, and the guard and
  integration flows (`CrossGuard`, `UCPIntegration`,
  `OpenResponsesIntegration`) pick this up with no code change. A signer
  is fail-closed about its configuration: a malformed, empty or
  too-short key raises at construction — never silently signs nothing.
- `QWED_RECEIPT_VERIFICATION_KEYS` names retired keys still accepted for
  verification, the rotation window: evidence signed under an old key
  keeps verifying until the key is removed, and refuses afterwards.
  Key ids are derived from the key material, so a key id cannot lie about
  which key signed. Empty list entries raise rather than being skipped.
- `AuditLog.verify_export_json` verifies an exported envelope and fails
  closed on every deviation: unsigned export, unknown key id, tampered
  receipt or envelope, injected or missing fields, truncated or reordered
  receipts, a signature replayed across artifacts.

### Changed

- **`AuditLog.export_json` returns a signed envelope object, not a bare
  array (breaking).** The export is now
  `{"schema": "qwed-finance/audit-log/v1", "alg": "HMAC-SHA256",
  "signature_key_id": "<key id>", "signature": "<hmac hex>",
  "receipts": [...]}`; each receipt carries its own `signature` and
  `signature_key_id`, and the envelope signature covers everything else
  in the document, so truncation and reordering of an export are
  detectable, which per-receipt signatures alone cannot do. Without a
  signer the envelope is explicitly unsigned: `alg`, `signature` and
  every receipt's signature fields are null — a receipt signed elsewhere
  does not carry its signature into an unsigned export. With one
  configured, the export verifies every receipt first and refuses to
  ship evidence it cannot vouch for. The envelope stays HMAC — tamper
  evidence for key holders, not third-party attestation; that envelope
  is #37.
- `AuditLog.log` retains an independent snapshot of each signed receipt,
  so mutating the caller's object — or re-signing the same receipt into
  another log under another key — never changes the evidence a log
  already holds. Re-signing verifies the existing signature first and
  refuses on a mismatch (the tamper-then-relog path) or a key outside
  the rotation window; a half-signed receipt (signature without key id,
  or the reverse) is refused too.
- `AuditLog.verify_export_json` parses with duplicate member names
  refused at every level (`json.loads` keeps only the last value of a
  repeated name, so a document that could verify here might read
  differently in a first-wins consumer) and reports invalid JSON as
  `ReceiptSignatureError`, not `JSONDecodeError`. Non-string key ids and
  content that cannot be canonically re-encoded also refuse as
  `ReceiptSignatureError` instead of raising `TypeError`.
- Receipt content is bounded: `metadata`, `proof_steps` and `violations`
  may nest at most 32 containers deep (`MAX_NESTING_DEPTH`), and deeper
  content is refused when it is logged (`ValueError`). The bound is fixed
  rather than taken from Python's recursion limit, which depends on how
  deep the stack already is, so signing, verification and export cannot
  overflow on content that was accepted.
- `AuditLog.log` refuses, with or without a signer, content that cannot be
  canonically JSON-encoded. Unsupported values, colliding keys and an
  `engine_used` or `status` that is not an enum member raise `TypeError`;
  before, such a receipt was accepted and `export_json()` failed later.
  NaN and Infinity raise `ValueError`: this is a behaviour change, since
  `export_json()` used to emit them as `NaN`/`Infinity` tokens, which are
  not JSON (RFC 8259); strict parsers reject them, though Python's `json`
  module accepts them by default. With a signer configured, a receipt that
  already carries a signature or a key id raises `ReceiptSignatureError`
  for the same content instead; an intact signed receipt is verified and
  re-signed as before.
- `AuditLog.verify_export_json` refuses nesting past the parser's
  recursion limit as `ReceiptSignatureError`, not `RecursionError`. On
  Python with the integer-digit limit (3.10.7 and later), an integer
  literal past the limit is refused as `ReceiptSignatureError`, not
  `ValueError`, and such an integer cannot be logged in the first place
  (`log()` raises `ValueError`, or `ReceiptSignatureError` for a receipt
  carrying signature state when a signer is configured, as above). On
  3.10.0–3.10.6 there is no limit: a long literal in a tampered export is
  refused by the schema and signature checks, and a genuinely signed
  export containing one verifies.

### Fixed

- `price_option` rejects anything other than exactly `call` or `put`,
  rejects missing numeric inputs instead of filling defaults, and records
  the put formula on put receipts (#73).
- `calculate_npv` and `calculate_loan_payment` enforce their declared
  parameter schemas (types with bools excluded from numbers, bounds,
  required fields, integer months) and reject out-of-contract arguments
  instead of silently computing (#73).
- `QueryGuard.verify_readonly_safety` reports a top-level `DELETE`,
  `INSERT` or `UPDATE` once instead of twice: the keyword scan and the AST
  wrote the same violation. Separate AST findings, such as two mutating
  subqueries, are all kept; verdicts and risk levels are unchanged.

## [3.0.1] - 2026-10-09

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
- **Sanctions screening resists in-word perturbations**
  (GHSA-mv2c-jwm9-pfrq): `normalize_for_screening` now folds diacritics
  and stray combining marks (NFKD + mark removal) and maps Latin
  look-alike letters (small capitals, dotless i, Cyrillic/Greek
  homoglyphs) to a Latin skeleton. `sanctions_match` additionally
  compares separator-free forms in the forward direction, so names such
  as `EV-IL CORP`, `E.V.I.L. CORP`, `ÉVIL CORP` or `ᴇᴠɪʟ ᴄᴏʀᴘ` no longer
  clear a `EVIL CORP` entry. Address fragments remain forward-only.
- **QueryGuard rejects MySQL executable comments** (GHSA-q8r4-6gpp-5fx2):
  queries containing `/*! ... */` or MariaDB `/*M! ... */` comments are
  now unsafe in `verify_readonly_safety`, and therefore in
  `verify_table_access`, `verify_column_access`, `sanitize_query` and
  `CrossGuard.verify_query_with_pii_protection`. MySQL executes these
  comments while the parser drops them, so tables and columns inside them
  previously bypassed the allow-list and PII checks. `sanitize_query` no
  longer rewrites such queries. Ordinary comments and optimizer hints
  (`/*+ ... */`) are unaffected.
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

[Unreleased]: https://github.com/QWED-AI/qwed-finance/compare/v3.0.1...HEAD
[3.0.1]: https://github.com/QWED-AI/qwed-finance/compare/v3.0.0...v3.0.1
[3.0.0]: https://github.com/QWED-AI/qwed-finance/compare/v2.1.0...v3.0.0
[2.1.0]: https://github.com/QWED-AI/qwed-finance/releases/tag/v2.1.0
