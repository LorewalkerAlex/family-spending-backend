"""Statement-evidence-based natural-month completeness."""

import re
from dataclasses import dataclass
from datetime import date

STATEMENT_DAY = 10
MONTH_PATTERN = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})$")


class MonthCoverageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MonthCoverage:
    month: str
    is_complete: bool
    show: bool


def _parse_month(value: str) -> tuple[int, int]:
    match = MONTH_PATTERN.fullmatch(value)
    if match is None:
        raise MonthCoverageError(f"Invalid projection month {value!r}; expected YYYY-MM")
    year, month = int(match.group("year")), int(match.group("month"))
    if month not in range(1, 13):
        raise MonthCoverageError(f"Invalid projection month {value!r}; expected YYYY-MM")
    return year, month


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def build_month_coverage(
    months: tuple[str, ...], statement_dates: frozenset[date]
) -> tuple[MonthCoverage, ...]:
    seen: set[str] = set()
    coverage: list[MonthCoverage] = []
    for month_name in months:
        if month_name in seen:
            raise MonthCoverageError(f"Duplicate projection month {month_name!r}")
        seen.add(month_name)
        year, month = _parse_month(month_name)
        next_year, next_month = _next_month(year, month)
        complete = all(
            item in statement_dates
            for item in (
                date(year, month, STATEMENT_DAY),
                date(next_year, next_month, STATEMENT_DAY),
            )
        )
        coverage.append(MonthCoverage(month_name, complete, complete))
    return tuple(coverage)
