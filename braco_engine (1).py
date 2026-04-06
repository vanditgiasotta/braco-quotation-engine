"""
Braco Selection Engine v1.1 — Cluster 1 Foundation
Key fixes from Sample 5 cross-verification:
  - Half-core lug uses IS standard neutral table (not sqmm/2)
  - OD lookup uses FLAT armour by default (matches Sample 5)
  - Small lugs added: 1.5, 2.5, 4, 6sqmm (copper pin-type / aluminium)
  - Sample 5 ODs used as verification targets
"""

import json, bisect
from dataclasses import dataclass, field
from typing import Optional

# ── IS Standard Reduced Neutral Conductor Size for 3.5C Cables ────────
# Source: IS 7098 / Sample 5 cross-verification. DO NOT compute — use table.
HALF_CORE_NEUTRAL_TABLE = {
    16: 10, 25: 16, 35: 16, 50: 25, 70: 35,
    95: 50, 120: 70, 150: 70, 185: 95,
    240: 120, 300: 150, 400: 185, 500: 240, 630: 300,
}

# ── Gland DB ───────────────────────────────────────────────────────────
GLAND_DB = {
    "BPW": [
        ("BPW-01",   13,  18,  178), ("BPW-02",  18,  20,  211),
        ("BPW-03",   20,  23,  214), ("BPW-04",  23,  26,  293),
        ("BPW-05",   26,  30,  364), ("BPW-06",  30,  33,  459),
        ("BPW-07",   33,  37,  616), ("BPW-08",  37,  41,  740),
        ("BPW-09",   41,  46,  809), ("BPW-010", 46,  52,  973),
        ("BPW-011",  52,  60, 1457), ("BPW-012", 60,  66, 1713),
        ("BPW-013",  66,  72, 2223), ("BPW-014", 72,  78, 2836),
        ("BPW-015",  78,  88, 3756), ("BPW-016", 88, 104, 5063),
    ],
    "BPF": [
        ("BPF-01",  13, 18,  197), ("BPF-02",  18, 20,  232),
        ("BPF-03",  20, 23,  236), ("BPF-04",  23, 26,  323),
        ("BPF-05",  26, 30,  400), ("BPF-06",  30, 33,  506),
        ("BPF-07",  33, 37,  678), ("BPF-08",  37, 41,  815),
        ("BPF-09",  41, 46,  890), ("BPF-010", 46, 52, 1070),
        ("BPF-011", 52, 60, 1603), ("BPF-012", 60, 66, 1884),
        ("BPF-013", 66, 72, 2446),
    ],
    "BPT": [
        ("BPT-001SS",  5, 10,  271), ("BPT-001S", 10, 13.5, 271),
        ("BPT-001",   11, 14.5, 319), ("BPT-01L", 14, 18,  440),
        ("BPT-02",    18, 20,  491), ("BPT-03SP", 20, 23,  500),
        ("BPT-04L",   23, 26,  759), ("BPT-05L",  26, 30,  852),
        ("BPT-06SP",  30, 33, 1224), ("BPT-07SP", 33, 36, 1475),
        ("BPT-08",    36, 41, 1733), ("BPT-09",   41, 44, 1875),
        ("BPT-010L",  44, 52, 2619), ("BPT-011S", 52, 55, 3406),
        ("BPT-012",   60, 66, 4002),
    ],
    "SSW": [
        ("SSW-01", 13,18,480), ("SSW-02",18,20,570), ("SSW-03",20,23,610),
        ("SSW-04", 23,26,790), ("SSW-05",26,30,980), ("SSW-06",30,33,1240),
        ("SSW-07", 33,37,1665),("SSW-08",37,41,2000),("SSW-09",41,46,2190),
    ],
}

# ── Lug DB (sqmm, barrel_mm, price) ───────────────────────────────────
# Note: Small sizes use copper pin lugs where AT doesn't cover
LUG_DB = [
    ("AT-212",  6,   6,   1.20),  # small copper pin lug
    ("AT-214",  10,  6,   1.90),
    ("AT-216",  16,  8,   2.46),
    ("AT-218",  25,  8,   3.31),
    ("AT-221",  35,  8,   4.36),
    ("AT-312",  50,  10,  6.92),
    ("AT-225",  70,  10, 10.48),
    ("AT-227",  95,  10, 11.39),
    ("AT-230", 120,  12, 16.40),
    ("AT-232", 150,  12, 20.68),
    ("AT-234", 185,  12, 27.80),
    ("AT-236", 240,  12, 44.56),
    ("AT-300", 300,  16, 60.84),
    ("AT-400", 400,  16, 86.50),
    ("AT-500", 500,  20,120.00),
    ("AT-630", 630,  20,168.00),
]
# Small sqmm without standard AT lug — flag for manual selection
SMALL_SQMM_NOTE = {
    1.5: "1.5sqmm: use copper pin lug / ferrule — no standard AT lug",
    2.5: "2.5sqmm: use copper pin lug — no standard AT lug",
    4:   "4sqmm: use copper pin lug — no standard AT lug",
    6:   "6sqmm: use copper pin lug or AT-212 equivalent",
}

# ── Polycab OD Reference (FLAT ARMOUR default — matches Sample 5 usage) ─
# Format: (cores, sqmm, cable_type) → (od_flat, od_round)
POLYCAB_OD = {
    # 2C LV Power
    (2,  2.5,"LV_POWER"):(15.0,16.5),(2,  4,"LV_POWER"):(16.5,18.0),
    (2,  6,  "LV_POWER"):(17.5,19.0),(2, 10,"LV_POWER"):(19.5,21.0),
    (2, 16,  "LV_POWER"):(22.0,24.0),(2, 25,"LV_POWER"):(25.5,27.5),
    # 3C LV Power
    (3,  2.5,"LV_POWER"):(16.0,17.5),(3,  4,"LV_POWER"):(18.0,19.5),
    (3,  6,  "LV_POWER"):(19.5,21.5),(3, 10,"LV_POWER"):(22.5,24.5),
    (3, 16,  "LV_POWER"):(26.0,28.0),(3, 25,"LV_POWER"):(30.0,32.5),
    (3, 35,  "LV_POWER"):(34.0,36.0),
    # 3.5C LV Power — verified against Sample 5 (flat armour ODs)
    (3.5, 25, "LV_POWER"):(23.5,25.0),(3.5, 35, "LV_POWER"):(26.0,28.0),
    (3.5, 50, "LV_POWER"):(30.0,32.0),(3.5, 70, "LV_POWER"):(33.5,36.0),
    (3.5, 95, "LV_POWER"):(36.5,39.0),(3.5,120, "LV_POWER"):(40.5,43.0),
    (3.5,150, "LV_POWER"):(44.5,47.5),(3.5,185, "LV_POWER"):(50.0,53.5),
    (3.5,240, "LV_POWER"):(55.0,58.5),(3.5,300, "LV_POWER"):(61.0,65.0),
    # 4C LV Power
    (4,  2.5,"LV_POWER"):(18.5,20.0),(4,  4,"LV_POWER"):(20.0,22.0),
    (4,  6,  "LV_POWER"):(21.0,23.0),(4, 10,"LV_POWER"):(23.5,25.5),
    (4, 16,  "LV_POWER"):(26.0,28.0),(4, 25,"LV_POWER"):(30.0,32.0),
    (4, 35,  "LV_POWER"):(33.0,35.5),(4, 50,"LV_POWER"):(37.5,40.0),
    (4, 70,  "LV_POWER"):(41.5,44.5),(4, 95,"LV_POWER"):(46.0,49.5),
    (4,120,  "LV_POWER"):(50.0,53.5),(4,150,"LV_POWER"):(54.5,58.0),
    (4,185,  "LV_POWER"):(60.0,64.0),
    # 1C
    (1, 95,"LV_POWER"):(21.0,23.0),(1,120,"LV_POWER"):(23.0,25.0),
    (1,150,"LV_POWER"):(25.0,27.0),(1,185,"LV_POWER"):(27.5,29.5),
    (1,240,"LV_POWER"):(31.0,33.0),(1,300,"LV_POWER"):(34.0,36.5),
    (1,400,"LV_POWER"):(38.0,40.5),(1,630,"LV_POWER"):(47.0,50.0),
    # Control cables
    (4, 1.5,"CONTROL"):(13.0,14.0),(4, 2.5,"CONTROL"):(13.0,14.5),
    (4, 4,  "CONTROL"):(14.0,15.5),(4, 6,  "CONTROL"):(15.5,17.0),
    (4, 10, "CONTROL"):(18.5,20.5),
    (7, 1.5,"CONTROL"):(15.0,16.0),(7, 2.5,"CONTROL"):(16.0,17.5),
    (12,2.5,"CONTROL"):(21.0,22.5),(19,2.5,"CONTROL"):(25.0,26.5),
    (27,2.5,"CONTROL"):(29.0,31.0),
    (12,1.5,"CONTROL"):(18.0,19.5),(19,1.5,"CONTROL"):(21.0,22.5),
    (27,1.5,"CONTROL"):(24.5,26.0),
}


def detect_cable_type(cores, sqmm, description=""):
    d = description.upper()
    if sqmm <= 2.5 and cores >= 2: return "CONTROL"
    if sqmm <= 6 and cores >= 5:   return "CONTROL"
    if "PVC" in d and cores >= 4 and sqmm <= 10: return "CONTROL"
    return "LV_POWER"


def get_od(cores, sqmm, cable_type, od_stated=None, use_flat=True):
    if od_stated is not None:
        return od_stated, "STATED_BY_CLIENT"
    key = (cores, sqmm, cable_type)
    if key in POLYCAB_OD:
        od_flat, od_round = POLYCAB_OD[key]
        return (od_flat if use_flat else od_round), "POLYCAB_FLAT" if use_flat else "POLYCAB_ROUND"
    # Fallback: try LV_POWER if control not found
    if cable_type == "CONTROL":
        key2 = (cores, sqmm, "LV_POWER")
        if key2 in POLYCAB_OD:
            od_flat, od_round = POLYCAB_OD[key2]
            return (od_flat if use_flat else od_round), "POLYCAB_FALLBACK_LV"
    return None, "NOT_FOUND"


def select_gland(series, od):
    for cat_no, od_min, od_max, price in GLAND_DB.get(series, []):
        if od_min <= od <= od_max:
            return (cat_no, od_min, od_max, price)
    return None


def select_lug(sqmm):
    for cat_no, lug_sqmm, barrel, price in LUG_DB:
        if lug_sqmm == sqmm:
            return (cat_no, barrel, price)
    return None


@dataclass
class LineItem:
    line_no: int
    description: str
    cores: float
    sqmm: float
    qty: int
    conductor: str = "CU"
    od_stated: Optional[float] = None
    gland_pref: str = "BPW"
    needs_gland: bool = True
    needs_lug: bool = False
    section: str = ""


@dataclass
class SelectionResult:
    line_no: int
    description: str
    qty: int
    cable_type: str
    od_used: float
    od_source: str
    gland: Optional[dict] = None
    lug_full: Optional[dict] = None
    lug_half: Optional[dict] = None
    flags: list = field(default_factory=list)
    status: str = "OK"


def run_selection(item: LineItem) -> SelectionResult:
    flags = []
    result = SelectionResult(
        line_no=item.line_no, description=item.description, qty=item.qty,
        cable_type="", od_used=0, od_source="",
    )
    cable_type = detect_cable_type(item.cores, item.sqmm, item.description)
    result.cable_type = cable_type

    od, od_source = get_od(item.cores, item.sqmm, cable_type, item.od_stated, use_flat=True)
    if od is None:
        flags.append({"severity": "BLOCK",
            "msg": f"OD not found for {item.cores}C x {item.sqmm}sqmm {cable_type}. "
                   "Add cable to Polycab_OD_Reference or state OD in inquiry."})
        result.flags = flags; result.status = "BLOCK"; return result

    result.od_used = od; result.od_source = od_source

    if od_source != "STATED_BY_CLIENT":
        flags.append({"severity": "INFO",
            "msg": f"OD={od}mm from Polycab flat armour reference. "
                   "Customer must confirm actual cable OD before placing order."})

    if item.needs_gland:
        gland_row = select_gland(item.gland_pref, od)
        if gland_row is None:
            flags.append({"severity": "BLOCK",
                "msg": f"No {item.gland_pref} gland for OD={od}mm. Check series or OD value."})
            result.status = "BLOCK"
        else:
            cat_no, od_min, od_max, price = gland_row
            result.gland = {
                "cat_no": cat_no,
                "description": (f"Braco Double Compression Nickle Plated Brass Cable Glands "
                                f"For Armoured Cables (OD Range {od_min}-{od_max} MM)"),
                "list_price": price, "od_range": f"{od_min}-{od_max}",
                "selection_trace": (f"{item.cores}C×{item.sqmm}sqmm → OD={od}mm "
                                   f"[{od_source}] → {item.gland_pref}({od_min}-{od_max}) → {cat_no}"),
            }

    if item.needs_lug or item.needs_gland:
        # Check for small sqmm without standard lug
        if item.sqmm in SMALL_SQMM_NOTE:
            flags.append({"severity": "WARNING", "msg": SMALL_SQMM_NOTE[item.sqmm]})
        else:
            lug_row = select_lug(item.sqmm)
            if lug_row:
                cat_no, barrel, price = lug_row
                result.lug_full = {
                    "cat_no": cat_no,
                    "description": f"{int(item.sqmm)}-{barrel} SQ MM Braco Aluminium Tube Terminals",
                    "list_price": price, "sqmm": item.sqmm,
                }
            else:
                flags.append({"severity": "WARNING",
                    "msg": f"No lug found for {item.sqmm}sqmm. Add to AT_Lugs sheet."})

        # Half-core: only for 3.5C, using IS neutral table
        if item.cores == 3.5:
            half_sqmm = HALF_CORE_NEUTRAL_TABLE.get(item.sqmm)
            if half_sqmm is None:
                flags.append({"severity": "WARNING",
                    "msg": f"Half-core neutral size unknown for {item.sqmm}sqmm. "
                           "Add to HALF_CORE_NEUTRAL_TABLE."})
            else:
                half_lug = select_lug(half_sqmm)
                if half_lug:
                    cat_no, barrel, price = half_lug
                    result.lug_half = {
                        "cat_no": cat_no,
                        "description": f"{int(half_sqmm)}-{barrel} SQ MM Braco Aluminium Tube Terminals",
                        "list_price": price, "sqmm": half_sqmm,
                    }
                else:
                    flags.append({"severity": "WARNING",
                        "msg": f"Half-core lug not found for {half_sqmm}sqmm."})

    sev = [f["severity"] for f in flags]
    result.status = "BLOCK" if "BLOCK" in sev else ("WARNING" if "WARNING" in sev else ("INFO" if flags else "OK"))
    result.flags = flags
    return result


def calculate_prices(result: SelectionResult, discount_pct: float) -> dict:
    mult = 1 - discount_pct / 100
    bd = {}
    for key, item in [("gland", result.gland), ("lug_full", result.lug_full), ("lug_half", result.lug_half)]:
        if item:
            lp = item["list_price"]
            net = round(lp * mult, 2)
            bd[key] = {"list_price": lp, "net_price": net, "qty": result.qty,
                       "line_total": round(net * result.qty, 2)}
    bd["line_grand_total"] = round(sum(v.get("line_total",0) for v in bd.values()), 2)
    return bd


# ── Test data ──────────────────────────────────────────────────────────
TUNISIA_CHOTTM = [
    LineItem(1,  "2C x 2.5 Sqmm. Cu.",   2,    2.5,  144, needs_gland=True, section="LV Power"),
    LineItem(2,  "2C x 4 Sqmm. Cu.",     2,    4,    160, needs_gland=True, section="LV Power"),
    LineItem(3,  "2C x 6 Sqmm. Cu.",     2,    6,      8, needs_gland=True, section="LV Power"),
    LineItem(4,  "2C x 10 Sqmm. Cu.",    2,   10,      6, needs_gland=True, section="LV Power"),
    LineItem(5,  "4C x 2.5 Sqmm. Cu.",   4,    2.5,   36, needs_gland=True, section="LV Power"),
    LineItem(6,  "4C x 4 Sqmm. Cu.",     4,    4,      6, needs_gland=True, section="LV Power"),
    LineItem(7,  "4C x 6 Sqmm. Cu.",     4,    6,     14, needs_gland=True, section="LV Power"),
    LineItem(8,  "4C x 10 Sqmm. Cu.",    4,   10,      4, needs_gland=True, section="LV Power"),
    LineItem(9,  "4C x 16 Sqmm. Cu.",    4,   16,      6, needs_gland=True, section="LV Power"),
    LineItem(10, "4C x 25 Sqmm. Cu.",    4,   25,     10, needs_gland=True, section="LV Power"),
    LineItem(11, "4C x 50 Sqmm. Cu.",    4,   50,      4, needs_gland=True, section="LV Power"),
    LineItem(12, "1C x 95 Sqmm. Cu",     1,   95,     24, needs_gland=True, section="LV Power"),
    LineItem(13, "3.5C x 300 Sqmm. Cu",  3.5, 300,     4, needs_gland=True, needs_lug=True, section="LV Power"),
    LineItem(14, "4Cx10 Sq.mm CU PVC",   4,   10,    143, needs_gland=True, section="Control"),
    LineItem(15, "4Cx6 Sq.mm CU PVC",    4,    6,    274, needs_gland=True, section="Control"),
    LineItem(16, "4Cx4 Sq.mm CU PVC",    4,    4,     70, needs_gland=True, section="Control"),
    LineItem(17, "4Cx2.5 Sq.mm CU PVC",  4,    2.5,   50, needs_gland=True, section="Control"),
    LineItem(18, "7Cx2.5 Sq.mm CU PVC",  7,    2.5,   60, needs_gland=True, section="Control"),
    LineItem(19, "12Cx1.5 Sq.mm CU PVC", 12,   1.5,   20, needs_gland=True, section="Control"),
]

# Sample 5 verification — uses stated ODs from the actual quotation
SAMPLE5_CASES = [
    LineItem(1,"3CX35",   3,   35, 26, od_stated=25,   needs_gland=True, needs_lug=True),
    LineItem(2,"3.5CX25", 3.5, 25,  8, od_stated=23.5, needs_gland=True, needs_lug=True),
    LineItem(3,"3.5CX35", 3.5, 35, 42, od_stated=26,   needs_gland=True, needs_lug=True),
    LineItem(4,"3.5CX50", 3.5, 50, 12, od_stated=30,   needs_gland=True, needs_lug=True),
    LineItem(5,"3.5CX95", 3.5, 95, 90, od_stated=36.5, needs_gland=True, needs_lug=True),
    LineItem(6,"3.5CX120",3.5,120, 54, od_stated=40.5, needs_gland=True, needs_lug=True),
    LineItem(7,"3.5CX185",3.5,185,  8, od_stated=50,   needs_gland=True, needs_lug=True),
    LineItem(8,"3.5CX240",3.5,240,  4, od_stated=55,   needs_gland=True, needs_lug=True),
    LineItem(9,"3.5CX300",3.5,300, 52, od_stated=61,   needs_gland=True, needs_lug=True),
    LineItem(10,"4CX16",  4,   16, 10, od_stated=23,   needs_gland=True, needs_lug=True),
    LineItem(11,"4CX10",  4,   10, 10, od_stated=20,   needs_gland=True, needs_lug=True),
    LineItem(12,"4CX25",  4,   25, 10, od_stated=24,   needs_gland=True, needs_lug=True),
    LineItem(13,"4CX35",  4,   35, 10, od_stated=27,   needs_gland=True, needs_lug=True),
]

SAMPLE5_EXPECTED = {
    "3CX35":   {"gland":"BPW-04","lug_full":"AT-221","lug_half":None},
    "3.5CX25": {"gland":"BPW-04","lug_full":"AT-218","lug_half":"AT-216"},
    "3.5CX35": {"gland":"BPW-04","lug_full":"AT-221","lug_half":"AT-216"},
    "3.5CX50": {"gland":"BPW-05","lug_full":"AT-312","lug_half":"AT-218"},
    "3.5CX95": {"gland":"BPW-07","lug_full":"AT-227","lug_half":"AT-312"},
    "3.5CX120":{"gland":"BPW-08","lug_full":"AT-230","lug_half":"AT-225"},
    "3.5CX185":{"gland":"BPW-010","lug_full":"AT-234","lug_half":"AT-227"},
    "3.5CX240":{"gland":"BPW-011","lug_full":"AT-236","lug_half":"AT-230"},
    "3.5CX300":{"gland":"BPW-012","lug_full":"AT-300","lug_half":"AT-232"},
    "4CX16":   {"gland":"BPW-03","lug_full":"AT-216","lug_half":None},
    "4CX10":   {"gland":"BPW-02","lug_full":"AT-214","lug_half":None},
    "4CX25":   {"gland":"BPW-04","lug_full":"AT-218","lug_half":None},
    "4CX35":   {"gland":"BPW-05","lug_full":"AT-221","lug_half":None},
}


def run_tests():
    G="\033[92m"; Y="\033[93m"; R="\033[91m"; B="\033[94m"; W="\033[1m"; X="\033[0m"
    DISC = 46

    print(f"\n{W}{'='*68}{X}")
    print(f"{W}  BRACO ENGINE v1.1 — TUNISIA BOQ ChottM{X}")
    print(f"{'='*68}{X}\n")

    grand = 0; current_sec = ""
    for item in TUNISIA_CHOTTM:
        if item.section != current_sec:
            current_sec = item.section
            print(f"\n{B}{W}  ── {current_sec} ──────────────────────────────{X}")
        r = run_selection(item)
        p = calculate_prices(r, DISC)
        grand += p["line_grand_total"]
        badge = f"{G}✅ OK{X}" if r.status in("OK","INFO") else (f"{Y}⚠ WARN{X}" if r.status=="WARNING" else f"{R}🚫 BLOCK{X}")
        print(f"\n  L{item.line_no:2d} {badge} {item.description} Qty:{item.qty}")
        print(f"     Type:{r.cable_type} OD:{r.od_used}mm [{r.od_source}]")
        if r.gland:
            g=r.gland; net=round(g['list_price']*(1-DISC/100),2)
            print(f"     Gland : {g['cat_no']} ₹{g['list_price']} → net ₹{net} ×{item.qty}=₹{p.get('gland',{}).get('line_total','—')}")
            print(f"     Trace : {g['selection_trace']}")
        if r.lug_full:
            lf=r.lug_full; net=round(lf['list_price']*(1-DISC/100),2)
            print(f"     Lug FC: {lf['cat_no']} — {lf['description']} net ₹{net}")
        if r.lug_half:
            lh=r.lug_half; net=round(lh['list_price']*(1-DISC/100),2)
            print(f"     Lug HC: {lh['cat_no']} — {lh['description']} net ₹{net}")
        for f in r.flags:
            c = R if f['severity']=='BLOCK' else (Y if f['severity']=='WARNING' else B)
            print(f"     {c}[{f['severity']}] {f['msg']}{X}")

    print(f"\n  {'─'*64}")
    print(f"  Grand Total @{DISC}% disc: ₹{grand:,.2f}")

    # Sample 5 cross-check
    print(f"\n{W}{'='*68}{X}")
    print(f"{W}  SAMPLE 5 CROSS-VERIFICATION (exact ODs from quotation){X}")
    print(f"{'='*68}{X}\n")
    all_match = True
    for item in SAMPLE5_CASES:
        r = run_selection(item)
        exp = SAMPLE5_EXPECTED.get(item.description, {})
        got_g = r.gland["cat_no"] if r.gland else "—"
        got_f = r.lug_full["cat_no"] if r.lug_full else "—"
        got_h = r.lug_half["cat_no"] if r.lug_half else "—"
        exp_g = exp.get("gland","?")
        exp_f = exp.get("lug_full","?") or "—"
        exp_h = exp.get("lug_half") or "—"
        ok = (got_g==exp_g and got_f==exp_f and got_h==exp_h)
        if not ok: all_match = False
        def chk(g,e): return "✓" if g==e else f"≠{e}"
        mk = f"{G}✅{X}" if ok else f"{R}❌{X}"
        print(f"  {mk} {item.description:<12} Gland:{got_g}({chk(got_g,exp_g)})  "
              f"FC:{got_f}({chk(got_f,exp_f)})  HC:{got_h}({chk(got_h,exp_h)})")

    print()
    if all_match:
        print(f"  {G}{W}✅ ALL SAMPLE 5 CHECKS PASSED — Engine is correct{X}")
    else:
        print(f"  {R}{W}❌ MISMATCHES — Review before proceeding{X}")
    print(f"{'='*68}\n")


if __name__ == "__main__":
    run_tests()
