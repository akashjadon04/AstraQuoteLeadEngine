# ============================================================
# phone.py — Single source of truth for Swiss phone normalization
#
# THE BUG THIS FIXES: the blacklist always stores phone numbers in E.164
# format ("+41228860226") because that's what lead["phone"] holds by the
# time Layer 6 finishes and calls add_to_blacklist(). But Layer 1's
# discovery-time dedup and Layer 4's re-crawl dedup were comparing against
# the RAW phone text scraped straight from a search snippet — Swiss local
# format ("022 886 02 26" -> whitespace-stripped "0228860226"). Those two
# strings never match, even for the exact same real phone number, so a
# company already fully assessed (and blacklisted) in a past run could be
# rediscovered and re-delivered as if it were new — confirmed live: the same
# company reached the DELIVERED list in two separate runs under this bug.
#
# Fix: normalize to E.164 for every dedup/blacklist comparison, from the
# very first time a phone number is seen — not just once Layer 2 gets to it.
# ============================================================

from typing import Optional

import phonenumbers


def normalize_swiss_phone(raw: str) -> Optional[str]:
    """Parse and format a Swiss phone number to E.164 ('+41...'). Returns None
    for anything unparseable/invalid — callers should fall back to a raw,
    whitespace-stripped comparison key in that case, same as before this
    module existed, so an invalid/foreign number still gets SOME dedup key
    rather than being silently skipped."""
    if not raw:
        return None
    try:
        parsed = phonenumbers.parse(raw, "CH")
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return None
