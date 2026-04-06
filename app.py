"""
Braco Quotation Engine — V1 UI
================================
Single-file Streamlit application that wraps the full pipeline:
  Upload → Parse → Select → Validate → Download

Run with:
  streamlit run app.py
"""

import sys, os, io, json, tempfile, traceback
from datetime import date
from pathlib import Path
from copy import deepcopy

import streamlit as st
import pandas as pd

# ── Pipeline imports ──────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from braco_parser import (
    parse_excel_file, generate_review_table, parsed_line_to_line_item
)
from braco_engine import run_selection, calculate_prices
from braco_validator import validate_quote
from braco_output import generate_quotation, QuoteConfig

# ══════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Braco Quotation Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════
# STYLE
# ══════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
/* Typography & base */
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

/* Header strip */
.braco-header {
    background: #0f2540;
    color: white;
    padding: 18px 28px 14px;
    border-radius: 10px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 14px;
}
.braco-header h1 {
    font-size: 1.45rem;
    font-weight: 600;
    margin: 0;
    letter-spacing: -0.3px;
}
.braco-header p {
    font-size: 0.82rem;
    margin: 2px 0 0;
    opacity: 0.65;
    font-weight: 300;
}

/* Status badges */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    font-family: 'DM Mono', monospace;
    letter-spacing: 0.3px;
}
.badge-ok      { background: #d1fae5; color: #065f46; }
.badge-warn    { background: #fef3c7; color: #92400e; }
.badge-block   { background: #fee2e2; color: #991b1b; }
.badge-info    { background: #dbeafe; color: #1e40af; }
.badge-pass    { background: #f0fdf4; color: #166534; }

/* Stat cards */
.stat-row {
    display: flex;
    gap: 14px;
    margin: 14px 0;
    flex-wrap: wrap;
}
.stat-card {
    flex: 1;
    min-width: 110px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 9px;
    padding: 14px 16px;
    text-align: center;
}
.stat-card .num {
    font-size: 1.8rem;
    font-weight: 600;
    color: #0f2540;
    font-family: 'DM Mono', monospace;
    line-height: 1.1;
}
.stat-card .lbl {
    font-size: 0.72rem;
    color: #64748b;
    margin-top: 4px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.stat-card.green .num { color: #059669; }
.stat-card.amber .num { color: #d97706; }
.stat-card.red   .num { color: #dc2626; }

/* Section label */
.section-label {
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #94a3b8;
    margin: 20px 0 8px;
}

/* Line card */
.line-card {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 9px;
    padding: 12px 16px;
    margin-bottom: 8px;
    border-left: 4px solid #e2e8f0;
}
.line-card.approved { border-left-color: #10b981; }
.line-card.review   { border-left-color: #f59e0b; }
.line-card.blocked  { border-left-color: #ef4444; }
.line-card .cable   { font-size: 0.88rem; font-weight: 500; color: #0f172a; }
.line-card .detail  { font-size: 0.78rem; color: #64748b; margin-top: 4px; font-family: 'DM Mono', monospace; }
.line-card .flags   { font-size: 0.75rem; color: #92400e; margin-top: 5px; background: #fef3c7; padding: 3px 8px; border-radius: 5px; display: inline-block; }

/* Release gate banner */
.gate-open {
    background: #d1fae5;
    border: 1px solid #6ee7b7;
    border-radius: 9px;
    padding: 14px 18px;
    color: #065f46;
    font-weight: 500;
    font-size: 0.88rem;
}
.gate-blocked {
    background: #fee2e2;
    border: 1px solid #fca5a5;
    border-radius: 9px;
    padding: 14px 18px;
    color: #991b1b;
    font-weight: 500;
    font-size: 0.88rem;
}

/* Divider */
.div-line {
    height: 1px;
    background: #e2e8f0;
    margin: 20px 0;
}

/* Override Streamlit button */
div.stButton > button {
    width: 100%;
    border-radius: 8px;
    font-family: 'DM Sans', sans-serif;
    font-weight: 500;
    font-size: 0.88rem;
    padding: 10px 18px;
}

/* Progress step indicators */
.step-row {
    display: flex;
    gap: 8px;
    align-items: center;
    margin: 10px 0;
    font-size: 0.82rem;
}
.step-dot {
    width: 22px; height: 22px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.72rem;
    font-weight: 700;
    flex-shrink: 0;
}
.step-dot.done    { background: #10b981; color: white; }
.step-dot.active  { background: #2563eb; color: white; }
.step-dot.pending { background: #e2e8f0; color: #94a3b8; }
.step-label       { color: #334155; font-weight: 400; }
.step-label.done  { color: #065f46; }
.step-label.pending { color: #94a3b8; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# SESSION STATE INIT
# ══════════════════════════════════════════════════════════════════════

def _init_state():
    defaults = {
        "stage": "upload",        # upload | parsed | validated | done
        "parsed_lines": None,
        "review_table": None,
        "items": None,
        "results": None,
        "val_summary": None,
        "output_bytes": None,
        "output_filename": None,
        "error": None,
        "parse_warnings": [],
        "uploaded_name": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

def _reset():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    _init_state()

# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def _status_badge(status: str) -> str:
    m = {"APPROVED": "badge-ok", "NEEDS_REVIEW": "badge-warn",
         "BLOCKED": "badge-block", "PASS": "badge-pass",
         "OK": "badge-ok", "WARNING": "badge-warn", "INFO": "badge-info"}
    cls = m.get(status, "badge-info")
    label = {"NEEDS_REVIEW": "REVIEW"}.get(status, status)
    return f'<span class="badge {cls}">{label}</span>'


def _step(num, label, state):
    cls = {"done": "done", "active": "active", "pending": "pending"}[state]
    icon = {"done": "✓", "active": str(num), "pending": str(num)}[state]
    return (
        f'<div class="step-row">'
        f'<span class="step-dot {cls}">{icon}</span>'
        f'<span class="step-label {cls}">{label}</span>'
        f'</div>'
    )


def _safe_run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"


# ══════════════════════════════════════════════════════════════════════
# SIDEBAR — QUOTE CONFIGURATION
# ══════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### ⚙ Quote Settings")
    st.markdown('<div class="div-line"></div>', unsafe_allow_html=True)

    quote_ref   = st.text_input("Quote Reference",  value="QT0000083")
    client_name = st.text_input("Client Name",      value="Client Name")
    project     = st.text_input("Project Name",     value="Project Reference")
    sec_label   = st.text_input("Section Label",    value="16.2")
    sec_title   = st.text_input("Section Title",    value="LT Cable Termination")
    discount    = st.number_input("Discount %", min_value=0.0, max_value=100.0, value=46.0, step=0.5)
    gen_by      = st.text_input("Generated By",     value="Sales Team")
    appr_by     = st.text_input("Approved By",      value="Director")
    is_export   = st.toggle("Export Order", value=False)
    use_ai      = st.toggle("AI Parser (for uncertain lines)", value=False,
                            help="Calls Claude API. Disable for offline use.")
    agg_sheets  = st.toggle("Aggregate Sheets", value=True,
                            help="Sum quantities across all sheets (multi-site BOQ)")

    st.markdown('<div class="div-line"></div>', unsafe_allow_html=True)

    sec_desc = st.text_area(
        "Section Description (optional)",
        value=(
            "1.1KV End Termination Double compression type Cable glands for 1.1kV grade, "
            "Aluminium conductor, XLPE/PVC insulated, armoured, FRLS PVC sheathed cables "
            "including Lugs, Glands etc."
        ),
        height=100,
    )

    if st.button("🔄 Reset / New Quote", use_container_width=True):
        _reset()
        st.rerun()

# ══════════════════════════════════════════════════════════════════════
# MAIN LAYOUT
# ══════════════════════════════════════════════════════════════════════

# Header
st.markdown("""
<div class="braco-header">
  <div>
    <h1>⚡ Braco Quotation Engine</h1>
    <p>Upload client inquiry → automatic selection → validated Excel quotation</p>
  </div>
</div>
""", unsafe_allow_html=True)

# Progress steps
stage = st.session_state.stage
step_states = {
    "upload":    ["active",  "pending", "pending", "pending"],
    "parsed":    ["done",    "active",  "pending", "pending"],
    "validated": ["done",    "done",    "active",  "pending"],
    "done":      ["done",    "done",    "done",    "active"],
}[stage]

steps_html = (
    _step(1, "Upload inquiry file",  step_states[0]) +
    _step(2, "Parse & review lines", step_states[1]) +
    _step(3, "Validate selections",  step_states[2]) +
    _step(4, "Download quotation",   step_states[3])
)
col_steps, col_spacer = st.columns([2, 3])
with col_steps:
    st.markdown(steps_html, unsafe_allow_html=True)

st.markdown('<div class="div-line"></div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# STAGE 1 — UPLOAD
# ══════════════════════════════════════════════════════════════════════

if stage == "upload":
    st.markdown('<div class="section-label">Step 1 — Upload Client Inquiry</div>', unsafe_allow_html=True)

    uploaded = st.file_uploader(
        "Drop the client BOQ here",
        type=["xlsx", "xls", "csv", "pdf", "png", "jpg", "jpeg"],
        help="Accepts Excel BOQ, CSV, PDF, or image of the inquiry",
        label_visibility="collapsed",
    )

    if uploaded:
        st.session_state.uploaded_name = uploaded.name

        col_info, col_btn = st.columns([3, 1])
        with col_info:
            ext = Path(uploaded.name).suffix.lower()
            size_kb = round(len(uploaded.getvalue()) / 1024, 1)
            st.markdown(
                f'📎 **{uploaded.name}** &nbsp;·&nbsp; {size_kb} KB &nbsp;·&nbsp; '
                f'{ext.upper()} format',
                unsafe_allow_html=True,
            )
        with col_btn:
            run_btn = st.button("▶ Parse File", type="primary", use_container_width=True)

        if run_btn:
            with st.spinner("Parsing inquiry…"):
                # Save to temp file (parser needs a path)
                suffix = Path(uploaded.name).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(uploaded.getvalue())
                    tmp_path = tmp.name

                try:
                    if suffix.lower() in (".xlsx", ".xls", ".csv"):
                        parsed_lines, err = _safe_run(
                            parse_excel_file,
                            tmp_path,
                            use_ai=use_ai,
                            aggregate_sheets=agg_sheets,
                        )
                    else:
                        st.error("PDF and image parsing requires the AI parser. Enable 'AI Parser' in the sidebar and re-upload.")
                        st.stop()

                    if err:
                        st.session_state.error = err
                        st.session_state.stage = "upload"
                    else:
                        review = generate_review_table(parsed_lines)
                        st.session_state.parsed_lines = parsed_lines
                        st.session_state.review_table = review
                        st.session_state.stage = "parsed"
                        st.session_state.error = None
                finally:
                    try: os.unlink(tmp_path)
                    except: pass

            st.rerun()

    else:
        # Demo hint
        st.info(
            "💡 **Supported formats:** Excel BOQ (.xlsx), CSV  \n"
            "The parser will aggregate quantities across multiple sheets automatically.",
            icon=None,
        )

# ══════════════════════════════════════════════════════════════════════
# STAGE 2 — PARSED REVIEW
# ══════════════════════════════════════════════════════════════════════

elif stage == "parsed":
    review = st.session_state.review_table
    s = review["summary"]

    st.markdown(f'<div class="section-label">Step 2 — Parsed Lines: {st.session_state.uploaded_name}</div>',
                unsafe_allow_html=True)

    # Stats
    st.markdown(f"""
    <div class="stat-row">
      <div class="stat-card"><div class="num">{s['total']}</div><div class="lbl">Total Lines</div></div>
      <div class="stat-card green"><div class="num">{s['auto_approved']}</div><div class="lbl">Auto-Approved</div></div>
      <div class="stat-card amber"><div class="num">{s['needs_review']}</div><div class="lbl">Needs Review</div></div>
      <div class="stat-card red"><div class="num">{s['failed']}</div><div class="lbl">Failed</div></div>
    </div>
    """, unsafe_allow_html=True)

    if s["failed"] > 0:
        st.warning(
            f"⚠ {s['failed']} line(s) could not be parsed. "
            "The engine will skip them. Check the source file for unusual formatting."
        )

    # Line-by-line preview table
    all_entries = (
        review["auto_approved"] +
        review["needs_review"] +
        review["failed"]
    )

    preview_data = []
    for e in all_entries:
        status = "APPROVED" if e in review["auto_approved"] else (
                 "REVIEW"   if e in review["needs_review"] else "FAILED")
        preview_data.append({
            "#":          e["line_no"],
            "Cable":      e["description"][:50],
            "Cores":      e["cores"],
            "sqmm":       e["sqmm"],
            "Qty":        e["qty"],
            "Section":    e["section"][:28],
            "Gland":      "✓" if e["needs_gland"] else "–",
            "Lug":        "✓" if e["needs_lug"]   else "–",
            "Confidence": f"{e['confidence']:.0%}",
            "Status":     status,
        })

    df_preview = pd.DataFrame(preview_data)
    st.dataframe(
        df_preview,
        use_container_width=True,
        hide_index=True,
        column_config={
            "#":      st.column_config.NumberColumn(width="small"),
            "Confidence": st.column_config.TextColumn(width="small"),
            "Status": st.column_config.TextColumn(width="medium"),
            "Gland":  st.column_config.TextColumn(width="small"),
            "Lug":    st.column_config.TextColumn(width="small"),
        }
    )

    # Warnings from parsing
    all_warnings = []
    for e in all_entries:
        for w in e.get("warnings", []):
            all_warnings.append(f"Line {e['line_no']}: {w}")
    if all_warnings:
        with st.expander(f"⚠ {len(all_warnings)} parsing warning(s)", expanded=False):
            for w in all_warnings:
                st.markdown(f"• {w}")

    st.markdown('<div class="div-line"></div>', unsafe_allow_html=True)

    col_back, col_run = st.columns([1, 2])
    with col_back:
        if st.button("← Back", use_container_width=True):
            _reset(); st.rerun()
    with col_run:
        proceed_disabled = s["total"] == 0 or (s["auto_approved"] + s["needs_review"]) == 0
        if st.button(
            "▶ Run Selection & Validation",
            type="primary",
            use_container_width=True,
            disabled=proceed_disabled,
        ):
            with st.spinner("Running selection engine and validation…"):
                # Convert parsed lines → LineItems (skip failed)
                parsed = st.session_state.parsed_lines
                items = []
                for p in parsed:
                    item = parsed_line_to_line_item(p)
                    if item:
                        items.append(item)

                if not items:
                    st.error("No valid lines to process. Check the source file.")
                    st.stop()

                # Run selection engine
                results = [run_selection(item) for item in items]

                # Run validation
                val_summary = validate_quote(items, results, discount)

                st.session_state.items = items
                st.session_state.results = results
                st.session_state.val_summary = val_summary
                st.session_state.stage = "validated"

            st.rerun()

# ══════════════════════════════════════════════════════════════════════
# STAGE 3 — VALIDATION RESULTS
# ══════════════════════════════════════════════════════════════════════

elif stage == "validated":
    summary   = st.session_state.val_summary
    items     = st.session_state.items
    results   = st.session_state.results

    st.markdown('<div class="section-label">Step 3 — Validation Results</div>', unsafe_allow_html=True)

    # Release gate banner
    if summary.release_allowed:
        st.markdown(
            f'<div class="gate-open">✅ &nbsp;<strong>Release Gate: OPEN</strong> &nbsp;—&nbsp; '
            f'All {summary.approved} lines approved'
            + (f', {summary.needs_review} with review notes' if summary.needs_review else '')
            + f'. Quotation may be generated.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="gate-blocked">🚫 &nbsp;<strong>Release Gate: BLOCKED</strong> &nbsp;—&nbsp; '
            f'{summary.blocked} line(s) have critical errors. '
            f'Resolve issues before generating output.</div>',
            unsafe_allow_html=True,
        )

    # Stats row
    st.markdown(f"""
    <div class="stat-row">
      <div class="stat-card green"><div class="num">{summary.approved}</div><div class="lbl">Approved</div></div>
      <div class="stat-card amber"><div class="num">{summary.needs_review}</div><div class="lbl">Needs Review</div></div>
      <div class="stat-card red"><div class="num">{summary.blocked}</div><div class="lbl">Blocked</div></div>
      <div class="stat-card"><div class="num">₹{summary.grand_total_net:,.0f}</div><div class="lbl">Net Total @{discount:.0f}%</div></div>
    </div>
    """, unsafe_allow_html=True)

    # Per-line validation cards
    status_map = {"APPROVED": "approved", "NEEDS_REVIEW": "review", "BLOCKED": "blocked"}
    report_by_line = {r.line_no: r for r in summary.reports}

   for i in range(min(len(items), len(results))):
    item = items[i]
    result = results[i]

    report = report_by_line.get(item.line_no)
    if not report:
        continue

        css_cls = status_map.get(report.final_status, "review")
        conf = f"{report.confidence_score:.0%}"

        gland_str = ""
        if result.gland:
            g = result.gland
            net = round(g["list_price"] * (1 - discount / 100), 2)
            gland_str = f"Gland: {g['cat_no']} &nbsp;·&nbsp; ₹{g['list_price']} list &nbsp;·&nbsp; ₹{net} net"

        lug_str = ""
        if result.lug_full:
            lf = result.lug_full
            net_f = round(lf["list_price"] * (1 - discount / 100), 2)
            lug_str += f"FC Lug: {lf['cat_no']} ₹{net_f}"
        if result.lug_half:
            lh = result.lug_half
            net_h = round(lh["list_price"] * (1 - discount / 100), 2)
            lug_str += f" &nbsp;·&nbsp; HC Lug: {lh['cat_no']} ₹{net_h}"

        od_str = f"OD: {result.od_used}mm [{result.od_source}]" if result.od_used else ""

        # Flags (non-PASS)
        flags = [c for c in report.checks if c["severity"] not in ("PASS",)]
        flag_html = ""
        for f in flags[:3]:  # show max 3 inline
            sev = f["severity"]
            cls = {"BLOCK": "badge-block", "WARNING": "badge-warn", "INFO": "badge-info"}.get(sev, "badge-info")
            flag_html += f'<span class="badge {cls}" style="margin-right:4px;">{sev}</span> {f["title"]}<br>'

        badge = _status_badge(report.final_status)

        st.markdown(f"""
        <div class="line-card {css_cls}">
          <div class="cable">
            {badge} &nbsp; <strong>L{item.line_no:02d}</strong> — {item.description}
            &nbsp;<span style="font-size:0.78rem;color:#94a3b8;font-family:'DM Mono',monospace;">
              Qty {item.qty} &nbsp;·&nbsp; Conf {conf}
            </span>
          </div>
          <div class="detail">
            {od_str}{"&nbsp;&nbsp;|&nbsp;&nbsp;" if od_str and gland_str else ""}{gland_str}
            {"&nbsp;&nbsp;|&nbsp;&nbsp;" if gland_str and lug_str else ""}{lug_str}
          </div>
          {('<div class="flags">' + flag_html + '</div>') if flag_html else ''}
        </div>
        """, unsafe_allow_html=True)

    # Detailed check expander for reviewable lines
    review_reports = [r for r in summary.reports if r.final_status != "APPROVED"]
    if review_reports:
        with st.expander(f"📋 Detailed checks for {len(review_reports)} line(s) needing attention"):
            for report in review_reports:
                st.markdown(f"**L{report.line_no:02d} — {report.description}**")
                for chk in report.checks:
                    if chk["severity"] == "PASS":
                        st.markdown(f"  ✓ {chk['title']}")
                    else:
                        sev = chk["severity"]
                        icon = {"BLOCK": "🚫", "WARNING": "⚠", "INFO": "ℹ"}.get(sev, "·")
                        st.markdown(f"  {icon} **{chk['title']}**")
                        st.caption(f"     {chk['detail']}")
                        st.caption(f"     ▶ {chk['action']}")
                st.markdown("---")

    st.markdown('<div class="div-line"></div>', unsafe_allow_html=True)

    col_back, col_gen = st.columns([1, 2])
    with col_back:
        if st.button("← Back to Parsed Lines", use_container_width=True):
            st.session_state.stage = "parsed"
            st.rerun()
    with col_gen:
        if summary.release_allowed:
            if st.button("📄 Generate Quotation Excel", type="primary", use_container_width=True):
                with st.spinner("Building Excel quotation…"):
                    config = QuoteConfig(
                        quote_ref=quote_ref,
                        quote_date=date.today().strftime("%d.%m.%Y"),
                        client_name=client_name,
                        client_address="",
                        project_name=project,
                        section_label=sec_label,
                        section_title=sec_title,
                        section_description=sec_desc,
                        discount_pct=discount,
                        generated_by=gen_by,
                        approved_by=appr_by,
                        currency="INR",
                        is_export=is_export,
                        include_validation_sheet=True,
                    )

                    out_path = os.path.join(tempfile.gettempdir(), f"{quote_ref}.xlsx")
                    gen_result = generate_quotation(
                        items, results, summary, config, out_path
                    )

                    if gen_result["ok"]:
                        with open(out_path, "rb") as f:
                            st.session_state.output_bytes = f.read()
                        st.session_state.output_filename = f"{quote_ref}_Braco_Quotation.xlsx"
                        st.session_state.stage = "done"
                    else:
                        st.error(f"Generation failed: {gen_result['reason']}")

                st.rerun()
        else:
            st.button(
                "🚫 Blocked — resolve issues first",
                disabled=True,
                use_container_width=True,
            )
            st.caption("Fix the BLOCK items above, then re-run the pipeline.")

# ══════════════════════════════════════════════════════════════════════
# STAGE 4 — DONE / DOWNLOAD
# ══════════════════════════════════════════════════════════════════════

elif stage == "done":
    summary = st.session_state.val_summary
    st.markdown('<div class="section-label">Step 4 — Quotation Ready</div>', unsafe_allow_html=True)

    st.success(
        f"✅ Quotation **{quote_ref}** generated successfully.\n\n"
        f"{summary.approved} lines approved · {summary.needs_review} with review notes · "
        f"Net total ₹{summary.grand_total_net:,.2f} @{discount:.0f}% discount"
    )

    st.markdown(f"""
    <div class="stat-row">
      <div class="stat-card green"><div class="num">{summary.approved}</div><div class="lbl">Approved</div></div>
      <div class="stat-card amber"><div class="num">{summary.needs_review}</div><div class="lbl">Review Notes</div></div>
      <div class="stat-card"><div class="num">₹{summary.grand_total_net:,.0f}</div><div class="lbl">Net Total</div></div>
      <div class="stat-card"><div class="num">{discount:.0f}%</div><div class="lbl">Discount</div></div>
    </div>
    """, unsafe_allow_html=True)

    # Download button — primary action
    st.download_button(
        label=f"⬇ Download  {st.session_state.output_filename}",
        data=st.session_state.output_bytes,
        file_name=st.session_state.output_filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )

    st.markdown('<div class="div-line"></div>', unsafe_allow_html=True)

    # What's in the file
    with st.expander("📂 What's in the Excel file?", expanded=False):
        st.markdown("""
**Sheet 1 — Quotation**
- Quote reference and date
- All cable lines with gland and lug selections
- OD values (client-stated or Polycab reference)
- List prices and net prices at the applied discount
- Grand total formula (dynamically calculated in Excel)
- OD disclaimer note
- Full Terms & Conditions

**Sheet 2 — Validation Audit**
- Summary: approved / review / blocked counts
- Line-by-line check results
- Confidence scores
- Internal audit trail (for Braco use, not sent to client)
        """)

    col_new, col_back = st.columns(2)
    with col_new:
        if st.button("🔄 Start New Quote", use_container_width=True, type="primary"):
            _reset(); st.rerun()
    with col_back:
        if st.button("← Back to Validation", use_container_width=True):
            st.session_state.stage = "validated"
            st.session_state.output_bytes = None
            st.rerun()

# ══════════════════════════════════════════════════════════════════════
# ERROR DISPLAY (any stage)
# ══════════════════════════════════════════════════════════════════════

if st.session_state.error:
    with st.expander("🔴 Error Details", expanded=True):
        st.code(st.session_state.error, language="python")
    if st.button("Clear error and reset"):
        _reset(); st.rerun()

# ══════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════

st.markdown('<div class="div-line"></div>', unsafe_allow_html=True)
st.markdown(
    '<p style="font-size:0.72rem;color:#94a3b8;text-align:center;">'
    'Braco Quotation Engine v1 &nbsp;·&nbsp; '
    'Parser → Selection Engine → Validation → Output &nbsp;·&nbsp; '
    f'Prices from National Price List w.e.f. 01.01.2026'
    '</p>',
    unsafe_allow_html=True,
)
