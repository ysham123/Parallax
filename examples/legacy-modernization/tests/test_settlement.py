"""Black-box characterization of the legacy CLI, not parser internals."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


FIXTURE = Path(__file__).resolve().parents[1]
CANDIDATE = Path(os.environ.get("SETTLEMENT_CANDIDATE", str(FIXTURE))).resolve()
HEADER = "transaction_id,customer,date,kind,amount,currency\n"
REPORT = "customer,currency,charges,refunds,net,transactions\n"


def run(*args, text=HEADER, cwd=None):
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, str(CANDIDATE / "settlement.py"), *args], input=text.encode("utf-8"),
                            capture_output=True, cwd=cwd, env=environment, timeout=10)
    # Decode without universal-newline rewriting: LF is part of the CSV contract.
    result.stdout = result.stdout.decode("utf-8")
    result.stderr = result.stderr.decode("utf-8")
    return result


class SettlementContractTests(unittest.TestCase):
    def success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, expected)

    def failure(self, result, message):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn(message, result.stderr)

    def test_fixed_batch_matches_golden_report(self):
        result = run("-i", str(FIXTURE / "sample-input" / "transactions.csv"))
        self.success(result, (FIXTURE / "tests" / "data" / "report.csv").read_text(encoding="utf-8"))

    def test_header_only_batch_emits_header(self):
        self.success(run(), REPORT)

    def test_default_input_and_output_are_standard_streams(self):
        self.success(run(text=HEADER + "x,A,2024-01-01,charge,12.3,USD\n"),
                     REPORT + "A,USD,12.30,0.00,12.30,1\n")

    def test_explicit_standard_stream_sentinels(self):
        self.success(run("--input=-", "--output=-"), REPORT)

    def test_rounds_each_transaction_half_up_before_total(self):
        self.success(run(text=HEADER + "a,A,2024-01-01,charge,0.005,USD\n"
                         "b,A,2024-01-01,charge,0.005,USD\n"), REPORT + "A,USD,0.02,0.00,0.02,2\n")

    def test_refund_only_group_keeps_negative_net(self):
        self.success(run(text=HEADER + "a,A,2024-01-01,refund,1.235,USD\n"),
                     REPORT + "A,USD,0.00,1.24,-1.24,1\n")

    def test_groups_currencies_separately_and_sorts_keys(self):
        text = HEADER + "a,Z,2024-01-01,charge,2,USD\nb,A,2024-01-01,charge,3,USD\nc,A,2024-01-01,charge,4,EUR\n"
        self.success(run(text=text), REPORT + "A,EUR,4.00,0.00,4.00,1\nA,USD,3.00,0.00,3.00,1\nZ,USD,2.00,0.00,2.00,1\n")

    def test_strips_values_and_normalizes_kind_and_currency(self):
        self.success(run(text=HEADER + " a , Alice ,2024-01-01, CHARGE , 2.5 , usd \n"),
                     REPORT + "Alice,USD,2.50,0.00,2.50,1\n")

    def test_customer_spelling_and_case_are_preserved(self):
        self.success(run(text=HEADER + "a,alice,2024-01-01,charge,1,USD\nb,Alice,2024-01-01,charge,2,USD\n"),
                     REPORT + "Alice,USD,2.00,0.00,2.00,1\nalice,USD,1.00,0.00,1.00,1\n")

    def test_since_is_inclusive_and_accepts_leap_day(self):
        self.success(run("--since", "2024-02-29", text=HEADER + "a,A,2024-02-28,charge,1,USD\nb,A,2024-02-29,charge,2,USD\n"),
                     REPORT + "A,USD,2.00,0.00,2.00,1\n")

    def test_currency_filter_normalizes_option(self):
        self.success(run("--currency", " eur ", text=HEADER + "a,A,2024-01-01,charge,1,USD\nb,A,2024-01-01,charge,2,EUR\n"),
                     REPORT + "A,EUR,2.00,0.00,2.00,1\n")

    def test_valid_rows_all_filtered_emit_header(self):
        self.success(run("--since", "2025-01-01", text=HEADER + "a,A,2024-01-01,charge,1,USD\n"), REPORT)

    def test_invalid_excluded_row_still_rejects_batch(self):
        self.failure(run("--currency", "EUR", text=HEADER + "a,A,2024-01-01,charge,NaN,USD\n"), "unsigned decimal")

    def test_duplicate_excluded_id_still_rejects_batch(self):
        self.failure(run("--since", "2025-01-01", text=HEADER + "a,A,2024-01-01,charge,1,USD\na,A,2024-01-02,charge,2,USD\n"), "duplicate transaction_id")

    def test_semicolon_input_and_comma_report(self):
        self.success(run("--delimiter", ";", text=HEADER.replace(",", ";") + "a;A;2024-01-01;charge;1.2;USD\n"),
                     REPORT + "A,USD,1.20,0.00,1.20,1\n")

    def test_reordered_extra_columns_and_header_whitespace(self):
        self.success(run(text="note, currency ,amount,kind,date,customer,transaction_id\nignored,usd,1,charge,2024-01-01,A,a\n"),
                     REPORT + "A,USD,1.00,0.00,1.00,1\n")

    def test_quoted_multiline_unicode_customer(self):
        result = run(text=HEADER + 'a,"Zoë\nWest",2024-01-01,charge,1,EUR\n')
        self.success(result, REPORT + '"Zoë\nWest",EUR,1.00,0.00,1.00,1\n')

    def test_utf8_bom_and_crlf_file(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "input.csv"
            path.write_bytes((HEADER + "a,A,2024-01-01,charge,1,USD\n").replace("\n", "\r\n").encode("utf-8-sig"))
            self.success(run("--input", str(path)), REPORT + "A,USD,1.00,0.00,1.00,1\n")

    def test_output_file_success_does_not_emit_stdout(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "report with spaces.csv"
            self.success(run("-o", str(path)), "")
            self.assertEqual(path.read_bytes(), REPORT.encode("utf-8"))

    def test_invalid_batch_preserves_existing_output(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "report.csv"
            path.write_bytes(b"previous successful batch\n")
            self.failure(run("--output", str(path), text=HEADER + "a,A,not-a-date,charge,1,USD\n"), "YYYY-MM-DD")
            self.assertEqual(path.read_bytes(), b"previous successful batch\n")

    def test_invalid_batch_does_not_create_output(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "new.csv"
            self.failure(run("-o", str(path), text=""), "header")
            self.assertFalse(path.exists())

    def test_same_input_and_output_are_refused(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "input.csv"
            path.write_text(HEADER, encoding="utf-8")
            self.failure(run("-i", str(path), "-o", str(path)), "different files")
            self.assertEqual(path.read_text(encoding="utf-8"), HEADER)

    def test_missing_input_is_error_without_output(self):
        with TemporaryDirectory() as folder:
            self.failure(run("-i", str(Path(folder) / "missing.csv")), "settlement:")

    def test_hyphen_prefixed_paths_are_option_values(self):
        with TemporaryDirectory() as folder:
            source, target = Path(folder) / "-input.csv", Path(folder) / "-output.csv"
            source.write_text(HEADER, encoding="utf-8")
            self.success(run("-i", source.name, "--output", target.name, cwd=folder), "")
            self.assertEqual(target.read_bytes(), REPORT.encode("utf-8"))

    def test_option_looking_filename_does_not_trigger_version(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "--version"
            source.write_text(HEADER, encoding="utf-8")
            self.success(run("--input", source.name, cwd=folder), REPORT)

    def test_malformed_headers(self):
        for text, message in [("", "header"), ("customer,currency\n", "missing required"),
                              (HEADER.rstrip("\n") + ",customer\n", "duplicate column")]:
            with self.subTest(text=text):
                self.failure(run(text=text), message)

    def test_short_extra_and_unterminated_rows(self):
        for text in [HEADER + "a,A,2024-01-01,charge,1\n", HEADER + "a,A,2024-01-01,charge,1,USD,extra\n",
                     HEADER + 'a,"unterminated,2024-01-01,charge,1,USD\n']:
            with self.subTest(text=text):
                self.failure(run(text=text), "settlement:")

    def test_bad_amounts(self):
        for amount in ("-1", "+1", "NaN", "Infinity", "1e2", ".50", "", "99999999.995", "1" * 40):
            with self.subTest(amount=amount):
                self.failure(run(text=HEADER + "a,A,2024-01-01,charge,%s,USD\n" % amount), "amount")

    def test_zero_and_max_amount(self):
        self.success(run(text=HEADER + "a,A,2024-01-01,charge,0,USD\nb,A,2024-01-01,charge,99999999.99,USD\n"),
                     REPORT + "A,USD,99999999.99,0.00,99999999.99,2\n")

    def test_bad_calendar_and_non_iso_dates(self):
        for value in ("2023-02-29", "2024-13-01", "20240101", "2024-1-01", ""):
            with self.subTest(value=value):
                self.failure(run(text=HEADER + "a,A,%s,charge,1,USD\n" % value), "date")

    def test_invalid_identifiers_kind_and_currency(self):
        for row, message in [(",A,2024-01-01,charge,1,USD\n", "required"),
                             ("a, ,2024-01-01,charge,1,USD\n", "required"),
                             ("a,A,2024-01-01,void,1,USD\n", "kind"),
                             ("a,A,2024-01-01,charge,1,GBP\n", "currency")]:
            with self.subTest(row=row):
                self.failure(run(text=HEADER + row), message)

    def test_cli_errors_remain_exit_two(self):
        for args in [("unexpected.csv",), ("--unknown",), ("--input",), ("--since", "2023-02-29"),
                     ("--currency", "GBP"), ("--delimiter", "|"), ("--since", "20240101")]:
            with self.subTest(args=args):
                self.failure(run(*args), "settlement:")

    def test_help_and_version_do_not_read_input(self):
        for args in [("-h",), ("--help",)]:
            result = run(*args, text="invalid")
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")
            for option in ("--input", "--output", "--since", "--currency", "--delimiter"):
                self.assertIn(option, result.stdout)
        self.success(run("--version", text="invalid"), "settlement 1.2\n")

    def test_legacy_attached_values_abbreviation_and_last_option_win(self):
        self.success(run("--currency=EUR", "--cur", "USD", "-i-", "-o-"), REPORT)


if __name__ == "__main__":
    unittest.main()
