import streamlit as st
import tempfile

from braco_parser import parse_excel_file, parsed_line_to_line_item
from braco_engine import run_selection
from braco_validator import validate_quote
from braco_output import generate_quotation, QuoteConfig

st.set_page_config(page_title="Braco Quotation Engine", layout="wide")

st.title("⚡ Braco Quotation Engine")

# Sidebar
st.sidebar.header("Quote Settings")
quote_ref = st.sidebar.text_input("Quote Ref", "QT0001")
client = st.sidebar.text_input("Client Name", "Client")
discount = st.sidebar.number_input("Discount %", value=46.0)

uploaded_file = st.file_uploader("Upload BOQ", type=["xlsx", "xls", "csv"])

if uploaded_file:

    st.success("File uploaded")

    # ---- TEMP FILE FIX ----
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(uploaded_file.getvalue())
        temp_path = tmp.name

    # ---- PARSE ----
    parsed = parse_excel_file(temp_path, use_ai=False, aggregate_sheets=True)

    items = []
    for p in parsed:
        try:
            item = parsed_line_to_line_item(p)
            if item:
                items.append(item)
        except:
            continue

    st.write(f"Parsed items: {len(items)}")

    # ---- SELECTION ----
    results = []
    for item in items:
        try:
            results.append(run_selection(item))
        except:
            continue

    # ---- VALIDATION ----
    summary = validate_quote(items, results, discount)

    st.write(f"Approved: {summary.approved}")
    st.write(f"Review: {summary.needs_review}")
    st.write(f"Blocked: {summary.blocked}")

    if summary.release_allowed:

        st.success("Ready to generate quotation")

        if st.button("Generate Quotation"):

            config = QuoteConfig(
                quote_ref=quote_ref,
                quote_date="",
                client_name=client,
                project_name="",
                section_label="",
                section_title="",
                discount_pct=discount,
                generated_by="User",
                approved_by="Manager"
            )

            output = generate_quotation(
                items,
                results,
                summary,
                config,
                "output.xlsx"
            )

            if output["ok"]:
                with open("output.xlsx", "rb") as f:
                    st.download_button("Download", f, file_name="quotation.xlsx")
            else:
                st.error(output["reason"])

    else:
        st.error("Blocked — fix errors before generating")
