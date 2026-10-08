import re

BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Multiplicative words, applied to the number that directly precedes them.
SCALES = {
    "hajar": 1_000, "hazar": 1_000, "হাজার": 1_000,
    "lakh": 100_000, "lac": 100_000, "lakkh": 100_000, "লাখ": 100_000,
    "koti": 10_000_000, "কোটি": 10_000_000,
}

# Fractional quantity words common in spoken Bangla. Small number words
# ("ek", "dui", "at", "noy") are deliberately NOT converted here: "at" and
# "noy" are also ordinary English/Bangla words ("meeting at 5", "nagad e noy"),
# and the model reads them correctly from context.
WORDS = {
    "arai": 2.5, "আড়াই": 2.5,                       # two and a half
    "dari": 1.5, "dedh": 1.5, "দেড়": 1.5,           # one and a half
}

# Default clock times for vague parts of the day. Users can override later.
DAYPARTS = {
    "bhor": "05:00", "sokal": "08:00", "dupur": "13:00",
    "bikal": "16:00", "bikel": "16:00", "sondha": "18:00",
    "raat": "21:00", "rat": "21:00",
}

_NUM = r"(\d+(?:\.\d+)?)"


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def normalise(text: str) -> str:
    """Bangla digits to ASCII, then quantity words to plain numbers."""
    t = text.translate(BN_DIGITS)
    t = re.sub(r"\s+", " ", t).strip()

    # "sharey tin" is left to the model; "sharey 3" -> "3.5"
    t = re.sub(rf"\bsharey\s+{_NUM}\b",
               lambda m: _fmt(float(m.group(1)) + 0.5), t, flags=re.I)

    # "arai hajar" -> "2.5 hajar"
    for word, val in WORDS.items():
        t = re.sub(rf"(?<!\w){word}(?!\w)", _fmt(val), t, flags=re.I)

    # "2.5 hajar" -> "2500"
    for word, mult in SCALES.items():
        t = re.sub(
            rf"\b{_NUM}\s*{word}(?!\w)",
            lambda m, mult=mult: _fmt(int(float(m.group(1)) * mult)),
            t, flags=re.I,
        )
    return t
