"""Parse exactly the number OCR observed; never guess missing decimal places."""

from decimal import Decimal, InvalidOperation
import re


def parse_weight(text: str, *, decimal_places: int = 2, fixed_digits: bool = False) -> Decimal | None:
    """Accept a complete signed reading with the configured decimal count.

    Commas are equivalent decimal separators. A missing separator, extra
    digits, partial text or an O/I substitution is never silently repaired.
    """
    if not 0 <= decimal_places <= 6:
        raise ValueError("decimal_places must be between 0 and 6")
    number = rf"-?[0-9]+[.,][0-9]{{{decimal_places}}}" if decimal_places else r"-?[0-9]+"
    match = re.fullmatch(rf"\s*({number})\s*(?:kg)?\s*", text, re.IGNORECASE)
    if match is None:
        if fixed_digits:
            raw = re.fullmatch(r'\s*(-?[0-9]{3,6})\s*(?:kg)?\s*',text,re.IGNORECASE)
            if raw:
                return Decimal(raw.group(1)).scaleb(-decimal_places)
        return None
    try:
        return Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None
