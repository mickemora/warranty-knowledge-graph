"""Synthetic warranty dataset, written as the CSV extracts a warranty system would export.

    python -m datagen.generate                     # writes data/generated/raw/*.csv + manifest.json
    python -m datagen.generate --seed 7 --out /tmp/wkg
    python -m datagen.generate --inject-defects    # adds known data-quality defects (SHACL demo)

The CSVs are the *source* data. The pipeline's transform step (warranty_kg/mapping.py) turns
them into RDF that conforms to the ontology; nothing here knows about RDF.

Three business signals are planted so the competency questions have something real to find:

1. Supplier defect: Apex Thermal Systems water pumps (16100-WP220) on Aster MY2022 vehicles
   built at San Marcos, TX between 2021-09-01 and 2021-12-15 fail far above the baseline rate.
2. Repeat repairs: a group of vehicles serviced at Tyler Meridian (D017) come back within
   weeks with a second claim on the same part, and that dealer books high labor hours.
3. A showcase claim matching the infographic's explorer mockup: claim C-100245, a water pump on
   an Aster at Prosper Meridian, based on repair order RO-987654.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from datagen import catalog as C
from warranty_kg.vin import check_digit, is_valid

AS_OF = date(2026, 9, 30)
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "generated"

DEFECT_PART = C.SHOWCASE_PART
DEFECT_MODEL, DEFECT_YEAR, DEFECT_PLANT = "Aster", 2022, "SMT"
DEFECT_FROM, DEFECT_TO = date(2021, 9, 1), date(2021, 12, 15)
DEFECT_RATE = 0.42

SHOWCASE_CLAIM, SHOWCASE_RO, SHOWCASE_SERIAL = "C-100245", "RO-987654", "123456"

BASELINE_CLAIMS_PER_VEHICLE = 0.45
COMEBACK_VEHICLES = 14
COMEBACK_LABOR_FACTOR = 1.55
POWERTRAIN_COVERAGE = (60, 60_000)   # months, miles
BASIC_COVERAGE = (36, 36_000)

vin_check_digit = check_digit
vin_is_valid = is_valid


def make_vin(model: str, engine_idx: int, trim_idx: int, year: int, plant: str, serial: str) -> str:
    vds = f"{C.MODELS[model]['code']}{'ABCDEF'[engine_idx]}{'ABCDEF'[trim_idx]}2"
    partial = f"5MR{vds}0{C.MODEL_YEAR_CODE[year]}{C.PLANTS[plant][0]}{serial}"
    return partial[:8] + vin_check_digit(partial) + partial[9:]


def months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    return months - (1 if end.day < start.day else 0)


def add_months(d: date, months: int, extra_days: int = 0) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    day = min(d.day, 28)
    return date(d.year + y, m + 1, day) + timedelta(days=extra_days)


@dataclass
class Dataset:
    seed: int
    suppliers: list[dict] = field(default_factory=list)
    parts: list[dict] = field(default_factory=list)
    dealers: list[dict] = field(default_factory=list)
    customers: list[dict] = field(default_factory=list)
    vehicles: list[dict] = field(default_factory=list)
    repair_orders: list[dict] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    signals: dict = field(default_factory=dict)
    defects: list[dict] = field(default_factory=list)

    TABLES = ("suppliers", "parts", "dealers", "customers", "vehicles", "repair_orders", "claims")

    def write(self, out: Path) -> Path:
        raw = out / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        for name in self.TABLES:
            rows = getattr(self, name)
            with open(raw / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        (out / "manifest.json").write_text(json.dumps(self.manifest(), indent=2) + "\n")
        return out

    def manifest(self) -> dict:
        return {"seed": self.seed, "asOf": AS_OF.isoformat(),
                "counts": {n: len(getattr(self, n)) for n in self.TABLES},
                "signals": self.signals, "injectedDefects": self.defects}


class Generator:
    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self.ds = Dataset(seed=seed)
        self._claim_numbers = self._unique_pool(100001, 199999, exclude={SHOWCASE_CLAIM[2:]})
        self._ro_numbers = self._unique_pool(500001, 999999, exclude={SHOWCASE_RO[3:]})
        self._serials = self._unique_pool(100000, 999999, exclude={SHOWCASE_SERIAL})

    # ------------------------------------------------------------------ helpers
    def _unique_pool(self, lo: int, hi: int, exclude: set[str]):
        seen = set(exclude)
        while True:
            n = str(self.rng.randint(lo, hi))
            if n not in seen:
                seen.add(n)
                yield n

    def _poisson(self, lam: float) -> int:
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.rng.random()
            if p <= limit:
                return k
            k += 1

    # ------------------------------------------------------------------ build
    def run(self) -> Dataset:
        r = self.rng
        ds = self.ds
        ds.suppliers = [{"supplier_code": c, "name": n, "city": city, "country": cc}
                        for c, n, city, cc in C.SUPPLIERS]
        ds.parts = [{"part_number": pn, "part_name": name, "category_code": cat,
                     "supplier_code": sup, "unit_cost": f"{cost:.2f}",
                     "std_labor_hours": f"{hours:.1f}"}
                    for pn, name, cat, sup, cost, hours, _ in C.PARTS]
        self.part_info = {p[0]: p for p in C.PARTS}
        self.parts_by_cat: dict[str, list[str]] = {}
        for p in C.PARTS:
            self.parts_by_cat.setdefault(p[2], []).append(p[0])

        ds.dealers = [{"dealer_code": c, "name": n, "city": city, "state": st, "region": reg}
                      for c, n, city, st, reg in C.DEALERS]
        self.dealer = {d["dealer_code"]: d for d in ds.dealers}
        self.labor_rate = {d["dealer_code"]: r.choice([150, 155, 160, 165, 170, 175, 185])
                           for d in ds.dealers}
        # Bigger stores sell more; Prosper and Tyler are weighted so their signals have volume.
        weights = {d["dealer_code"]: 1.0 for d in ds.dealers}
        weights.update({"D001": 2.0, "D002": 1.6, "D006": 1.8, "D014": 1.6, "D017": 1.1})
        self.dealer_codes = list(weights)
        self.dealer_weights = list(weights.values())

        self._vehicles()
        self._baseline_claims()
        self._supplier_defect()
        self._comebacks()
        self._maintenance_ros()
        ds.claims.sort(key=lambda c: (c["claim_date"], c["claim_number"]))
        ds.repair_orders.sort(key=lambda ro: (ro["open_date"], ro["ro_number"]))
        self._signals()
        return ds

    def _new_customer(self, dealer_code: str) -> dict:
        r = self.rng
        d = self.dealer[dealer_code]
        cust = {"customer_id": f"CU{len(self.ds.customers) + 1:05d}",
                "name": f"{r.choice(C.FIRST_NAMES)} {r.choice(C.LAST_NAMES)}",
                "city": d["city"], "state": d["state"], "preferred_dealer_code": dealer_code}
        self.ds.customers.append(cust)
        return cust

    def _vehicles(self):
        r = self.rng
        self.showcase_vin = None
        for (model, year, plant), count in C.PRODUCTION.items():
            spec = C.MODELS[model]
            start = date(year - 1, 7, 1)
            span = (date(year, 6, 30) - start).days
            for i in range(count):
                build = start + timedelta(days=r.randint(0, span))
                showcase = (model, year, plant) == (DEFECT_MODEL, DEFECT_YEAR, DEFECT_PLANT) and i == 0
                if showcase:
                    build = date(2021, 10, 18)
                in_service = min(build + timedelta(days=r.randint(20, 150)), AS_OF)
                engine_idx = r.randrange(len(spec["engines"]))
                trim_idx = r.randrange(len(spec["trims"]))
                serial = SHOWCASE_SERIAL if showcase else next(self._serials)
                vin = make_vin(model, engine_idx, trim_idx, year, plant, serial)
                selling = "D014" if showcase else r.choices(self.dealer_codes, self.dealer_weights)[0]
                # 8% of customers own a second vehicle.
                same = [c for c in self.ds.customers[-40:] if c["preferred_dealer_code"] == selling]
                owner = (r.choice(same) if same and r.random() < 0.08 and not showcase
                         else self._new_customer(selling))
                if showcase:
                    owner["preferred_dealer_code"] = "D014"
                    self.showcase_vin = vin
                self.ds.vehicles.append({
                    "vin": vin, "make": C.MAKE, "model": model, "model_year": year,
                    "trim": spec["trims"][trim_idx], "engine": spec["engines"][engine_idx],
                    "assembly_plant": C.PLANTS[plant][1], "plant_code": plant,
                    "build_date": build.isoformat(), "in_service_date": in_service.isoformat(),
                    "selling_dealer_code": selling, "owner_customer_id": owner["customer_id"],
                    "_miles_per_month": max(450, min(2400, r.gauss(1150, 280))),
                })
        self.vehicle = {v["vin"]: v for v in self.ds.vehicles}
        self.customer = {c["customer_id"]: c for c in self.ds.customers}

    def _claim_dealer(self, v: dict) -> str:
        pref = self.customer[v["owner_customer_id"]]["preferred_dealer_code"]
        if self.rng.random() < 0.82:
            return pref
        region = self.dealer[pref]["region"]
        return self.rng.choice([d for d in self.dealer if self.dealer[d]["region"] == region])

    def _add_claim(self, v: dict, part_number: str, mis: int, dealer: str, *,
                   extra_days: int = 0, claim_number: str | None = None,
                   ro_number: str | None = None, mileage: int | None = None,
                   mode: int | None = None) -> dict | None:
        r = self.rng
        pn, name, cat, _sup, unit_cost, std_hours, modes = self.part_info[part_number]
        in_service = date.fromisoformat(v["in_service_date"])
        months_cov, miles_cov = POWERTRAIN_COVERAGE if cat.startswith("PT-") else BASIC_COVERAGE
        claim_date = add_months(in_service, mis, extra_days)
        if mis > months_cov or claim_date > AS_OF or claim_date <= in_service:
            return None
        if mileage is None:
            mileage = int(max(25, (mis + extra_days / 30) * v["_miles_per_month"] * r.uniform(0.85, 1.15)))
        if mileage > miles_cov:
            return None
        code, complaint, cause, correction = modes[r.randrange(len(modes)) if mode is None else mode]
        hours = std_hours * r.uniform(0.9, 1.2)
        if dealer == C.COMEBACK_DEALER:
            hours *= COMEBACK_LABOR_FACTOR
        hours = round(hours, 1)
        labor = round(hours * self.labor_rate[dealer], 2)
        parts_cost = round(unit_cost * 1.35, 2)
        age = (AS_OF - claim_date).days
        status = ("SUBMITTED" if age < 14 else "REVIEW" if age < 30 else
                  "APPROVED" if age < 45 else "REJECTED" if r.random() < 0.04 else "PAID")

        ro_no = ro_number or f"RO-{next(self._ro_numbers)}"
        open_date = claim_date - timedelta(days=r.randint(0, 3))
        replaced = [pn]
        if cat == "PT-COOL" and pn != "16260-HS301" and r.random() < 0.15:
            replaced.append("16260-HS301")
        self.ds.repair_orders.append({
            "ro_number": ro_no, "vin": v["vin"], "dealer_code": dealer,
            "open_date": open_date.isoformat(), "close_date": claim_date.isoformat(),
            "mileage_in": mileage, "labor_operation": f"Replace {name.lower()}",
            "pay_type": "Warranty", "replaced_part_numbers": "|".join(replaced)})
        claim = {
            "claim_number": claim_number or f"C-{next(self._claim_numbers)}",
            "vin": v["vin"], "dealer_code": dealer, "ro_number": ro_no,
            "claim_date": claim_date.isoformat(), "status": status,
            "causal_part_number": pn, "failure_code": code, "complaint": complaint,
            "cause": cause, "correction": correction, "mileage": mileage,
            "labor_hours": f"{hours:.1f}", "labor_cost": f"{labor:.2f}",
            "parts_cost": f"{parts_cost:.2f}", "total_cost": f"{labor + parts_cost:.2f}"}
        self.ds.claims.append(claim)
        return claim

    def _available_months(self, v: dict) -> int:
        return months_between(date.fromisoformat(v["in_service_date"]), AS_OF)

    def _baseline_claims(self):
        r = self.rng
        cats, weights = list(C.CATEGORY_WEIGHT), list(C.CATEGORY_WEIGHT.values())
        for v in self.ds.vehicles:
            avail = self._available_months(v)
            if avail < 2:
                continue
            # Exposure-adjusted: newer vehicles have had less time to fail.
            lam = BASELINE_CLAIMS_PER_VEHICLE * min(1.0, avail / 36)
            for _ in range(self._poisson(lam)):
                cat = r.choices(cats, weights)[0]
                part = r.choice(self.parts_by_cat[cat])
                mis = r.randint(1, min(avail, 58))
                self._add_claim(v, part, mis, self._claim_dealer(v), extra_days=r.randint(0, 27))

    def _in_defect_cohort(self, v: dict) -> bool:
        return (v["model"] == DEFECT_MODEL and v["model_year"] == DEFECT_YEAR
                and v["plant_code"] == DEFECT_PLANT
                and DEFECT_FROM <= date.fromisoformat(v["build_date"]) <= DEFECT_TO)

    def _supplier_defect(self):
        r = self.rng
        cohort = [v for v in self.ds.vehicles if self._in_defect_cohort(v)]
        self.cohort_claims = 0
        for v in cohort:
            if v["vin"] == self.showcase_vin:
                self._add_claim(v, DEFECT_PART, 14, "D014", extra_days=9,
                                claim_number=SHOWCASE_CLAIM, ro_number=SHOWCASE_RO,
                                mileage=15_482, mode=0)
                self.cohort_claims += 1
                continue
            if r.random() < DEFECT_RATE:
                mis = int(r.triangular(5, 24, 12))
                if self._add_claim(v, DEFECT_PART, mis, self._claim_dealer(v),
                                   extra_days=r.randint(0, 27)):
                    self.cohort_claims += 1
        self.cohort_size = len(cohort)

    def _comebacks(self):
        r = self.rng
        candidates = [v for v in self.ds.vehicles
                      if self.customer[v["owner_customer_id"]]["preferred_dealer_code"]
                      == C.COMEBACK_DEALER and self._available_months(v) >= 10]
        r.shuffle(candidates)
        parts = ["86140-HU510", "48510-SA640", "88320-AC514", "12100-IG440", "45510-SR803"]
        self.comeback_vins = []
        for v in candidates:
            if len(self.comeback_vins) >= COMEBACK_VEHICLES:
                break
            part = r.choice(parts)
            mis = r.randint(4, min(self._available_months(v) - 3, 30))
            first = self._add_claim(v, part, mis, C.COMEBACK_DEALER, extra_days=r.randint(0, 5))
            if not first:
                continue
            gap = r.randint(20, 70)
            second = self._add_claim(v, part, mis, C.COMEBACK_DEALER, extra_days=gap + 5,
                                     mileage=first["mileage"] + r.randint(300, 2400))
            if second:
                self.comeback_vins.append(v["vin"])

    def _maintenance_ros(self):
        r = self.rng
        for v in r.sample(self.ds.vehicles, 520):
            avail = self._available_months(v)
            if avail < 3:
                continue
            mis = r.randint(2, avail)
            open_date = add_months(date.fromisoformat(v["in_service_date"]), mis)
            if open_date > AS_OF:
                continue
            self.ds.repair_orders.append({
                "ro_number": f"RO-{next(self._ro_numbers)}", "vin": v["vin"],
                "dealer_code": self.customer[v["owner_customer_id"]]["preferred_dealer_code"],
                "open_date": open_date.isoformat(), "close_date": open_date.isoformat(),
                "mileage_in": int(mis * v["_miles_per_month"]),
                "labor_operation": r.choice(C.MAINTENANCE_OPS), "pay_type": "CustomerPay",
                "replaced_part_numbers": ""})

    def _signals(self):
        for v in self.ds.vehicles:
            v.pop("_miles_per_month", None)
            v.pop("plant_code", None)
        self.ds.signals = {
            "supplierDefect": {
                "partNumber": DEFECT_PART, "supplierCode": "S01", "model": DEFECT_MODEL,
                "modelYear": DEFECT_YEAR, "plant": C.PLANTS[DEFECT_PLANT][1],
                "buildFrom": DEFECT_FROM.isoformat(), "buildTo": DEFECT_TO.isoformat(),
                "cohortVehicles": self.cohort_size, "cohortClaims": self.cohort_claims},
            "repeatRepairs": {"dealerCode": C.COMEBACK_DEALER,
                              "vehicles": len(self.comeback_vins),
                              "laborHoursFactor": COMEBACK_LABOR_FACTOR},
            "showcase": {"claimNumber": SHOWCASE_CLAIM, "vin": self.showcase_vin,
                         "dealerCode": "D014", "roNumber": SHOWCASE_RO,
                         "partNumber": DEFECT_PART, "supplierCode": "S01"},
        }


def inject_defects(ds: Dataset, rng: random.Random | None = None) -> Dataset:
    """Corrupt a few records in known ways so the SHACL validation has something to catch."""
    rng = rng or random.Random(99)
    vehicles = {v["vin"]: v for v in ds.vehicles}
    ros = {ro["ro_number"]: ro for ro in ds.repair_orders}
    claims = [c for c in ds.claims if c["claim_number"] != SHOWCASE_CLAIM]
    picks = rng.sample(claims, 7)

    def log(kind, record, detail):
        ds.defects.append({"defect": kind, "record": record, "detail": detail})

    c = picks[0]
    v = vehicles[c["vin"]]
    c["claim_date"] = (date.fromisoformat(v["in_service_date"]) - timedelta(days=30)).isoformat()
    log("CLAIM_BEFORE_IN_SERVICE", c["claim_number"], "claim date set 30 days before in-service")
    c = picks[1]
    c["total_cost"] = f"{float(c['total_cost']) + 250:.2f}"
    log("TOTAL_MISMATCH", c["claim_number"], "total cost is not labor + parts")
    c = picks[2]
    c["parts_cost"] = f"-{c['parts_cost']}"
    log("NEGATIVE_COST", c["claim_number"], "parts cost is negative")
    c = picks[3]
    ro_dealer = ros[c["ro_number"]]["dealer_code"]
    c["dealer_code"] = next(d["dealer_code"] for d in ds.dealers if d["dealer_code"] != ro_dealer)
    log("DEALER_MISMATCH", c["claim_number"], "claim dealer differs from repair order dealer")
    c = picks[4]
    c["causal_part_number"] = ""
    log("MISSING_CAUSAL_PART", c["claim_number"], "no causal part")
    c = picks[5]
    c["labor_hours"] = "55.0"
    log("LABOR_HOURS_OUT_OF_RANGE", c["claim_number"], "55 labor hours")
    c = picks[6]
    old = c["claim_number"]
    c["claim_number"] = old[:-1]
    log("BAD_CLAIM_NUMBER", c["claim_number"], f"was {old}")
    # A VIN with a letter O, which VINs never contain; rewritten everywhere it is referenced.
    v = rng.choice([v for v in ds.vehicles if v["vin"] != ds.signals["showcase"]["vin"]])
    bad = v["vin"][:3] + "O" + v["vin"][4:]
    for table in (ds.vehicles, ds.claims, ds.repair_orders):
        for row in table:
            if row.get("vin") == v["vin"]:
                row["vin"] = bad
    log("BAD_VIN_FORMAT", bad, "VIN contains the letter O")
    return ds


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--inject-defects", action="store_true")
    args = ap.parse_args()
    ds = Generator(args.seed).run()
    if args.inject_defects:
        inject_defects(ds)
    ds.write(args.out)
    m = ds.manifest()
    print(json.dumps({"out": str(args.out), "counts": m["counts"], "signals": m["signals"],
                      "injectedDefects": len(m["injectedDefects"])}, indent=2))


if __name__ == "__main__":
    main()
