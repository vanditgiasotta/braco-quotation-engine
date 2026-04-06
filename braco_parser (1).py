"""
Braco Input Parser — Cluster 2 Part 2
Flow: File → Extract → Normalise → Deterministic → AI (uncertain only) → Review → LineItem[]
"""
import re, json, sys, os
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from braco_engine import LineItem

# ── Failure Point Registry ────────────────────────────────────────────
FAILURE_POINTS = {
    "FP-01": ("sqmm notation",   "Sqmm./Sq.mm/mm²/SQ.MM → normalise to number only"),
    "FP-02": ("cores notation",  "3.5C/3.5Cx/3.5 Core x/4Px → normalise, 4P→4C flag"),
    "FP-03": ("section headers", "LV Power/Control Glands/Control Lugs → sets needs_gland/lug"),
    "FP-04": ("multi-sheet agg", "4 sheets, same spec, different qty → sum quantities"),
    "FP-05": ("conductor miss",  "No CU/AL stated → default CU + warn"),
    "FP-06": ("gland vs lug",    "Same cable in two sections → needs_gland vs needs_lug"),
    "FP-07": ("4Px paired",      "4Px = 4-pair ≠ 4C, but use 4C for gland OD → warn"),
    "FP-08": ("project header",  "Row 0 = project ref, not a cable → skip"),
    "FP-09": ("OD detection",    "OD=36.5 / (36.5mm) / O.D. 36.5 → extract before AI"),
    "FP-10": ("non-ASCII space", "\\xa0 breaks string matching → strip before any op"),
}

# ── NORMALISER ────────────────────────────────────────────────────────
def normalise_text(raw: str) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    t = raw.replace('\xa0',' ').replace('\u200b','').replace('\u00a0',' ')
    t = re.sub(r'[ \t]+',' ', t).strip()
    # sqmm
    t = re.sub(r'mm\s*[²2]','sqmm', t, flags=re.IGNORECASE)
    t = re.sub(r'sq\.?\s*mm\.?','sqmm', t, flags=re.IGNORECASE)
    t = re.sub(r'sqmm\.','sqmm', t, flags=re.IGNORECASE)
    # cores (order matters)
    t = re.sub(r'(\d+\.?\d*)\s*[Cc][Oo][Rr][Ee][Ss]?\s*[Xx]?\s*', r'\1Cx', t)
    t = re.sub(r'(\d+\.?\d*)\s*[Cc]\s+[Xx]\s+', r'\1Cx', t)
    t = re.sub(r'(\d+\.?\d*)\s*[Cc]\s+', r'\1Cx', t)
    # 4P/4Px BEFORE sqmm normalisation — fixes '4Px1.5 Sq.mm' edge case
    t = re.sub(r'(\d+)\s*[Pp][Xx]\s*(\d)', r'\1Cx\2', t)
    t = re.sub(r'(\d+)\s*[Pp][Xx]?\s+', r'\1Cx', t)
    # conductor
    t = re.sub(r'\bCopper\b','CU', t, flags=re.IGNORECASE)
    t = re.sub(r'\bAluminiu?m\b','AL', t, flags=re.IGNORECASE)
    return t.strip()


def extract_cores_sqmm(text: str):
    norm = normalise_text(text)
    m = re.search(r'(\d+\.?\d*)[Cc][Xx]?\s*(\d+\.?\d*)\s*sqmm', norm, re.IGNORECASE)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    return None


def extract_od(text: str):
    for pat in [r'[Oo]\.?[Dd]\.?\s*[=:]\s*(\d+\.?\d*)',
                r'[Oo]\.?[Dd]\.?\s+(\d+\.?\d*)\s*mm',
                r'\((\d+\.?\d*)\s*mm\)']:
        m = re.search(pat, text)
        if m:
            try: return float(m.group(1))
            except: pass
    return None


def detect_section_type(header: str):
    t = header.upper().strip()
    if 'LV POWER' in t and 'GLAND' in t:
        return {"section_name":"LV Power Cable Glands","needs_gland":True,"needs_lug":False,"cable_category":"LV_POWER"}
    if 'CONTROL' in t and 'GLAND' in t:
        return {"section_name":"Control Cable Glands","needs_gland":True,"needs_lug":False,"cable_category":"CONTROL"}
    if 'CONTROL' in t and 'LUG' in t:
        return {"section_name":"Control Cable Lugs","needs_gland":False,"needs_lug":True,"cable_category":"CONTROL"}
    if 'HT' in t and 'GLAND' in t:
        return {"section_name":"HT Cable Glands","needs_gland":True,"needs_lug":False,"cable_category":"HT_XLPE"}
    if 'LUG' in t:
        return {"section_name":"Cable Lugs","needs_gland":False,"needs_lug":True,"cable_category":"LV_POWER"}
    if 'TERMINAT' in t:
        return {"section_name":"LT Cable Termination","needs_gland":True,"needs_lug":True,"cable_category":"LV_POWER"}
    return None


def is_section_header(vals: list):
    if len(vals) < 2: return None
    col0, col1 = str(vals[0]).upper(), str(vals[1])
    if 'SR' in col0 and any(k in col1.upper() for k in
            ['GLAND','LUG','CABLE','POWER','CONTROL','HT','TERMINAT']):
        return col1.strip()
    return None


def is_project_header(text: str) -> bool:
    t = text.upper()
    return 'BOQ' in t or ('GLANDS' in t and 'LUGS' in t and len(text) > 20)


# ── RAW LINE ─────────────────────────────────────────────────────────
@dataclass
class RawLine:
    sheet_name: str
    row_idx: int
    sr_no: str
    description_raw: str
    description_norm: str
    qty_raw: str
    qty: Optional[int]
    section: str
    needs_gland: bool
    needs_lug: bool
    cable_category: str
    od_stated: Optional[float]
    is_4P_type: bool
    confidence_pre: float
    confidence_note: str


# ── EXCEL EXTRACTOR ───────────────────────────────────────────────────
def extract_from_excel(filepath: str, aggregate_sheets: bool = True) -> list:
    xl = pd.read_excel(filepath, sheet_name=None, header=None, dtype=str)
    raw_lines = []

    for sheet_name, df in xl.items():
        current_section = {
            "section_name":"LV Power Cable Glands",
            "needs_gland":True,"needs_lug":False,"cable_category":"LV_POWER"
        }
        for row_idx, row in df.iterrows():
            vals = [str(v).strip() if pd.notna(v) else '' for v in row]
            if all(v == '' or v.lower() == 'nan' for v in vals):
                continue
            if len(vals) > 0 and is_project_header(vals[0]):
                continue

            hdr = is_section_header(vals)
            if hdr:
                sec = detect_section_type(hdr)
                if sec:
                    current_section = sec
                continue

            if len(vals) > 1 and 'QTY' in vals[1].upper():
                continue
            if len(vals) < 3:
                continue

            sr_no = vals[0]
            try: float(sr_no)
            except: continue

            desc_raw = vals[1].strip()
            qty_raw  = vals[2].strip()
            if not desc_raw or desc_raw.lower() == 'nan':
                continue

            desc_norm = normalise_text(desc_raw)
            is_4p = bool(re.search(r'\d+\s*[Pp][Xx]?\s+', desc_raw))
            od = extract_od(desc_raw)

            qty = None
            try: qty = int(float(qty_raw.replace(',','')))
            except: pass

            cs = extract_cores_sqmm(desc_norm)
            conf = 0.95 if cs else 0.40
            note = f"Deterministic: {cs[0]}C×{cs[1]}sqmm" if cs else "Needs AI parsing"
            if qty is None: conf -= 0.30; note += " | MISSING QTY"
            if is_4p: conf -= 0.10; note += " | 4Px notation"

            raw_lines.append(RawLine(
                sheet_name=sheet_name, row_idx=row_idx, sr_no=sr_no,
                description_raw=desc_raw, description_norm=desc_norm,
                qty_raw=qty_raw, qty=qty,
                section=current_section["section_name"],
                needs_gland=current_section["needs_gland"],
                needs_lug=current_section["needs_lug"],
                cable_category=current_section["cable_category"],
                od_stated=od, is_4P_type=is_4p,
                confidence_pre=round(max(0.0, conf), 2),
                confidence_note=note,
            ))

    if aggregate_sheets:
        from collections import defaultdict
        buckets = defaultdict(list)
        for line in raw_lines:
            key = (line.description_norm, line.section, line.needs_gland, line.needs_lug)
            buckets[key].append(line)

        merged = []
        for key, group in buckets.items():
            base = group[0]
            total_qty = sum(l.qty for l in group if l.qty is not None)
            sheets = list({l.sheet_name for l in group})
            merged.append(RawLine(
                sheet_name=", ".join(sheets), row_idx=base.row_idx,
                sr_no=base.sr_no, description_raw=base.description_raw,
                description_norm=base.description_norm,
                qty_raw=str(total_qty), qty=total_qty,
                section=base.section, needs_gland=base.needs_gland,
                needs_lug=base.needs_lug, cable_category=base.cable_category,
                od_stated=base.od_stated, is_4P_type=base.is_4P_type,
                confidence_pre=base.confidence_pre,
                confidence_note=base.confidence_note + f" | {len(sheets)} sheets aggregated",
            ))
        return merged

    return raw_lines


# ── PARSED LINE ───────────────────────────────────────────────────────
@dataclass
class ParsedLine:
    line_no: int
    description_raw: str
    cores: Optional[float]
    sqmm: Optional[float]
    conductor: str
    qty: Optional[int]
    od_stated: Optional[float]
    needs_gland: bool
    needs_lug: bool
    section: str
    cable_category: str
    is_paired: bool
    half_core_required: bool
    confidence: float
    confidence_note: str
    parse_source: str
    warnings: list
    sheet_name: str


# ── AI PARSER PROMPT ──────────────────────────────────────────────────
PARSER_SYSTEM_PROMPT = """You are a specialist data extraction engine for Braco Electricals cable gland quotations.
Your ONLY job: extract cable specs from inquiry lines. Do NOT select products. Do NOT guess.

NORMALISATION:
- sqmm: mm²/mm2/Sq.mm/SQ.MM → just the number
- cores: 3.5C/3.5Cx/3.5Core x → cores=3.5 | 4Px → cores=4 + is_paired=true
- conductor: CU/Copper → "CU" | AL/Aluminium → "AL" | not stated → "CU" + conductor_assumed=true

CABLE TYPE (in order):
- sqmm<=2.5 AND cores>=2 → CONTROL
- sqmm<=6 AND cores>=5 → CONTROL
- "PVC" in description AND cores>=4 AND sqmm<=10 → CONTROL
- else → LV_POWER

HALF-CORE: cores==3.5 → half_core_required=true, else false

OD: scan for "OD=36.5", "OD 36.5mm", "(36.5mm)", "O.D. 36.5" → od_stated=float or null

CONFIDENCE: start 1.0, deduct: -0.05 conductor assumed, -0.10 is_paired, -0.25 qty missing, -0.30 cannot determine cores/sqmm

OUTPUT: ONLY valid JSON array. First char [, last char ]. No markdown. No preamble.
Each object:
{"description_raw":"","cores":null,"sqmm":null,"conductor":"CU","conductor_assumed":false,
"cable_type":null,"od_stated":null,"is_paired":false,"half_core_required":false,
"needs_gland":true,"needs_lug":false,"qty":null,"confidence":1.0,"confidence_note":""}"""


def call_ai_parser(raw_lines: list) -> list:
    try:
        import anthropic
        client = anthropic.Anthropic()
        items = [{"idx":i,"description_raw":r.description_raw,
                  "section_context":r.section,"qty_raw":r.qty_raw}
                 for i,r in enumerate(raw_lines)]
        msg = "Parse these cable inquiry lines per the system instructions:\n\n" + json.dumps(items, indent=2)
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=4000,
            system=PARSER_SYSTEM_PROMPT,
            messages=[{"role":"user","content":msg}]
        )
        txt = resp.content[0].text.strip()
        if txt.startswith('['): return json.loads(txt)
        m = re.search(r'\[.*\]', txt, re.DOTALL)
        if m: return json.loads(m.group())
        return []
    except Exception as e:
        print(f"  [AI] {e}")
        return []


def _detect_conductor(text: str):
    t = text.upper()
    if 'CU' in t or 'COPPER' in t: return "CU", 1.0
    if 'AL' in t or 'ALUMIN' in t: return "AL", 1.0
    return "CU", 0.80


def _make_failed(line_no, raw) -> ParsedLine:
    return ParsedLine(
        line_no=line_no, description_raw=raw.description_raw,
        cores=None, sqmm=None, conductor="CU", qty=raw.qty, od_stated=None,
        needs_gland=raw.needs_gland, needs_lug=raw.needs_lug,
        section=raw.section, cable_category=raw.cable_category,
        is_paired=raw.is_4P_type, half_core_required=False,
        confidence=0.0, confidence_note="FAILED: " + raw.confidence_note,
        parse_source="FAILED", warnings=[f"Cannot parse: {raw.description_raw!r}"],
        sheet_name=raw.sheet_name,
    )


# ── MAIN PIPELINE ─────────────────────────────────────────────────────
CONF_AUTO   = 0.85
CONF_REVIEW = 0.60


def parse_excel_file(filepath: str, use_ai: bool = True, aggregate_sheets: bool = True) -> list:
    print(f"\n  [PARSER] Reading: {os.path.basename(filepath)}")
    raw_lines = extract_from_excel(filepath, aggregate_sheets)
    print(f"  [PARSER] {len(raw_lines)} unique cable specs extracted")

    parsed = []
    uncertain = []

    for i, raw in enumerate(raw_lines):
        line_no = i + 1
        cs = extract_cores_sqmm(raw.description_norm)
        if cs and raw.qty is not None and raw.confidence_pre >= CONF_REVIEW:
            cores, sqmm = cs
            if raw.is_4P_type: cores = 4.0
            conductor, cc = _detect_conductor(raw.description_norm)
            warnings = []
            if cc < 1.0: warnings.append(f"Conductor not stated — defaulted to {conductor}")
            if raw.is_4P_type: warnings.append("4Px notation → treated as 4C for OD. Verify with client.")
            conf = raw.confidence_pre - (0.05 if cc < 1.0 else 0)
            parsed.append(ParsedLine(
                line_no=line_no, description_raw=raw.description_raw,
                cores=cores, sqmm=sqmm, conductor=conductor, qty=raw.qty,
                od_stated=raw.od_stated, needs_gland=raw.needs_gland,
                needs_lug=raw.needs_lug, section=raw.section,
                cable_category=raw.cable_category, is_paired=raw.is_4P_type,
                half_core_required=(cores == 3.5),
                confidence=round(max(0, min(1, conf)), 2),
                confidence_note=raw.confidence_note,
                parse_source="DETERMINISTIC", warnings=warnings,
                sheet_name=raw.sheet_name,
            ))
        else:
            uncertain.append((line_no, raw))

    if uncertain and use_ai:
        print(f"  [PARSER] {len(uncertain)} uncertain lines → AI parser")
        ai_raw = [r for _, r in uncertain]
        ai_res = call_ai_parser(ai_raw)
        for (line_no, raw), res in zip(uncertain, ai_res if ai_res else [None]*len(uncertain)):
            if not res:
                parsed.append(_make_failed(line_no, raw)); continue
            cores = res.get("cores")
            sqmm  = res.get("sqmm")
            if res.get("is_paired"): cores = 4.0
            parsed.append(ParsedLine(
                line_no=line_no, description_raw=raw.description_raw,
                cores=cores, sqmm=sqmm,
                conductor=res.get("conductor","CU"),
                qty=res.get("qty") or raw.qty,
                od_stated=res.get("od_stated") or raw.od_stated,
                needs_gland=res.get("needs_gland", raw.needs_gland),
                needs_lug=res.get("needs_lug", raw.needs_lug),
                section=raw.section, cable_category=res.get("cable_type", raw.cable_category),
                is_paired=res.get("is_paired", False),
                half_core_required=(cores == 3.5),
                confidence=float(res.get("confidence",0)),
                confidence_note=res.get("confidence_note","AI"),
                parse_source="AI", warnings=[], sheet_name=raw.sheet_name,
            ))
    elif uncertain:
        for line_no, raw in uncertain:
            parsed.append(_make_failed(line_no, raw))

    parsed.sort(key=lambda x: x.line_no)
    return parsed


def generate_review_table(parsed: list) -> dict:
    auto, review, failed = [], [], []
    for p in parsed:
        entry = {
            "line_no":p.line_no, "description":p.description_raw,
            "cores":p.cores, "sqmm":p.sqmm, "conductor":p.conductor,
            "qty":p.qty, "od_stated":p.od_stated, "section":p.section,
            "needs_gland":p.needs_gland, "needs_lug":p.needs_lug,
            "confidence":p.confidence, "parse_source":p.parse_source,
            "warnings":p.warnings, "note":p.confidence_note,
            "sheet":p.sheet_name,
        }
        if p.confidence >= CONF_AUTO and not p.warnings:
            auto.append(entry)
        elif p.confidence >= CONF_REVIEW or (p.cores and p.sqmm and p.qty):
            review.append(entry)
        else:
            failed.append(entry)

    return {
        "auto_approved": auto, "needs_review": review, "failed": failed,
        "summary": {
            "total": len(parsed),
            "auto_approved": len(auto),
            "needs_review": len(review),
            "failed": len(failed),
            "proceed_allowed": len(failed) == 0,
        }
    }


def parsed_line_to_line_item(p: ParsedLine) -> Optional[LineItem]:
    if p.cores is None or p.sqmm is None or p.qty is None:
        return None
    return LineItem(
        line_no=p.line_no, description=p.description_raw,
        cores=p.cores, sqmm=p.sqmm, qty=p.qty,
        conductor=p.conductor, od_stated=p.od_stated,
        gland_pref="BPW", needs_gland=p.needs_gland,
        needs_lug=p.needs_lug, section=p.section,
    )


# ── TEST SUITE ────────────────────────────────────────────────────────
G="\033[92m"; Y="\033[93m"; R="\033[91m"; B="\033[94m"; W="\033[1m"; X="\033[0m"

def run_parser_tests():
    print(f"\n{W}{'='*68}{X}")
    print(f"{W}  BRACO PARSER v1.0 — CLUSTER 2 PART 2 — TEST SUITE{X}")
    print(f"{'='*68}{X}")

    # Test A: Normaliser
    print(f"\n{W}  A — Normaliser: all real-world variation patterns{X}\n")
    tests = [
        ("3.5C x 300 Sqmm. Cu",     3.5, 300.0),
        ("4Cx10 Sq. mm, CU PVC",    4.0,  10.0),
        ("4Px1.5 Sq. mm, CU PVC",   4.0,   1.5),
        ("7Cx2.5 Sq. mm, CU PVC",   7.0,   2.5),
        ("27Cx2.5 Sq. mm, CU PVC", 27.0,   2.5),
        ("12Cx2.5 Sq. mm, CU PVC", 12.0,   2.5),
        ("19Cx2.5 Sq. mm, CU PVC", 19.0,   2.5),
        ("4C x 2.5 Sqmm. Cu.",      4.0,   2.5),
        ("1C x 95 Sqmm. Cu",        1.0,  95.0),
        ("2C x 4 Sqmm. Cu.",        2.0,   4.0),
        ("4C\xa0x\xa010 mm²",       4.0,  10.0),
        ("3.5 Core x 240 sqmm",     3.5, 240.0),
        ("3.5core x 185 sq mm",     3.5, 185.0),
        ("4C x 50 Sqmm. Cu.",       4.0,  50.0),
    ]
    ok = True
    for raw, ec, es in tests:
        norm = normalise_text(raw)
        cs = extract_cores_sqmm(norm)
        if cs and cs[0] == ec and cs[1] == es:
            print(f"  {G}✓{X} {raw[:42]:<44} → {cs[0]}C×{cs[1]}")
        else:
            print(f"  {R}✗{X} {raw[:42]:<44} → {cs} (exp {ec}C×{es})")
            ok = False
    print(f"\n  Normaliser: {G+'ALL PASS' if ok else R+'FAILURES'}{X}")

    # Test B: Section header detection
    print(f"\n{W}  B — Section header detection{X}\n")
    sec_tests = [
        (["SR. NO.", "LV Power Cable Glands",        "QTY (NOS)"], "LV Power Cable Glands"),
        (["SR. NO.", "0.6/1kV CONTROL CABLE GLANDS", "QTY (NOS)"], "Control Cable Glands"),
        (["SR. NO.", "0.6/1kV CONTROL CABLE LUGS",   "QTY (NOS)"], "Control Cable Lugs"),
        (["1",       "4Cx10 Sq. mm, CU PVC",         "143"],        None),
        (["SR. NO.", "LT Cable Termination",          "QTY"],        "LT Cable Termination"),
    ]
    for vals, expected in sec_tests:
        hdr = is_section_header(vals)
        sec = detect_section_type(hdr) if hdr else None
        got = sec["section_name"] if sec else None
        ok2 = got == expected
        print(f"  {G if ok2 else R}{'✓' if ok2 else '✗'}{X} {vals[1][:44]:<46} → {got or 'not a header'}")

    # Test C: Full extraction
    print(f"\n{W}  C — Full Excel extraction: Tunisia BOQ (4 sheets, aggregated){X}\n")
    boq = "/mnt/project/BOQ_Glands__Lugs.xlsx"
    if not os.path.exists(boq):
        print(f"  {Y}[SKIP] file not found{X}"); return

    parsed = parse_excel_file(boq, use_ai=False, aggregate_sheets=True)
    review = generate_review_table(parsed)

    s = review["summary"]
    print(f"  Total        : {s['total']}")
    print(f"  {G}Auto-approved: {s['auto_approved']}{X}")
    print(f"  {Y}Needs review : {s['needs_review']}{X}")
    print(f"  {R}Failed       : {s['failed']}{X}")
    print(f"  Proceed      : {'YES ✓' if s['proceed_allowed'] else 'NO ✗'}")

    print(f"\n  {'#':<4} {'Section':<26} {'Desc':<32} {'C':>4} {'sqmm':>6} {'Qty':>6} {'Cf':>5} {'Src'}")
    print(f"  {'─'*90}")

    for bname, bucket in [("AUTO-APPROVED",review["auto_approved"]),
                           ("NEEDS REVIEW", review["needs_review"]),
                           ("FAILED",       review["failed"])]:
        if not bucket: continue
        col = G if bname=="AUTO-APPROVED" else (Y if "REVIEW" in bname else R)
        print(f"\n  {col}{W}[{bname}]{X}")
        for e in bucket:
            cores_s = f"{e['cores']:.1f}" if e['cores'] else "?"
            sqmm_s  = str(e['sqmm'])       if e['sqmm']  else "?"
            qty_s   = str(e['qty'])        if e['qty']   else "?"
            c_col   = G if e['confidence']>=0.85 else (Y if e['confidence']>=0.60 else R)
            print(f"  {c_col}L{e['line_no']:02d}{X}  {e['section'][:24]:<26} {e['description'][:30]:<32} "
                  f"{cores_s:>4} {sqmm_s:>6} {qty_s:>6} {c_col}{e['confidence']:>4.0%}{X} {e['parse_source']}")
            for w in e.get("warnings",[]):
                print(f"       {Y}↳ {w}{X}")

    # Test D: LineItem conversion
    print(f"\n{W}  D — LineItem conversion (5 approved lines){X}\n")
    for p in [x for x in parsed if x.confidence>=CONF_REVIEW and x.cores and x.sqmm][:5]:
        item = parsed_line_to_line_item(p)
        if item:
            print(f"  {G}✓{X} L{item.line_no:02d}: {item.cores}C×{item.sqmm}sqmm "
                  f"qty={item.qty} gland={item.needs_gland} lug={item.needs_lug}")

    # Test E: Edge cases
    print(f"\n{W}  E — Edge cases{X}\n")
    for raw, label in [
        ("4Px1.5 Sq. mm, CU PVC",    "4Px paired"),
        ("12Cx2.5\xa0Sq.\xa0mm",     "non-breaking spaces"),
        ("3.5 Core x 300 mm²",       "mm² + spaced 'Core x'"),
        ("4C x 50 Sqmm.",            "no conductor"),
        ("3.5core x 185 sq mm",      "lowercase core"),
    ]:
        norm = normalise_text(raw)
        cs   = extract_cores_sqmm(norm)
        cond,cc = _detect_conductor(norm)
        od   = extract_od(raw)
        is_4p = bool(re.search(r'\d+\s*[Pp][Xx]?\s+', raw))
        col = G if cs else R
        print(f"  {col}[{label}]{X}")
        print(f"     Raw  : {repr(raw[:55])}")
        print(f"     Norm : {repr(norm[:55])}")
        print(f"     → {cs}  cond={cond}({cc:.0%})  OD={od}  4P={is_4p}")

    # Failure points summary
    print(f"\n{W}  FAILURE POINTS DEFENDED BY THIS PARSER{X}\n")
    for fid, (name, fix) in FAILURE_POINTS.items():
        print(f"  {B}{fid}{X} {name:<22} → {fix}")

    print(f"\n{'='*68}\n")


if __name__ == "__main__":
    run_parser_tests()
