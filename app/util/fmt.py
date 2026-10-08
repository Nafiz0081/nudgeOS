from datetime import datetime


def dtfmt(dt: datetime, pattern: str) -> str:
    """strftime that also understands %-d and %-I on Windows.

    The guide uses the glibc-only "no leading zero" flags, which raise
    ValueError on Windows. We substitute them before calling strftime.
    """
    pattern = (
        pattern.replace("%-d", str(dt.day))
               .replace("%-I", str(int(dt.strftime("%I"))))
               .replace("%-H", str(dt.hour))
               .replace("%-m", str(dt.month))
    )
    return dt.strftime(pattern)
