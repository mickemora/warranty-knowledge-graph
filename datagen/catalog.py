"""Static reference data for the synthetic warranty dataset.

All names are fictional: the OEM ("Meridian Motors"), its models, dealers, suppliers and
customers are invented. City names are real, so the dealer network has a plausible shape.
"""

MAKE = "Meridian"

# model -> body, engines, trims, the plants that build it, and its share of production
MODELS = {
    "Aster":   {"body": "Sedan",    "code": "AS", "engines": ["2.5L I4", "2.5L I4 Hybrid"],
                "trims": ["LE", "SE", "XLE"], "plants": ["SMT", "LXK"]},
    "Cascade": {"body": "SUV",      "code": "CA", "engines": ["2.5L I4", "3.5L V6"],
                "trims": ["LE", "XLE", "Limited"], "plants": ["LXK", "CHT"]},
    "Summit":  {"body": "Pickup",   "code": "SU", "engines": ["3.5L V6 Turbo"],
                "trims": ["SR5", "TRD", "Platinum"], "plants": ["SMT"]},
    "Lumen":   {"body": "Crossover", "code": "LU", "engines": ["2.0L I4 Hybrid", "Dual-motor EV"],
                "trims": ["S", "XSE"], "plants": ["CHT"]},
}

PLANTS = {
    # code: (VIN plant character, display name)
    "SMT": ("S", "San Marcos, TX"),
    "LXK": ("L", "Lexington, KY"),
    "CHT": ("C", "Chattanooga, TN"),
}

# Vehicles built per (model, model year, plant). Aster MY2022 at San Marcos is the large run
# that contains the planted water-pump problem.
PRODUCTION = {
    ("Aster", 2021, "SMT"): 150, ("Aster", 2021, "LXK"): 90,
    ("Aster", 2022, "SMT"): 470, ("Aster", 2022, "LXK"): 110,
    ("Aster", 2023, "SMT"): 160, ("Aster", 2023, "LXK"): 90,
    ("Aster", 2024, "SMT"): 120,
    ("Cascade", 2021, "LXK"): 110, ("Cascade", 2022, "LXK"): 130, ("Cascade", 2022, "CHT"): 60,
    ("Cascade", 2023, "CHT"): 120, ("Cascade", 2024, "CHT"): 90,
    ("Summit", 2021, "SMT"): 70, ("Summit", 2022, "SMT"): 90, ("Summit", 2023, "SMT"): 90,
    ("Summit", 2024, "SMT"): 60,
    ("Lumen", 2022, "CHT"): 60, ("Lumen", 2023, "CHT"): 90, ("Lumen", 2024, "CHT"): 90,
}

MODEL_YEAR_CODE = {2020: "L", 2021: "M", 2022: "N", 2023: "P", 2024: "R", 2025: "S"}

# (code, name, city, state, region)
DEALERS = [
    ("D001", "Dallas Meridian", "Dallas", "TX", "South Central"),
    ("D002", "Plano Meridian", "Plano", "TX", "South Central"),
    ("D003", "Fort Worth Meridian", "Fort Worth", "TX", "South Central"),
    ("D004", "Austin Meridian", "Austin", "TX", "South Central"),
    ("D005", "San Antonio Meridian", "San Antonio", "TX", "South Central"),
    ("D006", "Houston North Meridian", "Houston", "TX", "South Central"),
    ("D007", "Houston West Meridian", "Katy", "TX", "South Central"),
    ("D008", "Waco Meridian", "Waco", "TX", "South Central"),
    ("D009", "Lubbock Meridian", "Lubbock", "TX", "South Central"),
    ("D010", "El Paso Meridian", "El Paso", "TX", "Mountain"),
    ("D011", "Oklahoma City Meridian", "Oklahoma City", "OK", "South Central"),
    ("D012", "Tulsa Meridian", "Tulsa", "OK", "South Central"),
    ("D013", "Little Rock Meridian", "Little Rock", "AR", "South Central"),
    ("D014", "Prosper Meridian", "Prosper", "TX", "South Central"),
    ("D015", "Shreveport Meridian", "Shreveport", "LA", "South Central"),
    ("D016", "Baton Rouge Meridian", "Baton Rouge", "LA", "Southeast"),
    ("D017", "Tyler Meridian", "Tyler", "TX", "South Central"),
    ("D018", "Albuquerque Meridian", "Albuquerque", "NM", "Mountain"),
    ("D019", "Denver Meridian", "Denver", "CO", "Mountain"),
    ("D020", "Wichita Meridian", "Wichita", "KS", "Midwest"),
    ("D021", "Kansas City Meridian", "Kansas City", "MO", "Midwest"),
    ("D022", "Memphis Meridian", "Memphis", "TN", "Southeast"),
    ("D023", "Nashville Meridian", "Nashville", "TN", "Southeast"),
    ("D024", "Birmingham Meridian", "Birmingham", "AL", "Southeast"),
]
SHOWCASE_DEALER = "D014"     # Prosper Meridian, as on the infographic's explorer mockup
COMEBACK_DEALER = "D017"     # Tyler Meridian: planted repeat repairs and high labor hours

# (code, name, city, country)
SUPPLIERS = [
    ("S01", "Apex Thermal Systems", "Monterrey", "MX"),
    ("S02", "Northstar Electronics", "Auburn Hills", "US"),
    ("S03", "Keystone Brake Co.", "Erie", "US"),
    ("S04", "Ridgeway Drivetrain", "Toledo", "US"),
    ("S05", "Lumina Lighting", "Columbus", "US"),
    ("S06", "Harbor Seating & Trim", "Greenville", "US"),
    ("S07", "Clearview Sensors", "Guadalajara", "MX"),
    ("S08", "Bluewater Fuel Systems", "Saginaw", "US"),
    ("S09", "Granite Chassis Components", "Huntsville", "US"),
    ("S10", "Polar Climate Systems", "Windsor", "CA"),
    ("S11", "Tri-County Powertrain Parts", "Fort Wayne", "US"),
]

# (part number, name, category code, supplier code, unit cost, std labor hours, failure modes)
# A failure mode is (failure code, complaint, cause, correction).
PARTS = [
    ("16100-WP220", "Water Pump Assembly", "PT-COOL", "S01", 186.40, 2.6, [
        ("COOL-LEAK", "Coolant leak under the front of the engine; low coolant warning",
         "Water pump shaft seal weeping coolant", "Replaced water pump assembly and gasket, refilled coolant"),
        ("COOL-NOISE", "Whining noise from the engine bay that rises with RPM",
         "Water pump bearing worn", "Replaced water pump assembly, refilled and bled coolant")]),
    ("16400-RD118", "Radiator", "PT-COOL", "S01", 312.00, 2.1, [
        ("COOL-LEAK", "Coolant puddle at front of vehicle",
         "Radiator end-tank seam leak", "Replaced radiator, refilled coolant")]),
    ("16031-TH076", "Thermostat Housing", "PT-COOL", "S01", 58.75, 1.2, [
        ("COOL-TEMP", "Temperature gauge reads high in traffic",
         "Thermostat stuck partially closed", "Replaced thermostat and housing")]),
    ("16260-HS301", "Upper Radiator Hose", "PT-COOL", "S11", 34.20, 0.6, [
        ("COOL-LEAK", "Sweet smell and steam after driving", "Hose clamp area cracked",
         "Replaced upper radiator hose")]),
    ("12100-IG440", "Ignition Coil", "PT-ENG", "S02", 72.10, 0.8, [
        ("ENG-MISF", "Check engine light, engine shakes at idle",
         "Ignition coil internal short (P0302)", "Replaced ignition coil")]),
    ("15100-OP210", "Oil Pump", "PT-ENG", "S11", 241.00, 5.2, [
        ("ENG-OILP", "Low oil pressure warning", "Oil pump relief valve sticking",
         "Replaced oil pump")]),
    ("13568-TB509", "Timing Belt Tensioner", "PT-ENG", "S11", 96.30, 3.4, [
        ("ENG-NOISE", "Rattle on cold start", "Tensioner losing hydraulic pressure",
         "Replaced timing belt tensioner")]),
    ("33100-VB733", "Transmission Valve Body", "PT-TRN", "S04", 688.00, 4.8, [
        ("TRN-SHIFT", "Harsh 2-3 upshift", "Valve body solenoid sticking",
         "Replaced valve body, performed relearn")]),
    ("33500-SH114", "Shift Solenoid", "PT-TRN", "S04", 142.50, 2.2, [
        ("TRN-SLIP", "Transmission slips when warm", "Shift solenoid B intermittent",
         "Replaced shift solenoid")]),
    ("23200-FP356", "Fuel Pump Module", "PT-FUEL", "S08", 274.90, 1.9, [
        ("FUEL-NOST", "Engine cranks but will not start", "Fuel pump impeller failure",
         "Replaced fuel pump module")]),
    ("23250-FI118", "Fuel Injector", "PT-FUEL", "S08", 118.00, 1.6, [
        ("FUEL-LEAN", "Check engine light, rough acceleration", "Injector partially clogged",
         "Replaced fuel injector")]),
    ("47730-BC912", "Front Brake Caliper", "CH-BRK", "S03", 164.80, 1.4, [
        ("BRK-DRAG", "Vehicle pulls left when braking", "Caliper piston sticking",
         "Replaced front caliper, bled brakes")]),
    ("44050-AB220", "ABS Modulator", "CH-BRK", "S03", 905.00, 2.8, [
        ("BRK-ABS", "ABS warning light on", "ABS modulator internal valve fault",
         "Replaced ABS modulator, bled system")]),
    ("48510-SA640", "Front Strut Assembly", "CH-SUS", "S09", 221.40, 2.0, [
        ("SUS-NOISE", "Clunk over bumps from front right", "Strut mount bearing worn",
         "Replaced front strut assembly, aligned")]),
    ("48068-CA117", "Lower Control Arm", "CH-SUS", "S09", 133.60, 1.7, [
        ("SUS-NOISE", "Creak when turning into driveways", "Control arm bushing cracked",
         "Replaced lower control arm, aligned")]),
    ("45510-SR803", "Electric Power Steering Rack", "CH-STR", "S09", 1180.00, 4.1, [
        ("STR-ASSIST", "Steering heavy, EPS warning light", "EPS motor torque sensor fault",
         "Replaced steering rack, calibrated angle sensor")]),
    ("28800-BT650", "12V Battery", "EL-BAT", "S02", 168.00, 0.5, [
        ("BAT-DEAD", "Vehicle will not start after sitting overnight", "Battery internal cell failure",
         "Replaced 12V battery")]),
    ("27060-AL220", "Alternator", "EL-BAT", "S02", 389.00, 1.9, [
        ("BAT-CHG", "Battery light on while driving", "Alternator regulator failure",
         "Replaced alternator")]),
    ("86140-HU510", "Infotainment Head Unit", "EL-INF", "S02", 842.00, 1.3, [
        ("INF-REBOOT", "Screen reboots repeatedly", "Head unit software and memory fault",
         "Replaced head unit, updated software"),
        ("INF-BT", "Phone will not stay paired", "Bluetooth module fault in head unit",
         "Replaced head unit")]),
    ("86190-CM118", "Backup Camera", "EL-INF", "S07", 214.00, 0.9, [
        ("INF-CAM", "Backup camera image black", "Camera connector water intrusion",
         "Replaced backup camera")]),
    ("88210-RS402", "Front Radar Sensor", "EL-ADAS", "S07", 612.00, 1.5, [
        ("ADAS-RADAR", "Pre-collision system unavailable message", "Radar sensor internal fault",
         "Replaced radar sensor, performed aiming")]),
    ("89341-PS220", "Parking Sensor", "EL-ADAS", "S07", 88.40, 0.8, [
        ("ADAS-PARK", "Parking sensor beeps continuously", "Sensor diaphragm damaged",
         "Replaced parking sensor")]),
    ("81110-HL730", "LED Headlamp Assembly", "EL-LGT", "S05", 734.00, 1.1, [
        ("LGT-COND", "Condensation inside headlamp", "Headlamp vent seal defect",
         "Replaced headlamp assembly, aimed")]),
    ("81550-TL210", "Tail Lamp Assembly", "EL-LGT", "S05", 196.00, 0.6, [
        ("LGT-OUT", "Tail lamp segment out", "LED board failure", "Replaced tail lamp")]),
    ("69040-DL115", "Door Lock Actuator", "BD-HW", "S06", 92.70, 1.2, [
        ("BODY-LOCK", "Rear door will not unlock with key fob", "Lock actuator motor failure",
         "Replaced door lock actuator")]),
    ("68620-WR301", "Window Regulator", "BD-HW", "S06", 128.40, 1.4, [
        ("BODY-WIN", "Window drops into door", "Regulator cable snapped",
         "Replaced window regulator")]),
    ("71071-SC220", "Driver Seat Cushion Heater", "BD-TRIM", "S06", 154.00, 2.4, [
        ("TRIM-HEAT", "Driver seat heater not working", "Heater element open circuit",
         "Replaced seat cushion heater")]),
    ("88320-AC514", "A/C Compressor", "CL-HVAC", "S10", 724.00, 3.1, [
        ("HVAC-WARM", "A/C blows warm air", "Compressor clutch coil failure",
         "Replaced A/C compressor, evacuated and recharged")]),
    ("87103-BM209", "Blower Motor", "CL-HVAC", "S10", 146.00, 0.9, [
        ("HVAC-NOAIR", "No airflow from vents on low settings", "Blower motor resistor and motor fault",
         "Replaced blower motor")]),
]
SHOWCASE_PART = "16100-WP220"

# Relative claim frequency by category (baseline, all models).
CATEGORY_WEIGHT = {
    "PT-COOL": 5, "PT-ENG": 9, "PT-TRN": 6, "PT-FUEL": 6, "CH-BRK": 10, "CH-SUS": 9,
    "CH-STR": 3, "EL-BAT": 12, "EL-INF": 14, "EL-ADAS": 7, "EL-LGT": 6, "BD-HW": 9,
    "BD-TRIM": 4, "CL-HVAC": 8,
}

FIRST_NAMES = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery",
               "Quinn", "Parker", "Rowan", "Hayden", "Emerson", "Reese", "Skyler", "Dakota",
               "Cameron", "Logan", "Drew", "Sam", "Elliot", "Harper", "Kai", "Blake"]
LAST_NAMES = ["Garcia", "Nguyen", "Patel", "Johnson", "Martinez", "Kim", "Brown", "Lopez",
              "Wilson", "Anderson", "Thomas", "Moore", "Jackson", "Lee", "Harris", "Clark",
              "Lewis", "Walker", "Hall", "Young", "Allen", "Wright", "Scott", "Green",
              "Baker", "Adams", "Nelson", "Hill", "Campbell", "Mitchell"]

MAINTENANCE_OPS = ["Oil and filter change", "Tire rotation", "Multipoint inspection",
                   "Cabin air filter replacement", "Brake fluid exchange", "Wheel alignment"]
