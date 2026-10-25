"""VIN check digit (ISO 3779 / 49 CFR 565), used by the generator and the transform step."""

TRANSLIT = {**{str(d): d for d in range(10)},
            **dict(zip("ABCDEFGH", range(1, 9))), **dict(zip("JKLMN", range(1, 6))),
            "P": 7, "R": 9, **dict(zip("STUVWXYZ", range(2, 10)))}
WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


def check_digit(vin: str) -> str:
    r = sum(TRANSLIT[c] * w for c, w in zip(vin, WEIGHTS)) % 11
    return "X" if r == 10 else str(r)


def is_valid(vin: str) -> bool:
    if len(vin) != 17 or any(c not in TRANSLIT for c in vin):
        return False
    return vin[8] == check_digit(vin)
