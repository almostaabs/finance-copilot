# Real annual reports

Published annual reports and 10-K filings, used for Phase 12 validation. The PDFs
themselves are the publishers' documents and are **not** committed — `.gitignore`
excludes `tests/fixtures/real/*.pdf`. Download them from the sources below and drop
them in this folder; this README and `run_all.py` are tracked, so the validation can
be reproduced by anyone who fetches the same documents.

They sit in their own folder rather than alongside the synthetic fixtures because
`tests/test_fixture_integrity.py` pins the exact set of PDFs directly in
`tests/fixtures/`, and because these are the only fixtures nobody here computed the
answers for.

| File | Source |
|---|---|
| `apple_10k_2023.pdf` | Apple 10-K FY2023, investor site |
| `berkshire_2023.pdf` | Berkshire Hathaway 10-K 2023, berkshirehathaway.com |
| `microsoft_fy24.pdf` | Microsoft 10-K FY2024 |
| `merchants_bank_2024.pdf` | Merchants Bancorp 10-K 2024, company CDN |
| `wipro_fy24.pdf` | Wipro Integrated Annual Report FY24, wipro.com |

Run one:

```bash
uv run python demo.py tests/fixtures/real/apple_10k_2023.pdf
```

Run all of them and print a summary table:

```bash
uv run python tests/fixtures/real/run_all.py
```

Results and the findings they produced are recorded in `docs/PHASE12_VALIDATION.md`.
These files are deliberately NOT part of the test suite: they change when a company
republishes, and a test that depends on a moving external document is not a test.
