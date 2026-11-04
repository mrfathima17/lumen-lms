def safe_cell(value):
    """Stop spreadsheet formula injection: a cell starting with = + - @ would run as a formula in Excel."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s
