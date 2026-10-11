# Settlement CLI compatibility contract, version 1.0

This synthetic legacy batch job models an integration used by scheduled scripts and CSV consumers. The task replaces its parser component, preserving business rules and supported invocation behavior. It is a fixture, not a production customer system.

Only `settlement.py` may change. Preserve `ledger.py`, the fixed input/output, tests, acceptance runner and this manifest/contract. Do not install packages or introduce network access, new services or a different report format.

| Boundary | Required behavior |
| --- | --- |
| CLI | `-i/--input`, `-o/--output`, `--since`, `--currency`, `--delimiter`, help and version remain available. Input/output default to `-` for standard streams. Keep supported attached/equal-value forms, unique long-option abbreviations and last repeated value winning. |
| Legacy path values | An input/output value can start with a hyphen or look like another option: `-i -input.csv`, `--input --version`. Consuming that token as a filename is intentional legacy behavior. A plain argparse port changes it. |
| Date/currency filters | `--since` is inclusive and requires a real `YYYY-MM-DD` calendar date. Currency is normalized to USD/EUR. Every input row is validated and duplicate IDs rejected **before** filtering; bad excluded rows still reject the batch. |
| CSV input | Required columns: transaction_id, customer, date, kind, amount, currency. Reordered/whitespace-padded headers and extra named columns are allowed. Duplicate headers, missing required columns, short/extra fields and malformed quoting fail. File input accepts UTF-8 BOM and CRLF; quoted commas/newlines and Unicode are preserved. |
| Values | Strip surrounding whitespace. IDs/customer must be nonempty; IDs are unique across the entire batch. Kind is charge/refund with case normalized; customer spelling/case are preserved. Currency must be USD/EUR. |
| Amounts | Unsigned decimal with a leading digit; no signs, exponents, NaN or Infinity. Round **each transaction** to cents using half-up before summing. Rounded per-transaction maximum is 99999999.99. Zero is a counted transaction; refunds can produce a negative group net. |
| Output | Exactly customer,currency,charges,refunds,net,transactions, in that order. Group by customer/currency and sort those keys. Decimal fields have two places; transactions is an integer. CSV quoting and LF output are preserved. Header-only or fully filtered valid input yields only the report header. |
| Failure/effects | Success exit 0; CLI/input failures exit 2, no report on stdout, an error on stderr. Existing output is unchanged and absent output is not created when input validation fails. The same resolved input/output file is refused. Successful file output emits no stdout. |
| Help/version | Help exits 0 and lists all supported options; version output is exactly `settlement 1.2` followed by LF. These paths do not read input. Full help/usage wrapping and parser-specific error wording are outside the contract; semantic error, stderr destination and exit code remain required. |

Run `python3 acceptance/verify_candidate.py` before modernization. It should pass. Run `python3 acceptance/verify_candidate.py --require-modernized` for target acceptance: the unchanged baseline should pass characterization and then fail the retirement guard. After migration both must pass on the installed Python 3.10 and 3.13 interpreters.

The public suite is characterization evidence, not hidden proof of equivalence for every possible input. A real maintainer must approve the contract, retain independent holdout cases outside the agent-readable project, and review unexpected behavior rather than “fixing” tests to make a migration green. The AST guard checks imports; human review must also confirm argparse handles the actual CLI, not an unused import or a dynamic bypass.

No rollback of already generated downstream reports, schema/data migration, automatic rebase, whole-app rewrite, throughput guarantee or production deployment is included. Before local application, keep the captured baseline and inspect the exact candidate. If an applied change must be reverted, the developer uses their normal reviewed Git revert/restore process in the disposable project; Parallax does not automatically roll back consumers or deployments.
