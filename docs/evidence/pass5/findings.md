# Pass 5 findings and dispositions

## F5-01 — mobile finance acceptance can inspect stale portfolio content

- **Severity/classification:** P2, nonblocking acceptance-evidence defect; fixed. This weakens the earlier mobile-specific evidence; it does not demonstrate an authorization or financial-calculation failure.
- **Affected boundary:** browser navigation completion versus route-specific screenshots/accessibility assertions in `src/onboarding/console_demo.py`.
- **Reproduction:** install the pinned environment and run `python scripts/verify.py --workspace .local/repro --output .local/repro-evidence` at starting commit `7a65b7fe5cd3cf7841ceb8cb7ddb22b8d7cf9b36`. Inspect the financial-mobile capture. The preserved fresh baseline shows the portfolio heading/cards, despite metadata naming the finance route. The timing depends on navigation completion: the generic visible-heading/busy check and shared $5,000 text can pass before the new content renders.
- **Expected:** a finance-specific heading and invoice reconciliation region must render before calling the finance scan and capture. Screenshot metadata must describe the displayed view.
- **Observed:** 52 passing browser checks and a genuine image, but the capture still contains “Which acquisitions are ready to report?” and portfolio content. The claimed mobile finance scan therefore did not establish finance-view coverage in that execution.
- **Consequence:** passing counts and a genuine screenshot are insufficient to prove the named route was reviewed; mobile finance layout/a11y acceptance was temporarily unverified.
- **Evidence:** [initial capture](baseline/financial-mobile.png), [initial browser assertions/metadata](baseline/pass4.json), [initial source hashes](baseline/verification.json), and [corrected capture](run01/financial-mobile.png).
- **Correction:** wait for exact finance/history/company headings at transitions; require the existing labelled invoice reconciliation region on mobile; assert and record the observed route and heading on all seven captures. The offline evidence checker validates the new metadata when the new route check is present. Historical evidence is not rewritten.
- **Disposition/verification:** final corrected revision `dc17ad5f627a1c3d84db9e8032d7ac1a0ba1ac40` passes full acceptance, including the added finance-route assertion. A first correction used the wrong accessible role (`table` instead of the existing labelled `region`); that failed run is recorded and was corrected before acceptance. The correct view then exposed 46 contrast checks inconclusive because cells were horizontally clipped. All 46 explicitly pass after scrolling their exact nodes into view. The final driver preserves initial incomplete counts and each visibility follow-up, and the offline checker validates that every follow-up explicitly passed. No rule or node is waived. The application UI, policies and schemas were not redesigned.

## Other classifications

**Blocking findings:** none demonstrated. The added attacks did not establish a cross-company identity link, unauthorized database mutation, publication of invalid finances or new write based solely on historical authority.

**Documented limitations:** local session/HTTP trust model, no SSO/TLS/RLS certification, trusted setup, finite USD accounting policy, synthetic cutoffs, no native integration/CDC proof and finite bounded recovery. These were already acknowledged and are not newly invented vulnerabilities.

**Unverified:** production operation, independent human security certification, arbitrary scale/load, statutory/FX accounting and universal exactly-once execution. They are not acceptance claims of this local slice.

The $5,000 posting discrepancy and $8,000 unsupported elimination are intentionally retained source-accounting exceptions, not newly introduced defects and not asserted to be resolved by successful reconciliation.
