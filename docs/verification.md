# Verification

Publication preparation completed on 2026-11-06.

- 81 backend tests passed with Chromium rendering/security tests enabled.
- 18 browser workflow scenarios passed against the patched backend, including exact CSV/XLSX comparisons, pagination, preview, JavaScript rendering, cancellation, partial failure, and restricted destinations.
- 12 responsive viewport/field-count combinations passed wheel, keyboard, boundary, focus and overflow checks.
- Production build, strict TypeScript checking, frontend formatting and Python lint/format checks passed.
- Updated vulnerable dependencies in an isolated environment and recorded verified versions in requirements-lock.txt. Python 3.11+ is now required. Python and npm advisory scans reported no known vulnerabilities in the verified dependencies. The local project itself is not a published package and is reviewed as source, rather than looked up on a package registry.
- Preserved connection-time DNS validation, private-address blocking, same-origin redirect/pagination restrictions, robots enforcement, pacing, browser restrictions, site CSP, and export sanitization.
- Publication file scan found no personal identifiers, private filesystem paths, assistant references, private keys, or credential patterns. Bundled workbook author/timestamp metadata was removed without changing worksheet contents.
- No previous Git repository or commit history existed. Initial publication uses a generic maintainer identity with a reserved example-domain email; personal author metadata is not included.

Local environments, generated builds, extraction/review output, screenshots and logs are excluded from publication. Automated checks do not establish that every possible vulnerability is absent. Follow SECURITY.md and reassess advisories when dependencies change.
