"""Small arithmetic helpers. The demo deliberately starts with boundary bugs."""


def clamp(value, lower, upper):
    """Clamp value to inclusive lower/upper bounds; reject reversed bounds."""
    if lower > upper:
        raise ValueError("lower bound must not exceed upper bound")
    return min(max(value, lower), upper)


def safe_divide(numerator, denominator):
    """Divide two numbers; raise ValueError for a zero denominator."""
    if denominator == 0:
        raise ValueError("denominator must not be zero")
    return numerator / denominator
