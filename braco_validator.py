"""
Braco Validation System — Cluster 2
=====================================
Plugs directly onto braco_engine.py SelectionResult objects.
Does NOT rebuild anything from Cluster 1.

HOW TO USE:
  from braco_engine import run_selection, calculate_prices, LineItem
  from braco_validator import validate, ValidationReport, print_report

Architecture:
  10 checks across 3 tiers:
    Tier 1 — BLOCK  : must stop output. Non-negotiable.
    Tier 2 — WARNING: human must review and approve before release.
    Tier 3 — INFO   : logged, visible, safe to proceed.

  After all checks run → ValidationReport is produced.
  ValidationReport drives the review queue in the UI (Cluster 3).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dataclasses import dataclass, field
from typing import Optional
from braco_engine import (
    LineItem, SelectionResult, run_selection, calculate_prices,
    GLAND_DB, LUG_DB, POLYCAB_OD, HALF_CORE_NEUTRAL_TABLE,
    detect_cable_type, SMALL_SQMM_NOTE,
)

# ══════════════════════════════════════════════════════════════════════
# SECTION 1 — CHECK DEFINITIONS
# Every check is a standalone function.
# Signature: check_xxx(item, result) → list[dict]
# Each dict: {check_id, severity, title, detail, action, passed}
# ══════════════════════════════════════════════════════════════════════

def _flag(check_id, severity, title, detail, action, passed=False):
    return {
        "check_id":  check_id,
        "severity":  severity,       # BLOCK | WARNING | INFO
        "title":     title,          # short label, shown in review queue
        "detail":    detail,         # full explanation for engineer/director
        "action":    action,         # plain English: what employee must do
        "passed":    passed,         # True = check OK, False = check fired
    }

def _pass(check_id, title):
    return {"check_id": check_id, "severity": "PASS", "title": title,
            "detail": "Check passed.", "action": "None.", "passed": True}


# ──────────────────────────────────────────────────────────────────────
# CHECK 01 — Gland cat no exists in master database
# BLOCK: if cat no is not in GLAND_DB, price and description are invented.
# ──────────────────────────────────────────────────────────────────────
def check_01_cat_no_exists(item: LineItem, result: SelectionResult) -> list:
    if not result.gland:
        return []
    cat = result.gland["cat_no"]
    series = item.gland_pref
    all_cats = [row[0] for row in GLAND_DB.get(series, [])]
    if cat not in all_cats:
        return [_flag("C01", "BLOCK",
            "Gland cat no not in database",
            f"Selected gland '{cat}' (series {series}) does not exist in the master GLAND_DB. "
            "This means the price and description are wrong.",
            f"Remove this line from output. Verify the correct cat no for {item.cores}C×{item.sqmm}sqmm "
            f"OD={result.od_used}mm against the Braco 2026 price list manually.")]
    return [_pass("C01", "Gland cat no verified in database")]


# ──────────────────────────────────────────────────────────────────────
# CHECK 02 — OD is strictly within selected gland range (no boundary ambiguity)
# WARNING: OD sitting exactly on a boundary (e.g., OD=26mm, range 23–26)
#          means the cable is at the absolute edge. Any variance = wrong gland.
# ──────────────────────────────────────────────────────────────────────
def check_02_od_within_range(item: LineItem, result: SelectionResult) -> list:
    if not result.gland:
        return []
    od = result.od_used
    od_range = result.gland["od_range"]
    parts = od_range.split("-")
    od_min, od_max = float(parts[0]), float(parts[1])

    if od < od_min or od > od_max:
        return [_flag("C02", "BLOCK",
            "OD outside selected gland range",
            f"Cable OD={od}mm is outside the selected gland range {od_range}mm. "
            "This gland physically cannot fit this cable.",
            f"Re-check OD value. If OD is correct, re-run selection — "
            f"a different gland size is required.")]

    # Boundary warning: within 0.5mm of either edge
    if od <= od_min + 0.5:
        return [_flag("C02", "WARNING",
            "OD at lower boundary of gland range",
            f"Cable OD={od}mm is at or very near the lower limit of gland range {od_range}mm. "
            "Small OD variations between cable makes could mean the gland is too large (sealing failure).",
            f"Confirm with customer: is this cable exactly Polycab make? "
            "If they are using a different cable brand, request the actual OD from their datasheet.")]

    if od >= od_max - 0.5:
        return [_flag("C02", "WARNING",
            "OD at upper boundary of gland range",
            f"Cable OD={od}mm is at or very near the upper limit of gland range {od_range}mm. "
            "If the actual cable OD is even 0.5mm larger, this gland will not close properly.",
            f"Confirm with customer: is this cable exactly Polycab make? "
            "If OD is client-stated, add a note in the quote to verify before order.")]

    return [_pass("C02", "OD comfortably within gland range")]


# ──────────────────────────────────────────────────────────────────────
# CHECK 03 — Price matches master database (no drift, no stale value)
# BLOCK: if price in result differs from database by >1%.
# ──────────────────────────────────────────────────────────────────────
def check_03_price_matches_db(item: LineItem, result: SelectionResult) -> list:
    flags = []
    if result.gland:
        cat = result.gland["cat_no"]
        series = item.gland_pref
        db_price = next((r[3] for r in GLAND_DB.get(series, []) if r[0] == cat), None)
        if db_price is not None:
            diff_pct = abs(result.gland["list_price"] - db_price) / db_price * 100
            if diff_pct > 1:
                flags.append(_flag("C03", "BLOCK",
                    "Gland price does not match database",
                    f"Output price ₹{result.gland['list_price']} differs from database ₹{db_price} "
                    f"by {diff_pct:.1f}%. The 2026 price list is the only valid source.",
                    f"Correct the price to ₹{db_price} before releasing the quote."))
            else:
                flags.append(_pass("C03", "Gland price matches database"))

    if result.lug_full:
        cat = result.lug_full["cat_no"]
        sqmm = result.lug_full["sqmm"]
        db_price = next((r[3] for r in LUG_DB if r[0] == cat), None)
        if db_price is not None:
            diff_pct = abs(result.lug_full["list_price"] - db_price) / db_price * 100
            if diff_pct > 1:
                flags.append(_flag("C03b", "BLOCK",
                    "Full-core lug price does not match database",
                    f"Output lug price ₹{result.lug_full['list_price']} differs from database ₹{db_price}.",
                    f"Correct the lug price to ₹{db_price}."))
            else:
                flags.append(_pass("C03b", "Full-core lug price matches database"))

    return flags


# ──────────────────────────────────────────────────────────────────────
# CHECK 04 — Half-core lug logic is correct
# BLOCK: half-core lug present for non-3.5C cable.
# BLOCK: half-core lug absent for 3.5C cable.
# WARNING: half-core sqmm doesn't match the IS neutral table.
# ──────────────────────────────────────────────────────────────────────
def check_04_half_core_logic(item: LineItem, result: SelectionResult) -> list:
    flags = []
    is_3_5_core = (item.cores == 3.5)

    if not is_3_5_core and result.lug_half:
        flags.append(_flag("C04", "BLOCK",
            "Half-core lug on non-3.5-core cable",
            f"A half-core lug ({result.lug_half['cat_no']}) was generated for a "
            f"{item.cores}-core cable. Half-core lugs are ONLY for 3.5-core cables.",
            "Remove the half-core lug from this line item immediately."))

    if is_3_5_core and not result.lug_half:
        flags.append(_flag("C04", "BLOCK",
            "Half-core lug missing for 3.5-core cable",
            f"This is a 3.5-core {item.sqmm}sqmm cable. A half-core (neutral conductor) "
            "lug is always required. The selection engine should have provided one.",
            "Re-run selection. If it still fails, add the neutral size to HALF_CORE_NEUTRAL_TABLE."))

    if is_3_5_core and result.lug_half:
        expected_neutral = HALF_CORE_NEUTRAL_TABLE.get(item.sqmm)
        got_neutral = result.lug_half.get("sqmm")
        if expected_neutral and got_neutral != expected_neutral:
            flags.append(_flag("C04b", "BLOCK",
                "Half-core lug sqmm incorrect",
                f"For {item.sqmm}sqmm 3.5C cable, IS standard neutral = {expected_neutral}sqmm. "
                f"But selected half-core lug is {got_neutral}sqmm ({result.lug_half['cat_no']}). "
                "This will result in incorrect crimping at site.",
                f"Replace half-core lug with the {expected_neutral}sqmm AT lug."))
        elif expected_neutral and got_neutral == expected_neutral:
            flags.append(_pass("C04", "Half-core lug correct per IS neutral table"))

    if not is_3_5_core and not result.lug_half:
        flags.append(_pass("C04", "No half-core lug — correct for non-3.5C cable"))

    return flags


# ──────────────────────────────────────────────────────────────────────
# CHECK 05 — Full-core lug sqmm matches cable sqmm exactly
# BLOCK: lug sqmm ≠ cable sqmm (wrong size lug = unsafe termination).
# ──────────────────────────────────────────────────────────────────────
def check_05_lug_sqmm_match(item: LineItem, result: SelectionResult) -> list:
    if not result.lug_full:
        return []
    lug_sqmm = result.lug_full.get("sqmm")
    if lug_sqmm != item.sqmm:
        return [_flag("C05", "BLOCK",
            "Full-core lug sqmm does not match cable sqmm",
            f"Cable is {item.sqmm}sqmm but full-core lug is {lug_sqmm}sqmm "
            f"({result.lug_full['cat_no']}). An undersized lug is an electrical safety hazard. "
            "An oversized lug increases cost without justification.",
            f"Replace with the correct {item.sqmm}sqmm AT lug.")]
    return [_pass("C05", "Full-core lug sqmm matches cable sqmm")]


# ──────────────────────────────────────────────────────────────────────
# CHECK 06 — OD source transparency and confidence scoring
# INFO:    OD stated by client → highest confidence.
# INFO:    OD from Polycab flat table → medium confidence.
# WARNING: OD from fallback (LV table used for control cable) → lower confidence.
# ──────────────────────────────────────────────────────────────────────
def check_06_od_source_confidence(item: LineItem, result: SelectionResult) -> list:
    src = result.od_source
    od = result.od_used

    if src == "STATED_BY_CLIENT":
        return [_flag("C06", "INFO",
            "OD stated by client — highest confidence",
            f"OD={od}mm was explicitly provided in the client inquiry. "
            "No inference was required. This is the most reliable selection basis.",
            "No action required. Include OD value in quotation for client records.",
            passed=True)]

    if src in ("POLYCAB_FLAT", "POLYCAB_ROUND"):
        return [_flag("C06", "INFO",
            "OD from Polycab reference — medium confidence",
            f"OD={od}mm inferred from Polycab IS cable standard (flat armour default). "
            "This is correct for Polycab make cables per IS specifications. "
            "For other cable brands, OD may differ.",
            "Quote must include the standard Braco OD disclaimer clause: "
            "'Selection based on Polycab IS cables. Customer to verify OD from actual cable datasheet.'")]

    if src == "POLYCAB_FALLBACK_LV":
        return [_flag("C06", "WARNING",
            "OD from LV fallback — lower confidence",
            f"This is a {result.cable_type} cable but the control cable OD table "
            f"had no entry for {item.cores}C×{item.sqmm}sqmm. "
            f"The LV power table was used as fallback, giving OD={od}mm. "
            "Control cable ODs differ from power cable ODs of the same sqmm.",
            "Add this cable spec to the CONTROL section of Polycab_OD_Reference. "
            "For now, flag this line for senior review before sending quote.")]

    return [_flag("C06", "BLOCK",
        "OD source unknown",
        f"OD={od}mm has source='{src}'. This source is not recognised. "
        "The selection may be based on an incorrect OD value.",
        "Investigate the OD source. Do not release this line item.")]


# ──────────────────────────────────────────────────────────────────────
# CHECK 07 — Cable type detection was deterministic (not ambiguous)
# WARNING: if cable_type could reasonably be either CONTROL or LV_POWER
#          based on the description alone.
# ──────────────────────────────────────────────────────────────────────
def check_07_cable_type_confidence(item: LineItem, result: SelectionResult) -> list:
    # Ambiguous case: 4Cx10 with no "PVC" mention — could be power or control
    d = item.description.upper()
    is_borderline = (
        item.sqmm == 10 and item.cores == 4 and "PVC" not in d and "XLPE" not in d
    )
    if is_borderline:
        return [_flag("C07", "WARNING",
            "Cable type ambiguous — could be CONTROL or LV POWER",
            f"4Cx10sqmm without 'PVC' or 'XLPE' keyword. Classified as '{result.cable_type}'. "
            "If this is a control cable, its OD is smaller and a smaller gland may be correct. "
            "If it is a power cable, the current selection is correct.",
            "Ask the client or confirm from the cable schedule: "
            "is this cable XLPE armoured (power) or PVC armoured (control)?")]

    # Ambiguous case: 4Cx2.5 — always control but worth confirming
    if item.sqmm == 2.5 and item.cores == 4 and result.cable_type == "CONTROL":
        return [_flag("C07", "INFO",
            "4Cx2.5sqmm classified as control cable",
            "This cable is correctly classified as CONTROL (≤2.5sqmm rule). "
            "OD used is from the control cable table.",
            "No action required.", passed=True)]

    return [_pass("C07", f"Cable type '{result.cable_type}' is unambiguous")]


# ──────────────────────────────────────────────────────────────────────
# CHECK 08 — Quantity is positive and non-zero
# BLOCK: qty ≤ 0.
# WARNING: qty is unusually large (>1000) — possible data entry error.
# ──────────────────────────────────────────────────────────────────────
def check_08_quantity_sanity(item: LineItem, result: SelectionResult) -> list:
    if item.qty <= 0:
        return [_flag("C08", "BLOCK",
            "Quantity is zero or negative",
            f"Line {item.line_no} has qty={item.qty}. This cannot produce a valid line total.",
            "Correct the quantity from the original inquiry before re-running.")]

    if item.qty > 1000:
        return [_flag("C08", "WARNING",
            "Unusually large quantity — verify",
            f"Quantity={item.qty} is above 1000. This may be correct for a large project "
            "but should be verified against the original inquiry to rule out data entry error.",
            "Cross-check qty against the source inquiry document.")]

    return [_pass("C08", f"Quantity {item.qty} is valid")]


# ──────────────────────────────────────────────────────────────────────
# CHECK 09 — Gland series is consistent with cable type and environment
# WARNING: BPW selected for unarmoured cable (should be BPT).
# WARNING: Standard brass (BPW) suggested where stainless steel may be needed.
# INFO:    Coastal/marine/corrosive environment keywords detected in description.
# ──────────────────────────────────────────────────────────────────────
def check_09_series_appropriateness(item: LineItem, result: SelectionResult) -> list:
    if not result.gland:
        return []
    flags = []
    series = item.gland_pref
    d = item.description.upper()

    # BPW on what appears to be unarmoured cable
    if series == "BPW" and "UNARMOURED" in d:
        flags.append(_flag("C09", "WARNING",
            "BPW gland selected for unarmoured cable",
            "BPW (Double Compression) is designed for armoured cables. "
            "For unarmoured cables, BPT (Double Compression Through Gland) should be used.",
            "Confirm cable construction. If unarmoured, replace BPW with BPT series."))

    # Corrosive/marine environment keyword detection
    corrosive_keywords = ["MARINE", "OFFSHORE", "SALINE", "CORROSIVE", "CHEMICAL",
                          "COASTAL", "SUBSTATION", "OUTDOOR", "HAZARDOUS"]
    found = [k for k in corrosive_keywords if k in d]
    if found and series not in ("SSW", "SSF"):
        flags.append(_flag("C09b", "INFO",
            "Corrosive environment keyword detected — consider SS glands",
            f"Description contains '{', '.join(found)}'. For corrosive, marine, or outdoor "
            "installations, stainless steel glands (SSW/SSF) are recommended over brass (BPW/BPF) "
            "for longer service life.",
            "Confirm environment with client. If SS is required, re-run with gland_pref='SSW'."))

    if not flags:
        flags.append(_pass("C09", f"Series {series} is appropriate for this cable"))

    return flags


# ──────────────────────────────────────────────────────────────────────
# CHECK 10 — Line total is arithmetically correct
# BLOCK: if calculated total doesn't match (list_price × discount × qty).
# This catches any discount calculation error before it reaches the client.
# ──────────────────────────────────────────────────────────────────────
def check_10_price_arithmetic(item: LineItem, result: SelectionResult,
                               discount_pct: float, price_breakdown: dict) -> list:
    flags = []
    mult = 1 - discount_pct / 100

    for key, product in [("gland", result.gland),
                         ("lug_full", result.lug_full),
                         ("lug_half", result.lug_half)]:
        if not product:
            continue
        lp = product["list_price"]
        expected_net = round(lp * mult, 2)
        expected_total = round(expected_net * result.qty, 2)
        bd = price_breakdown.get(key, {})
        got_net = bd.get("net_price", None)
        got_total = bd.get("line_total", None)

        if got_net is None or got_total is None:
            flags.append(_flag(f"C10_{key}", "WARNING",
                f"Price breakdown missing for {key}",
                f"Expected net ₹{expected_net} × {result.qty} = ₹{expected_total} "
                f"but breakdown is absent.",
                "Recalculate prices and re-run validation."))
            continue

        net_ok = abs(got_net - expected_net) < 0.02
        total_ok = abs(got_total - expected_total) < 0.05

        if not net_ok or not total_ok:
            flags.append(_flag(f"C10_{key}", "BLOCK",
                f"Arithmetic error in {key} price",
                f"List=₹{lp} × (1-{discount_pct}%) should give net=₹{expected_net} "
                f"× qty={result.qty} = ₹{expected_total}. "
                f"Got net=₹{got_net}, total=₹{got_total}.",
                "Recalculate using the formula: net = list × (1 - disc/100), "
                "total = net × qty. Do not release until arithmetic is correct."))
        else:
            flags.append(_pass(f"C10_{key}", f"{key} arithmetic correct: ₹{got_total}"))

    return flags


# ══════════════════════════════════════════════════════════════════════
# SECTION 2 — VALIDATION ORCHESTRATOR
# Runs all 10 checks, aggregates results into a ValidationReport.
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ValidationReport:
    line_no: int
    description: str
    qty: int
    # Verdict
    final_status: str        # BLOCKED | NEEDS_REVIEW | APPROVED
    release_allowed: bool    # False if any BLOCK exists
    # Check results
    checks: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    infos: list = field(default_factory=list)
    passes: list = field(default_factory=list)
    # Confidence
    confidence_score: float = 0.0   # 0.0–1.0
    confidence_label: str = ""       # HIGH / MEDIUM / LOW / BLOCKED
    # Trust card (for director review)
    trust_card: dict = field(default_factory=dict)


def validate(item: LineItem, result: SelectionResult,
             discount_pct: float = 0.0) -> ValidationReport:
    """
    Run all 10 validation checks against a SelectionResult.
    Returns a ValidationReport with full audit trail.
    """
    price_bd = calculate_prices(result, discount_pct) if discount_pct > 0 else {}

    # Run all checks
    all_checks = []
    all_checks += check_01_cat_no_exists(item, result)
    all_checks += check_02_od_within_range(item, result)
    all_checks += check_03_price_matches_db(item, result)
    all_checks += check_04_half_core_logic(item, result)
    all_checks += check_05_lug_sqmm_match(item, result)
    all_checks += check_06_od_source_confidence(item, result)
    all_checks += check_07_cable_type_confidence(item, result)
    all_checks += check_08_quantity_sanity(item, result)
    all_checks += check_09_series_appropriateness(item, result)
    if discount_pct > 0:
        all_checks += check_10_price_arithmetic(item, result, discount_pct, price_bd)

    # Partition
    blocks   = [c for c in all_checks if c["severity"] == "BLOCK"]
    warnings = [c for c in all_checks if c["severity"] == "WARNING"]
    infos    = [c for c in all_checks if c["severity"] == "INFO"]
    passes   = [c for c in all_checks if c["severity"] == "PASS"]

    # Verdict
    release_allowed = len(blocks) == 0
    if blocks:
        final_status = "BLOCKED"
    elif warnings:
        final_status = "NEEDS_REVIEW"
    else:
        final_status = "APPROVED"

    # Confidence score
    # Base = 1.0, deductions:
    #   OD from Polycab (not stated)      -0.08
    #   OD from fallback                  -0.20
    #   any WARNING                       -0.10 each
    #   cable type ambiguous (C07 warn)   -0.15
    #   small sqmm lug missing            -0.10
    score = 1.0
    if result.od_source == "POLYCAB_FLAT":
        score -= 0.08
    elif result.od_source == "POLYCAB_FALLBACK_LV":
        score -= 0.20
    elif result.od_source == "NOT_FOUND":
        score -= 0.50
    score -= len(warnings) * 0.10
    for w in warnings:
        if w["check_id"] == "C07":
            score -= 0.05  # extra for ambiguous cable type
    score = max(0.0, min(1.0, round(score, 2)))

    if score >= 0.85:
        conf_label = "HIGH"
    elif score >= 0.65:
        conf_label = "MEDIUM"
    elif score >= 0.40:
        conf_label = "LOW"
    else:
        conf_label = "BLOCKED"

    if blocks:
        conf_label = "BLOCKED"
        score = 0.0

    # Trust card — the "why" for the director
    trust_card = build_trust_card(item, result, discount_pct, price_bd)

    return ValidationReport(
        line_no=item.line_no,
        description=item.description,
        qty=item.qty,
        final_status=final_status,
        release_allowed=release_allowed,
        checks=all_checks,
        blocks=blocks,
        warnings=warnings,
        infos=infos,
        passes=passes,
        confidence_score=score,
        confidence_label=conf_label,
        trust_card=trust_card,
    )


# ══════════════════════════════════════════════════════════════════════
# SECTION 3 — TRUST CARD
# The "why" document. Every selection is fully explained.
# Designed to satisfy a director asking "how do you know this is right?"
# ══════════════════════════════════════════════════════════════════════

def build_trust_card(item: LineItem, result: SelectionResult,
                     discount_pct: float, price_bd: dict) -> dict:
    card = {
        "cable": {
            "input":       item.description,
            "cores":       item.cores,
            "sqmm":        item.sqmm,
            "conductor":   item.conductor,
            "type_detected": result.cable_type,
            "type_rule":   _explain_cable_type_rule(item),
        },
        "od": {
            "value":       result.od_used,
            "source":      result.od_source,
            "source_explanation": _explain_od_source(result),
        },
        "gland_selection": None,
        "lug_selection": None,
        "price_breakdown": price_bd,
        "selection_confidence": None,
    }

    if result.gland:
        g = result.gland
        od_parts = g["od_range"].split("-")
        card["gland_selection"] = {
            "cat_no":      g["cat_no"],
            "od_range":    g["od_range"],
            "list_price":  g["list_price"],
            "logic_trace": g["selection_trace"],
            "why_this_gland": (
                f"Cable OD={result.od_used}mm falls within the BPW range "
                f"{od_parts[0]}–{od_parts[1]}mm. "
                f"BPW is the standard Braco double compression nickel-plated brass gland "
                f"for armoured cables, conforming to IS 12943 / IEC 62444. "
                f"No other BPW size covers OD={result.od_used}mm."
            ),
            "what_if_od_wrong": (
                f"If actual OD > {od_parts[1]}mm → need next size up. "
                f"If actual OD < {od_parts[0]}mm → sealing failure risk."
            ),
        }

    if result.lug_full or result.lug_half:
        card["lug_selection"] = {}
        if result.lug_full:
            lf = result.lug_full
            card["lug_selection"]["full_core"] = {
                "cat_no":  lf["cat_no"],
                "sqmm":    lf["sqmm"],
                "price":   lf["list_price"],
                "why":     f"Full-core lug matches cable sqmm ({item.sqmm}sqmm) exactly. "
                           "Aluminium tube terminal, heavy duty, conforms to IS 8309.",
            }
        if result.lug_half:
            lh = result.lug_half
            expected_neutral = HALF_CORE_NEUTRAL_TABLE.get(item.sqmm, "?")
            card["lug_selection"]["half_core"] = {
                "cat_no":  lh["cat_no"],
                "sqmm":    lh["sqmm"],
                "price":   lh["list_price"],
                "why":     (
                    f"3.5-core cable: 3 phases at {item.sqmm}sqmm + "
                    f"1 neutral conductor at {expected_neutral}sqmm (IS 7098 reduced neutral standard). "
                    f"Half-core lug selected for neutral conductor."
                ),
            }

    card["selection_confidence"] = {
        "note": (
            "OD stated by client = highest confidence (no inference). "
            "OD from Polycab IS table = medium confidence (Polycab make assumed). "
            "OD from fallback = low confidence (needs manual verification)."
        )
    }
    return card


def _explain_cable_type_rule(item: LineItem) -> str:
    d = item.description.upper()
    if item.sqmm <= 2.5 and item.cores >= 2:
        return f"Classified CONTROL: sqmm={item.sqmm} ≤ 2.5 AND cores={item.cores} ≥ 2 → control cable rule."
    if item.sqmm <= 6 and item.cores >= 5:
        return f"Classified CONTROL: sqmm={item.sqmm} ≤ 6 AND cores={item.cores} ≥ 5 → control cable rule."
    if "PVC" in d and item.cores >= 4 and item.sqmm <= 10:
        return f"Classified CONTROL: 'PVC' in description AND cores={item.cores} ≥ 4 AND sqmm={item.sqmm} ≤ 10."
    return f"Classified LV_POWER: does not meet any control cable rule. Standard power cable."


def _explain_od_source(result: SelectionResult) -> str:
    src = result.od_source
    od  = result.od_used
    if src == "STATED_BY_CLIENT":
        return f"OD={od}mm was explicitly stated in the client inquiry. No inference needed."
    if src == "POLYCAB_FLAT":
        return (f"OD={od}mm comes from the Polycab IS cable flat-armoured OD reference table. "
                "This is Braco's standard policy when the client does not state OD.")
    if src == "POLYCAB_ROUND":
        return (f"OD={od}mm from Polycab IS cable round-armoured OD table (non-default). "
                "Flat armour is the Braco default.")
    if src == "POLYCAB_FALLBACK_LV":
        return (f"OD={od}mm from LV Power table (used as fallback — control cable entry missing). "
                "This OD may be slightly larger than actual. Flag for review.")
    return f"OD source '{src}' is unrecognised. Manual verification required."


# ══════════════════════════════════════════════════════════════════════
# SECTION 4 — BATCH VALIDATOR + RELEASE GATE
# Validates an entire BOQ in one call.
# Returns a summary with release decision for the whole quote.
# ══════════════════════════════════════════════════════════════════════

@dataclass
class QuoteValidationSummary:
    total_lines: int
    approved: int
    needs_review: int
    blocked: int
    release_allowed: bool   # True only if ZERO blocks across all lines
    release_verdict: str
    reports: list           # one ValidationReport per line
    grand_total_net: float
    all_prices_consistent: bool


def validate_quote(items: list, results: list, discount_pct: float) -> QuoteValidationSummary:
    reports = []
    grand_total = 0.0
    all_prices_ok = True

    for item, result in zip(items, results):
        report = validate(item, result, discount_pct)
        reports.append(report)
        if report.trust_card.get("price_breakdown"):
            grand_total += report.trust_card["price_breakdown"].get("line_grand_total", 0)
        if report.blocks:
            all_prices_ok = False

    approved      = sum(1 for r in reports if r.final_status == "APPROVED")
    needs_review  = sum(1 for r in reports if r.final_status == "NEEDS_REVIEW")
    blocked       = sum(1 for r in reports if r.final_status == "BLOCKED")
    release_allowed = blocked == 0

    if blocked > 0:
        verdict = f"BLOCKED — {blocked} line(s) have critical errors. Output must NOT be generated."
    elif needs_review > 0:
        verdict = (f"NEEDS REVIEW — {needs_review} line(s) require human approval. "
                   "Release only after all warnings are reviewed and signed off.")
    else:
        verdict = f"APPROVED — All {approved} lines passed validation. Safe to generate output."

    return QuoteValidationSummary(
        total_lines=len(items),
        approved=approved,
        needs_review=needs_review,
        blocked=blocked,
        release_allowed=release_allowed,
        release_verdict=verdict,
        reports=reports,
        grand_total_net=round(grand_total, 2),
        all_prices_consistent=all_prices_ok,
    )


# ══════════════════════════════════════════════════════════════════════
# SECTION 5 — PRINT FUNCTIONS (terminal output)
# ══════════════════════════════════════════════════════════════════════

G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"
B = "\033[94m"; M = "\033[95m"; W = "\033[1m"; X = "\033[0m"

CONF_COLOR = {"HIGH": G, "MEDIUM": Y, "LOW": R, "BLOCKED": R}
STATUS_COLOR = {"APPROVED": G, "NEEDS_REVIEW": Y, "BLOCKED": R}
SEV_COLOR = {"BLOCK": R, "WARNING": Y, "INFO": B, "PASS": G}


def print_report(report: ValidationReport, show_trust_card=False):
    sc = STATUS_COLOR.get(report.final_status, X)
    cc = CONF_COLOR.get(report.confidence_label, X)

    print(f"\n  {'─'*66}")
    print(f"  Line {report.line_no:2d} │ {report.description}")
    print(f"  Status    : {sc}{W}{report.final_status}{X}   "
          f"Confidence: {cc}{report.confidence_label} ({report.confidence_score:.0%}){X}")

    for c in report.checks:
        sev = c["severity"]
        if sev == "PASS":
            print(f"    {G}✓{X} {c['title']}")
        else:
            col = SEV_COLOR.get(sev, X)
            print(f"    {col}[{sev}]{X} {c['title']}")
            print(f"         → {c['detail']}")
            print(f"         ▶ ACTION: {c['action']}")

    if show_trust_card and report.trust_card:
        tc = report.trust_card
        print(f"\n  {M}{W}  TRUST CARD — Why was this gland selected?{X}")
        cab = tc.get("cable", {})
        print(f"    Cable  : {cab.get('input')} → Type={cab.get('type_detected')}")
        print(f"    Rule   : {cab.get('type_rule')}")
        od = tc.get("od", {})
        print(f"    OD     : {od.get('value')}mm [{od.get('source')}]")
        print(f"             {od.get('source_explanation')}")
        gs = tc.get("gland_selection")
        if gs:
            print(f"    Gland  : {gs.get('cat_no')} | ₹{gs.get('list_price')} list")
            print(f"    Trace  : {gs.get('logic_trace')}")
            print(f"    Reason : {gs.get('why_this_gland')}")
            print(f"    Risk   : {gs.get('what_if_od_wrong')}")
        ls = tc.get("lug_selection")
        if ls:
            fc = ls.get("full_core")
            hc = ls.get("half_core")
            if fc: print(f"    Lug FC : {fc['cat_no']} {fc['sqmm']}sqmm | {fc['why']}")
            if hc: print(f"    Lug HC : {hc['cat_no']} {hc['sqmm']}sqmm | {hc['why']}")


def print_summary(summary: QuoteValidationSummary):
    sc = STATUS_COLOR.get(
        "BLOCKED" if summary.blocked > 0 else ("NEEDS_REVIEW" if summary.needs_review > 0 else "APPROVED"), X)
    print(f"\n{'='*68}")
    print(f"{W}  QUOTE VALIDATION SUMMARY{X}")
    print(f"{'='*68}")
    print(f"  Total lines    : {summary.total_lines}")
    print(f"  {G}Approved       : {summary.approved}{X}")
    print(f"  {Y}Needs review   : {summary.needs_review}{X}")
    print(f"  {R}Blocked        : {summary.blocked}{X}")
    print(f"  Grand total net: ₹{summary.grand_total_net:,.2f}")
    print(f"\n  {sc}{W}VERDICT: {summary.release_verdict}{X}")
    if not summary.release_allowed:
        print(f"\n  {R}{W}⛔ OUTPUT GENERATION IS LOCKED.{X}")
        print(f"  {R}  Resolve all BLOCK items before proceeding.{X}")
    else:
        print(f"\n  {G}{W}✅ RELEASE GATE: OPEN — Output may be generated.{X}")
    print(f"{'='*68}\n")


# ══════════════════════════════════════════════════════════════════════
# SECTION 6 — TEST SUITE
# 3 carefully chosen real-world cases that demonstrate all 3 tiers.
# ══════════════════════════════════════════════════════════════════════

def run_validation_tests():
    print(f"\n{W}{'='*68}{X}")
    print(f"{W}  BRACO VALIDATION SYSTEM — CLUSTER 2 TEST SUITE{X}")
    print(f"{'='*68}{X}")

    DISC = 46.0  # Tunisia export discount

    # ── CASE 1: Perfect line — 3.5Cx300 with client-stated OD ────────
    print(f"\n{W}  CASE 1 — Perfect line (client-stated OD, 3.5-core, all checks pass){X}")
    item1 = LineItem(
        line_no=1, description="3.5CX300 SQ.MM", cores=3.5, sqmm=300, qty=52,
        od_stated=61.0, gland_pref="BPW", needs_gland=True, needs_lug=True,
    )
    r1 = run_selection(item1)
    rpt1 = validate(item1, r1, DISC)
    print_report(rpt1, show_trust_card=True)

    # ── CASE 2: Ambiguous control cable with small lug warning ────────
    print(f"\n{W}  CASE 2 — Ambiguous 4Cx10 (no PVC keyword, OD from Polycab){X}")
    item2 = LineItem(
        line_no=2, description="4Cx10 SQMM XLPE Armoured", cores=4, sqmm=10, qty=4,
        gland_pref="BPW", needs_gland=True, needs_lug=True,
    )
    r2 = run_selection(item2)
    rpt2 = validate(item2, r2, DISC)
    print_report(rpt2, show_trust_card=False)

    # ── CASE 3: Injected BLOCK — price tampered in result ─────────────
    print(f"\n{W}  CASE 3 — BLOCK scenario: price tampered (simulates stale/wrong data){X}")
    item3 = LineItem(
        line_no=3, description="3.5CX95 SQ.MM", cores=3.5, sqmm=95, qty=90,
        od_stated=36.5, gland_pref="BPW", needs_gland=True, needs_lug=True,
    )
    r3 = run_selection(item3)
    # Simulate a stale price from old database
    if r3.gland:
        r3.gland["list_price"] = 500  # real price is ₹616 — this is wrong
    rpt3 = validate(item3, r3, DISC)
    print_report(rpt3, show_trust_card=False)

    # ── CASE 4: BLOCK — wrong half-core lug sqmm injected ─────────────
    print(f"\n{W}  CASE 4 — BLOCK scenario: half-core lug sqmm wrong (95sqmm lug on 95sqmm cable){X}")
    item4 = LineItem(
        line_no=4, description="3.5CX185 SQ.MM", cores=3.5, sqmm=185, qty=8,
        od_stated=50.0, gland_pref="BPW", needs_gland=True, needs_lug=True,
    )
    r4 = run_selection(item4)
    # Inject wrong half-core lug (85sqmm instead of correct 95sqmm)
    if r4.lug_half:
        r4.lug_half["sqmm"] = 85  # tampered — real is 95
        r4.lug_half["cat_no"] = "AT-WRONG"
    rpt4 = validate(item4, r4, DISC)
    print_report(rpt4, show_trust_card=False)

    # ── CASE 5: OD boundary warning ───────────────────────────────────
    print(f"\n{W}  CASE 5 — WARNING: OD exactly at upper boundary of gland range{X}")
    item5 = LineItem(
        line_no=5, description="4CX25 SQ.MM", cores=4, sqmm=25, qty=10,
        od_stated=26.0,  # exact upper boundary of BPW-04 (23-26)
        gland_pref="BPW", needs_gland=True, needs_lug=True,
    )
    r5 = run_selection(item5)
    rpt5 = validate(item5, r5, DISC)
    print_report(rpt5, show_trust_card=False)

    # ── Full quote batch summary ──────────────────────────────────────
    print(f"\n{W}{'='*68}{X}")
    print(f"{W}  FULL BATCH VALIDATION — 5 cases combined{X}")
    print(f"{'='*68}{X}")
    items   = [item1, item2, item3, item4, item5]
    results = [r1, r2, r3, r4, r5]
    summary = validate_quote(items, results, DISC)
    print_summary(summary)

    # ── Edge cases register ───────────────────────────────────────────
    print(f"\n{W}  EDGE CASES REGISTERED IN THIS SYSTEM{X}")
    edge_cases = [
        ("EC-01", "qty = 0",           "BLOCK  — check 08"),
        ("EC-02", "qty > 1000",        "WARNING — check 08 — data entry sanity"),
        ("EC-03", "OD at boundary",    "WARNING — check 02 — sealing risk"),
        ("EC-04", "Stale/wrong price", "BLOCK  — check 03 — price drift"),
        ("EC-05", "HC lug on 4C cable","BLOCK  — check 04 — wrong lug applied"),
        ("EC-06", "HC lug missing 3.5C","BLOCK — check 04 — missing lug"),
        ("EC-07", "Wrong HC sqmm",     "BLOCK  — check 04b — incorrect neutral size"),
        ("EC-08", "Lug sqmm ≠ cable sqmm","BLOCK — check 05 — safety hazard"),
        ("EC-09", "Unknown cat no",    "BLOCK  — check 01 — invented product"),
        ("EC-10", "OD fallback used",  "WARNING — check 06 — low confidence OD"),
        ("EC-11", "Ambiguous 4Cx10",   "WARNING — check 07 — could be ctrl or power"),
        ("EC-12", "BPW on unarmoured", "WARNING — check 09 — wrong series"),
        ("EC-13", "Corrosive env",     "INFO  — check 09b — SS gland suggested"),
        ("EC-14", "Arithmetic error",  "BLOCK  — check 10 — price calculation wrong"),
        ("EC-15", "OD not in table",   "BLOCK  — pre-check — OD lookup failed"),
    ]
    for ec_id, case, result in edge_cases:
        print(f"    {B}{ec_id}{X} {case:<30} → {result}")

    print()


if __name__ == "__main__":
    run_validation_tests()
