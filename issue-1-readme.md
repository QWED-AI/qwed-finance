## README: Branding, badges, and content fixes

### The problem

The README is the first thing people see and it's missing a few things that make other QWED repos feel cohesive. No QWED logo at the top, no QWED Security badge, and a couple of inconsistencies that make it look like it hasn't been touched since v1.0.

Specific things:

**Logo**
Right now the README jumps straight into the title without any brand imagery. Other QWED repos have a logo at the top before the title. We should add one here too — makes the repo feel part of the same family.

**Badges**
There are already badges for Snyk, Mintlify, GitHub Developer Program, PyPI, npm, and License. Keep all of them. Just add a QWED Security badge right after the existing badges block, maybe before the GitHub Developer Program badge. The badge format from qwed-verification is:
```
[![QWED Security Verified](https://img.shields.io/badge/QWED_Security-Verified-00C853?style=flat&logo=checkmarx)](https://github.com/marketplace/qwed-security)
```

Also the Mintlify badge links to `docs.qwedai.com` which is a Mintlify page. If the docs moved to a different platform, update the link. If not, keep it.

**"Ten Guards" vs "Eleven Guards"**
The README heading says "The Ten Guards" but `__init__.py` lists 11 guards including TradingGuard. Counting the sections in README confirms only 10 are documented. We're either missing a section for TradingGuard or the heading needs to change. The README shows sections 1-9 and then 10 (ISO Guard), but TradingGuard exists in code and is exported from `__init__.py`. Need to either add TradingGuard documentation or rename to "Eleven Guards" and add the missing section.

**Missing fail-closed philosophy section**
Other QWED repos have a section explaining fail-closed philosophy — something like "fail-closed by default, verified=False until proven otherwise". The finance context makes this especially relevant since a hallucinated calculation that passes silently could cause real financial loss. A short 3-4 line section would help.

**QWED Ecosystem link**
The "Part of the QWED Ecosystem" section exists but there's no direct link to the QWED Security GitHub App marketplace page. Add it somewhere prominent, maybe under the badges or in the security section.

### What to do

1. Add QWED logo SVG/PNG at the top before the title
2. Add QWED Security badge to the badges row (keep existing badges)
3. Either add TradingGuard docs section or change "The Ten Guards" to "The Eleven Guards" — whichever matches reality
4. Add a short fail-closed philosophy section (~3 lines)
5. Add QWED Security marketplace link

### Files to touch

- `README.md`

### Acceptance criteria

- Logo visible at top of README
- QWED Security badge in badges row, existing badges untouched
- "Ten Guards" heading matches actual guard count in the file (10 or 11)
- Fail-closed philosophy explained briefly
- QWED Security marketplace link present
