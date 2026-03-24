import streamlit as st
import pandas as pd
import sqlite3
import hashlib
from PIL import Image
import pytesseract
import re
import datetime

# ================= 1. CONFIGURATION =================
st.set_page_config(page_title="DataPilot AI Enterprise", layout="wide")
st.title("🚀 DataPilot AI: Professional Edition")

# ================= 2. DATABASE (Auth & Mapping) =================
conn = sqlite3.connect("datapilot_v3.db", check_same_thread=False)
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
c.execute("CREATE TABLE IF NOT EXISTS ledger_map (ocr_name TEXT PRIMARY KEY, tally_name TEXT)")
conn.commit()

# ================= 3. SECURITY LOGIC =================
def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

def login_user(u, p):
    c.execute("SELECT * FROM users WHERE username=? AND password=?", (u, hash_pw(p)))
    return c.fetchone()

def create_user(u, p):
    try:
        c.execute("INSERT INTO users VALUES (?,?)", (u, hash_pw(p)))
        conn.commit()
        return True
    except: return False

# ================= 4. ACCOUNTING & XML LOGIC =================
def calculate_gst_breakup(total_amt, rate):
    if total_amt <= 0: return 0.0, 0.0
    taxable = round(total_amt / (1 + (rate / 100)), 2)
    gst = round(total_amt - taxable, 2)
    return taxable, gst

def generate_tally_xml(df):
    xml_output = "<ENVELOPE>\n<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>\n<BODY><IMPORTDATA><REQUESTDATA>\n"
    for _, row in df.iterrows():
        # Ensure date is Tally-friendly (YYYYMMDD)
        try:
            d = pd.to_datetime(row['Date']).strftime('%Y%m%d')
        except:
            d = datetime.datetime.now().strftime('%Y%m%d')
            
        v_name = row.get('Tally_Ledger_Name', row['Vendor_Name'])
        
        xml_output += f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
            <VOUCHER VCHTYPE="Payment" ACTION="Create">
                <DATE>{d}</DATE>
                <VOUCHERNUMBER>{row.get('Bill_Number')}</VOUCHERNUMBER>
                <PARTYLEDGERNAME>{v_name}</PARTYLEDGERNAME>
                <BANKERSDATE>{d}</BANKERSDATE> 
                <NARRATION>Bill: {row.get('Bill_Number')} | DataPilot AI Cleaned</NARRATION>
                <ALLLEDGERENTRIES.LIST>
                    <LEDGERNAME>{v_name}</LEDGERNAME>
                    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                    <AMOUNT>-{row['Total_Amount']}</AMOUNT>
                </ALLLEDGERENTRIES.LIST>
            </VOUCHER>
        </TALLYMESSAGE>"""
    xml_output += "\n</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>"
    return xml_output

# ================= 5. OCR & CLEANING ENGINE =================
def vision_extract(file):
    try:
        img = Image.open(file)
        text = pytesseract.image_to_string(img)
        
        # Date Extraction
        date_match = re.search(r"\d{2}[-/]\d{2}[-/]\d{4}", text)
        date_val = date_match.group() if date_match else datetime.date.today().strftime("%d-%m-%Y")
        
        # Amount Extraction
        amounts = re.findall(r"\d+\.\d+", text)
        total_amt = max([float(a) for a in amounts]) if amounts else 0.0
        
        # GST Rate
        rate_search = re.search(r"(\d{1,2})\s?%", text)
        gst_rate = float(rate_search.group(1)) if rate_search else 18.0
        
        # Vendor Name (Force non-null)
        lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 2]
        vendor = lines[0][:40] if lines else "UNKNOWN_VENDOR"
        
        # Bill Number (Force non-null)
        bill_match = re.search(r"(INV|BILL)[- ]?(\d+)", text.upper())
        bill_no = bill_match.group(0) if bill_match else f"TMP-{datetime.datetime.now().strftime('%H%M%S')}"

        taxable, gst_val = calculate_gst_breakup(total_amt, gst_rate)

        return pd.DataFrame([{
            "Date": date_val,
            "Vendor_Name": vendor,
            "Bill_Number": bill_no,
            "GST_Rate": gst_rate,
            "Taxable_Value": taxable,
            "GST_Amount": gst_val,
            "Total_Amount": total_amt
        }])
    except: return pd.DataFrame()

# ================= 6. AUTHENTICATION UI =================
st.session_state.setdefault("logged_in", False)
st.session_state.setdefault("pool", [])

if not st.session_state.logged_in:
    st.sidebar.title("🔐 Login")
    u = st.sidebar.text_input("Username")
    p = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Enter System"):
        if login_user(u, p):
            st.session_state.logged_in = True
            st.rerun()
    if st.sidebar.button("Signup"):
        if create_user(u, p): st.sidebar.success("Account Ready!")
    st.stop()

# ================= 7. NAVIGATION =================
menu = st.sidebar.radio("Menu", ["1. Upload", "2. Mapping", "3. Export"])

# --- PAGE 1: UPLOAD (Deduplication Logic) ---
if menu == "1. Upload":
    st.header("📂 Upload Bills")
    files = st.file_uploader("Upload Images/CSV", accept_multiple_files=True)
    
    if files:
        for f in files:
            # CHECK FOR DUPLICATES: If filename already in pool, skip it
            if f.name not in [x["name"] for x in st.session_state.pool]:
                with st.spinner(f"Reading {f.name}..."):
                    df = vision_extract(f) if not f.name.endswith('.csv') else pd.read_csv(f)
                    if not df.empty:
                        st.session_state.pool.append({"name": f.name, "data": df, "selected": True})

    if st.session_state.pool:
        st.subheader("Selected Bills")
        selected_list = []
        for i, item in enumerate(st.session_state.pool):
            if st.checkbox(item["name"], value=item["selected"], key=f"f_{i}"):
                selected_list.append(item["data"])
        
        if selected_list:
            st.session_state.master = pd.concat(selected_list, ignore_index=True).drop_duplicates()

# --- PAGE 2: MAPPING ---
elif menu == "2. Mapping":
    st.header("🔗 Tally Mapping")
    with st.form("m"):
        o = st.text_input("Name on Bill")
        t = st.text_input("Name in Tally")
        if st.form_submit_button("Save"):
            c.execute("INSERT OR REPLACE INTO ledger_map VALUES (?,?)", (o, t))
            conn.commit()
    st.table(pd.read_sql("SELECT * FROM ledger_map", conn))

# --- PAGE 3: EXPORT (Null Handling Logic) ---
elif menu == "3. Export":
    st.header("📑 Final Audit")
    if "master" in st.session_state and not st.session_state.master.empty:
        maps = dict(c.execute("SELECT * FROM ledger_map").fetchall())
        df = st.session_state.master.copy()
        df['Tally_Ledger_Name'] = df['Vendor_Name'].map(maps).fillna(df['Vendor_Name'])
        
        # Ensure No Nulls in critical columns before showing editor
        df['Date'] = df['Date'].fillna(datetime.date.today().strftime("%d-%m-%Y"))
        df['Total_Amount'] = df['Total_Amount'].fillna(0.0)
        
        edited = st.data_editor(df, num_rows="dynamic")
        
        # Re-calc math
        for i, r in edited.iterrows():
            tx, gs = calculate_gst_breakup(r['Total_Amount'], r['GST_Rate'])
            edited.at[i, 'Taxable_Value'] = tx
            edited_at[i, 'GST_Amount'] = gs

        if st.download_button("🚀 Export Tally XML", generate_tally_xml(edited), "tally.xml"):
            st.balloons()
