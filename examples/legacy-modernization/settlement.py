"""Legacy scheduled-batch CLI; intentionally retains its old parser component."""
import csv
import io
from optparse import OptionParser, make_option
from pathlib import Path
import sys

from ledger import LedgerError, parse_date, summarize, write_report


def parse_options(argv):
    # option_list is the deprecated construction API being retired in this task.
    parser = OptionParser(prog="settlement", usage="%prog [options]", version="settlement 1.2",
        option_list=[
            make_option("-i", "--input", dest="input", default="-", help="CSV input, or - for stdin"),
            make_option("-o", "--output", dest="output", default="-", help="report file, or - for stdout"),
            make_option("--since", dest="since", help="inclusive booking date YYYY-MM-DD"),
            make_option("--currency", dest="currency", help="USD or EUR"),
            make_option("--delimiter", dest="delimiter", default=",", help="input delimiter: , or ;"),
        ])
    options, positional = parser.parse_args(argv)
    if positional:
        parser.error("positional arguments are not supported")
    if options.delimiter not in (",", ";"):
        parser.error("delimiter must be , or ;")
    if options.currency is not None:
        options.currency = options.currency.strip().upper()
        if options.currency not in ("USD", "EUR"):
            parser.error("currency must be USD or EUR")
    if options.since is not None:
        try:
            options.since = parse_date(options.since)
        except LedgerError as error:
            parser.error(str(error))
    return options


def main(argv=None):
    options = parse_options(sys.argv[1:] if argv is None else argv)
    try:
        if options.input != "-" and options.output != "-" and Path(options.input).resolve() == Path(options.output).resolve():
            raise LedgerError("input and output must be different files")
        if options.input == "-":
            rows = summarize(sys.stdin, since=options.since, currency=options.currency, delimiter=options.delimiter)
        else:
            with open(options.input, encoding="utf-8-sig", newline="") as source:
                rows = summarize(source, since=options.since, currency=options.currency, delimiter=options.delimiter)
        # Complete validation before opening output; bad input preserves its file.
        buffer = io.StringIO(newline="")
        write_report(rows, buffer)
        if options.output == "-":
            sys.stdout.write(buffer.getvalue())
        else:
            with open(options.output, "w", encoding="utf-8", newline="") as target:
                target.write(buffer.getvalue())
        return 0
    except (LedgerError, csv.Error, OSError, UnicodeError) as error:
        sys.stderr.write("settlement: %s\n" % error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
