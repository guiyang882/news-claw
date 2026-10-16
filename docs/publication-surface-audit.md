# Publication surface audit and issuer scope (2026-10-16)

`daily-blog-delivery-audit` now checks the rendered local frontend after validated bilingual content is found. It compares the public article catalogue to home/library cards in both languages and checks the published article plus home/library/about/editorial navigation. Missing cards, outdated navigation, failed HTTP responses and wrong-language article pages report `publication_surface_mismatch` with `needs_attention: true`; they do not trigger another writing/model attempt.

Checks use only `http://127.0.0.1:3000`, an audit user agent, bounded response reads, eight-second timeouts and no redirects. External crawling remains zero. The existing 10:55 Asia/Shanghai schedule is unchanged. Local HTTP requests are separately reported. This is an origin/deployment check, not a claim that an external CDN was checked.

The company-pulses review remains Monday/Thursday 10:10 with its existing six-page shared budget and ten-second spacing. Its actual website prompt now covers SpaceX's listed issuer scope, Space / Connectivity / AI revenue, operating income and capex, and consolidated cash flow. Start with the verified issuer IR source in the operating snapshot. Preserve units, reporting periods and non-GAAP definitions. Missing inputs must not become an assertion that the issuer has no public filings. SEC access stays paused on ECS.

No paused strategy, stock-download or retired history task was re-enabled.
