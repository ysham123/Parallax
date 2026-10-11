"""Existing settlement rules. The parser modernization must not change these."""
import csv
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re


REQUIRED = ("transaction_id", "customer", "date", "kind", "amount", "currency")
REPORT_HEADER = ("customer", "currency", "charges", "refunds", "net", "transactions")
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("99999999.99")


class LedgerError(ValueError):
    pass


def parse_date(value):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise LedgerError("date must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise LedgerError("date must be a valid calendar date") from None


def parse_amount(value):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
        raise LedgerError("amount must be an unsigned decimal")
    try:
        amount = Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise LedgerError("amount is outside the supported range") from None
    if amount > MAX_AMOUNT:
        raise LedgerError("amount is outside the supported range")
    return amount


def summarize(stream, *, since=None, currency=None, delimiter=","):
    """Validate every row before filtering; round each row before summing."""
    reader = csv.DictReader(stream, delimiter=delimiter, strict=True)
    if reader.fieldnames is None:
        raise LedgerError("input must contain a header")
    headers = [name.strip() for name in reader.fieldnames]
    if len(set(headers)) != len(headers):
        raise LedgerError("duplicate column name")
    if any(name not in headers for name in REQUIRED):
        raise LedgerError("missing required column")
    reader.fieldnames = headers
    seen = set()
    groups = {}
    for line, raw in enumerate(reader, start=2):
        if None in raw or any(raw[name] is None for name in REQUIRED):
            raise LedgerError("row %d: wrong number of columns" % line)
        row = {name: raw[name].strip() for name in REQUIRED}
        try:
            if not row["transaction_id"] or not row["customer"]:
                raise LedgerError("transaction_id and customer are required")
            if row["transaction_id"] in seen:
                raise LedgerError("duplicate transaction_id")
            seen.add(row["transaction_id"])
            booked = parse_date(row["date"])
            kind = row["kind"].lower()
            if kind not in ("charge", "refund"):
                raise LedgerError("kind must be charge or refund")
            code = row["currency"].upper()
            if code not in ("USD", "EUR"):
                raise LedgerError("currency must be USD or EUR")
            amount = parse_amount(row["amount"])
        except LedgerError as error:
            raise LedgerError("row %d: %s" % (line, error)) from None
        # Historical contract: bad excluded rows still fail the entire batch.
        if since is not None and booked < since:
            continue
        if currency is not None and code != currency:
            continue
        key = (row["customer"], code)
        if key not in groups:
            groups[key] = {"charge": Decimal("0.00"), "refund": Decimal("0.00"), "count": 0}
        groups[key][kind] += amount
        groups[key]["count"] += 1
    result = []
    for (customer, code), totals in sorted(groups.items()):
        charge, refund = totals["charge"], totals["refund"]
        result.append((customer, code, format(charge, ".2f"), format(refund, ".2f"),
                       format(charge - refund, ".2f"), totals["count"]))
    return result


def write_report(rows, stream):
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(REPORT_HEADER)
    writer.writerows(rows)
