"""Iterable statistics. The demo deliberately starts with boundary bugs."""


def mean(values):
    """Return arithmetic mean of a finite iterable; reject empty input."""
    items = list(values)
    if not items:
        raise ValueError("Cannot compute mean of empty iterable")
    return sum(items) / len(items)


def median(values):
    """Return median of a finite iterable; reject empty input."""
    items = list(values)
    if not items:
        raise ValueError("Cannot compute median of empty iterable")
    ordered = sorted(items)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
