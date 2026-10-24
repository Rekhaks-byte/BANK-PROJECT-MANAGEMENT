"""
Bank Statement -> CSV Extractor (FREE / OFFLINE VERSION)
----------------------------------------------------------
No paid API needed. Works two ways:

1. PDF upload: reads the text layer directly out of the PDF (fast, free,
   accurate — works for any statement downloaded from netbanking, since
   those are real text, not scanned images).
2. Screenshot upload (PNG/JPG): runs local OCR (Tesseract, via pytesseract)
   to read the text out of the image.

Then a rule-based parser pulls out date / description / debit / credit /
balance from each line, and a keyword dictionary assigns a spending
category. Everything runs on your own machine.

Run with:
    pip install -r requirements.txt
    streamlit run app.py

NOTE: For screenshot/image uploads only, you also need the Tesseract OCR
program itself installed on Windows (not just the pip package):
    https://github.com/UB-Mannheim/tesseract/wiki
PDF uploads do NOT need Tesseract at all.
"""

import io
import re

import fitz  # PyMuPDF
import pandas as pd
import streamlit as st
from PIL import Image

st.set_page_config(page_title="MoneyLens — Statement Analyzer", layout="wide", page_icon="💸")

st.markdown(
    """
    <style>
    .hero {
        padding: 2rem 2rem 1.5rem 2rem;
        border-radius: 18px;
        background: linear-gradient(135deg, #14532d 0%, #0f766e 45%, #0e7490 100%);
        margin-bottom: 1.8rem;
    }
    .hero h1 {
        font-size: 2.1rem;
        margin-bottom: 0.3rem;
        color: #F0FDF4;
    }
    .hero p {
        color: #D1FAE5;
        font-size: 1rem;
        margin: 0;
    }
    div[data-testid="stMetric"] {
        background: #141C2F;
        border: 1px solid #22D3A6;
        border-radius: 14px;
        padding: 0.9rem 1rem;
    }
    div[data-testid="stMetricValue"] {
        color: #22D3A6;
    }
    section[data-testid="stFileUploader"] {
        border: 1.5px dashed #22D3A6;
        border-radius: 14px;
        padding: 0.6rem;
    }
    .stDownloadButton button, .stButton button {
        border-radius: 10px !important;
        font-weight: 600;
    }
    </style>
    <div class="hero">
        <h1>💸 MoneyLens</h1>
        <p>Upload a bank statement — get every transaction categorized and exported to CSV, free and offline.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Category keyword rules — edit/extend freely
# ---------------------------------------------------------------------------
CATEGORY_RULES = {
    "Food & Dining": ["swiggy", "zomato", "restaurant", "cafe", "food", "eatery", "dominos", "pizza", "starbucks", "hotel"],
    "Groceries": ["bigbasket", "blinkit", "zepto", "grocery", "supermarket", "dmart", "kirana", "mart"],
    "Shopping": ["amazon", "flipkart", "myntra", "ajio", "mall", "shopping", "store", "retail"],
    "Bills & Utilities": ["electricity", "recharge", "broadband", "wifi", "mobile bill", "dth", "gas bill", "water bill", "bescom", "bill"],
    "Transport": ["uber", "ola", "rapido", "petrol", "fuel", "metro", "irctc", "fastag", "toll", "diesel"],
    "Entertainment": ["netflix", "prime video", "hotstar", "spotify", "bookmyshow", "movie", "pvr", "inox", "game"],
    "Health": ["pharmacy", "hospital", "clinic", "medical", "doctor", "health", "apollo", "medplus", "diagnostic", "lab", "insurance", "medicine"],
    "Salary/Income": ["salary", "stipend", "payroll", "credited by employer", "credit interest"],
    "Transfer": ["upi", "neft", "imps", "rtgs", "transfer", "sent to", "received from", "p2p", "paytm", "gpay", "phonepe"],
    "ATM/Cash": ["atm", "cash withdrawal", "cash wdl"],
    "Fees & Charges": ["charge", "fee", "penalty", "gst", "interest debited", "amb"],
}




# Matches: "Aug 06, 2026  01:20 pm  DEBIT  ₹750  Paid to SCOOTERMAN AUTOMOTIVES..."
# Works even if line breaks land between each field, since we collapse whitespace first.
TRANSACTION_PATTERN = re.compile(
    r"(?P<date>[A-Za-z]{3,9}\s\d{1,2},\s\d{4})\s+"
    r"(?P<time>\d{1,2}:\d{2}\s?[ap]m)\s+"
    r"(?P<type>DEBIT|CREDIT)\s+"
    r"₹\s?(?P<amount>[\d,]+(?:\.\d+)?)\s+"
    r"(?:Paid to|Received from|to|from)?\s*"
    r"(?P<description>.*?)"
    r"(?=(?:[A-Za-z]{3,9}\s\d{1,2},\s\d{4}\s+\d{1,2}:\d{2}\s?[ap]m\s+(?:DEBIT|CREDIT))|$)",
    re.IGNORECASE,
)


def categorize(description: str) -> str:
    desc_lower = description.lower()
    for category, keywords in CATEGORY_RULES.items():
        if any(kw in desc_lower for kw in keywords):
            return category
    return "Miscellaneous"


def extract_transactions(text: str):
    """Find every transaction in a block of statement text, regardless of line breaks."""
    flat_text = re.sub(r"\s+", " ", text)
    results = []
    for m in TRANSACTION_PATTERN.finditer(flat_text):
        amount = m.group("amount").replace(",", "")
        ttype = m.group("type").upper()
        description = m.group("description").strip(" -.,:|")
        if not description:
            continue
        results.append(
            {
                "date": m.group("date"),
                "time": m.group("time"),
                "description": description,
                "debit": amount if ttype == "DEBIT" else "",
                "credit": amount if ttype == "CREDIT" else "",
                "category": categorize(description),
            }
        )
    return results


def extract_text_from_pdf(pdf_bytes: bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages_text = [page.get_text() for page in doc]
    doc.close()
    return pages_text


def extract_text_from_image(image_bytes: bytes):
    try:
        import pytesseract
    except ImportError:
        st.error("pytesseract isn't installed. Run: pip install pytesseract")
        return ""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    try:
        return pytesseract.image_to_string(img)
    except Exception as e:
        st.error(
            "OCR failed. Make sure the Tesseract OCR program itself is installed "
            "(not just the pip package): "
            "https://github.com/UB-Mannheim/tesseract/wiki\n\n"
            f"Error: {e}"
        )
        return ""


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
uploaded_files = st.file_uploader(
    "Upload bank statement PDF or screenshot(s) (PDF, PNG, JPG)",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
)

if uploaded_files:
    all_transactions = []
    raw_texts = []

    for f in uploaded_files:
        file_bytes = f.read()
        if f.type == "application/pdf" or f.name.lower().endswith(".pdf"):
            with st.spinner(f"Reading text from {f.name}..."):
                pages_text = extract_text_from_pdf(file_bytes)
                raw_texts.extend(pages_text)
        else:
            with st.spinner(f"Running OCR on {f.name}..."):
                raw_texts.append(extract_text_from_image(file_bytes))

    with st.expander("Raw extracted text (for debugging)"):
        st.text("\n\n---PAGE BREAK---\n\n".join(raw_texts))

    for page_num, text in enumerate(raw_texts, start=1):
        rows = extract_transactions(text)
        for row in rows:
            row["source_page"] = page_num
            all_transactions.append(row)

    if not all_transactions:
        st.warning(
            "No transactions could be parsed. Expand 'Raw extracted text' above to see what "
            "was read, and check the date/amount format matches what the parser expects."
        )
    else:
        df = pd.DataFrame(all_transactions)
        cols = ["date", "time", "description", "debit", "credit", "category", "source_page"]
        df = df[[c for c in cols if c in df.columns]]

        df["debit"] = pd.to_numeric(df["debit"], errors="coerce").fillna(0)
        df["credit"] = pd.to_numeric(df["credit"], errors="coerce").fillna(0)

        st.subheader("💰 Where your money went")
        CATEGORY_ICONS = {
            "Food & Dining": "🍔", "Groceries": "🛒", "Shopping": "🛍️",
            "Bills & Utilities": "🧾", "Transport": "🚗", "Entertainment": "🎬",
            "Health": "🏥", "Salary/Income": "💵", "Transfer": "🔁",
            "ATM/Cash": "🏧", "Fees & Charges": "⚠️", "Miscellaneous": "📦",
        }
        by_cat = df.groupby("category")["debit"].sum().sort_values(ascending=False)
        by_cat = by_cat[by_cat > 0]
        if len(by_cat) > 0:
            metric_cols = st.columns(min(4, len(by_cat)))
            for i, (cat, amount) in enumerate(by_cat.items()):
                icon = CATEGORY_ICONS.get(cat, "💳")
                metric_cols[i % len(metric_cols)].metric(f"{icon} {cat}", f"₹{amount:,.2f}")
            st.bar_chart(by_cat)
        else:
            st.info("No spending (debit) amounts were detected to break down by category.")

        st.subheader(f"All {len(df)} extracted transactions")
        st.dataframe(df, use_container_width=True)

        summary = (
            df.groupby("category")
            .agg(transactions=("category", "count"), total_debit=("debit", "sum"), total_credit=("credit", "sum"))
            .sort_values("total_debit", ascending=False)
            .reset_index()
        )
        with st.expander("Category summary table"):
            st.dataframe(summary, use_container_width=True)

        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)

        # Extra: also save the CSV directly to disk in the project folder
        output_path = "transactions.csv"
        df.to_csv(output_path, index=False)
        st.success(f"CSV also saved to disk at: {output_path}")

        st.download_button(
            "Download CSV",
            data=csv_buffer.getvalue(),
            file_name="transactions.csv",
            mime="text/csv",
            type="primary",
        )