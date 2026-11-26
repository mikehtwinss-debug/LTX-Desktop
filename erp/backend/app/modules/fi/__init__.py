"""Financial accounting."""

from app.core.numbering import register_number_range

# Journal entries are numbered per fiscal year: two-digit year + 8 digits, no prefix.
JOURNAL_NUMBER_RANGE = "JE"
register_number_range(JOURNAL_NUMBER_RANGE, "", 8, True)
