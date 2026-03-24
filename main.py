import streamlit as st
import pandas as pd
import sqlite3
import hashlib
from PIL import Image
import pytesseract
import re
import datetime

# ================= 1. CONFIGURATION =================
st.set_page_config(page_title="DataPilot AI Enterprise", layout="wide", page_icon="🚀")

# ================= 2. DATABASE SETUP =================
conn = sqlite3.connect("datapilot_v4.db", check_same_thread=False)
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
c.execute("CREATE TABLE IF NOT EXISTS clients (client_name TEXT PRIMARY KEY)")
c.execute("""CREATE TABLE IF NOT EXISTS ledger_map 
             (client_name TEXT, ocr_name TEXT, tally_name TEXT, 
             PRIMARY KEY (client_name, ocr_name))""")
# NEW: Table to store bills permanently so they don't vanish on logout
c.execute("""CREATE TABLE IF NOT EXISTS processed_bills 
             (client_name TEXT, bill_date TEXT, vendor TEXT, bill_no TEXT, 
              gst_rate REAL, taxable REAL, gst_amt REAL, total REAL)""")
conn.commit()

# ================= 3. SECURITY & HELPERS =================
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

def calculate_gst_breakup(total_amt, rate):
    if total_amt <= 0: return 0.0, 0.0
    taxable = round(total_amt / (1 + (rate / 100)), 2)
    gst = round(total_amt - taxable, 2)
    return taxable, gst

# ================= 4. TALLY XML ENGINE =================
def generate_tally_xml(df):
    xml_output = "<ENVELOPE>\n<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>\n<BODY><IMPORTDATA><REQUESTDATA>\n"
    for _, row in df.iterrows():
        try: d = pd.to_datetime(row['Date']).strftime('%Y%m%d')
        except: d = datetime.datetime.now().strftime('%Y%m%d')
        v_name = row.get('Tally_Ledger_Name', row['Vendor_Name'])
        xml_output += f"""
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
            <VOUCHER VCHTYPE="Payment" ACTION="Create">
                <DATE>{d}</DATE>
                <VOUCHERNUMBER>{row.get('Bill_Number')}</VOUCHERNUMBER>
                <PARTYLEDGERNAME>{v_name}</PARTYLEDGERNAME>
                <BANKERSDATE>{d}</BANKERSDATE> 
                <NARRATION>Bill: {row.get('Bill_Number')} | DataPilot AI Enterprise</NARRATION>
                <ALLLEDGERENTRIES.LIST>
                    <LEDGERNAME>{v_name}</LEDGERNAME>
                    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                    <AMOUNT>-{row['Total_Amount']}</AMOUNT>
                </ALLLEDGERENTRIES.LIST>
            </VOUCHER>
        </TALLYMESSAGE>"""
    xml_output += "\n</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>"
    return xml_output

# ================= 5. OCR ENGINE =================
def vision_extract(file, client_name):
    try:
        img = Image.open(file)
        text = pytesseract.image_to_string(img)
        date_match = re.search(r"\d{2}[-/]\d{2}[-/]\d{4}", text)
        date_val = date_match.group() if date_match else datetime.date.today().strftime("%d-%m-%Y")
        amounts = re.findall(r"\d+\.\d+", text)
        total_amt = max([float(a) for a in amounts]) if amounts else 0.0
        rate_search = re.search(r"(\d{1,2})\s?%", text)
        gst_rate = float(rate_search.group(1)) if rate_search else 18.0
        lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 2]
        vendor = lines[0][:40] if lines else "UNKNOWN_VENDOR"
        bill_match = re.search(r"(INV|BILL)[- ]?(\d+)", text.upper())
        bill_no = bill_match.group(2) if bill_match else f"TMP-{datetime.datetime.now().strftime('%H%M%S')}"
        taxable, gst_val = calculate_gst_breakup(total_amt, gst_rate)
        
        # SAVE TO PERMANENT DATABASE IMMEDIATELY
        c.execute("INSERT INTO processed_bills VALUES (?,?,?,?,?,?,?,?)", 
                  (client_name, date_val, vendor, bill_no, gst_rate, taxable, gst_val, total_amt))
        conn.commit()
        return True
    except: return False

# ================= 6. AUTHENTICATION =================
if "logged_in" not in st.session_state: st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🔐 DataPilot AI: Enterprise Login")
    with st.sidebar:
        u, p = st.text_input("User"), st.text_input("Pass", type="password")
        if st.button("Login"):
            if login_user(u, p): st.session_state.logged_in = True; st.rerun()
        if st.button("Signup"):
            if create_user(u, p): st.success("Created!")
    st.stop()

# ================= 7. NAVIGATION =================
c.execute("SELECT client_name FROM clients")
client_options = [row[0] for row in c.fetchall()]

with st.sidebar:
    st.success("Authenticated")
    active_client = st.selectbox("Current Client", client_options if client_options else ["No Clients"])
    if st.button("Logout"): st.session_state.logged_in = False; st.rerun()

menu = st.sidebar.radio("Navigation", ["0. Manage Clients", "1. Upload & Audit", "2. Ledger Mapping", "3. Export to Tally"])

# ================= 8. MAIN APP CONTENT =================

# --- PAGE 0: MANAGE CLIENTS ---
if menu == "0. Manage Clients":
    st.header("🏢 Client Portfolio")
    new_c = st.text_input("Enter Business Name")
    if st.button("Register Business"):
        if new_c:
            try:
                c.execute("INSERT INTO clients VALUES (?)", (new_c.strip(),))
                conn.commit(); st.rerun()
            except: st.error("Exists!")
    st.table(pd.read_sql("SELECT * FROM clients", conn))

# --- PAGE 1: UPLOAD & AUDIT ---
elif menu == "1. Upload & Audit":
    if not client_options: st.warning("Add a client first."); st.stop()
    st.header(f"📂 Processing Center: {active_client}")
    
    files = st.file_uploader("Upload Batch", accept_multiple_files=True)
    if files:
        for f in files:
            with st.spinner(f"Reading {f.name}..."):
                vision_extract(f, active_client)
        st.success("Batch Uploaded and Saved Permanently!")

    # PULL DATA FROM PERMANENT DATABASE
    query = f"SELECT bill_date as Date, vendor as Vendor_Name, bill_no as Bill_Number, gst_rate as GST_Rate, taxable as Taxable_Value, gst_amt as GST_Amount, total as Total_Amount FROM processed_bills WHERE client_name='{active_client}'"
    master_df = pd.read_sql(query, conn)

    if not master_df.empty:
        # Check Mapping Status
        c.execute("SELECT ocr_name FROM ledger_map WHERE client_name=?", (active_client,))
        mapped = [r[0] for r in c.fetchall()]
        missing = [v for v in master_df['Vendor_Name'].unique() if v not in mapped]
        
        st.divider()
        m1, m2 = st.columns(2); m1.metric("Saved Bills", len(master_df)); m2.metric("Unmapped Vendors", len(missing))
        
        if missing:
            st.error("⚠️ Mapping Required for New Vendors")
            st.table(pd.DataFrame(missing, columns=["New Vendor Found"]))
        
        st.dataframe(master_df)
        if st.button("🗑️ Clear All Saved Bills for this Client"):
            c.execute("DELETE FROM processed_bills WHERE client_name=?", (active_client,))
            conn.commit(); st.rerun()

# --- PAGE 2: MAPPING ---
elif menu == "2. Ledger Mapping":
    st.header(f"🔗 Tally Dictionary: {active_client}")
    with st.form("map"):
        o, t = st.text_input("OCR Vendor Name"), st.text_input("Tally Ledger Name")
        if st.form_submit_button("Link Vendor"):
            c.execute("INSERT OR REPLACE INTO ledger_map VALUES (?,?,?)", (active_client, o.strip(), t.strip()))
            conn.commit(); st.success("Mapping Remembered!")
    st.table(pd.read_sql(f"SELECT ocr_name, tally_name FROM ledger_map WHERE client_name='{active_client}'", conn))

# --- PAGE 3: EXPORT ---
elif menu == "3. Export to Tally":
    query = f"SELECT bill_date as Date, vendor as Vendor_Name, bill_no as Bill_Number, gst_rate as GST_Rate, taxable as Taxable_Value, gst_amt as GST_Amount, total as Total_Amount FROM processed_bills WHERE client_name='{active_client}'"
    df = pd.read_sql(query, conn)
    
    if not df.empty:
        c.execute("SELECT ocr_name, tally_name FROM ledger_map WHERE client_name=?", (active_client,))
        maps = dict(c.fetchall())
        df['Tally_Ledger_Name'] = df['Vendor_Name'].map(maps).fillna(df['Vendor_Name'])
        
        st.info("Review and make final edits below:")
        edited = st.data_editor(df, use_container_width=True)
        if st.download_button("🚀 Generate Tally XML", generate_tally_xml(edited), f"{active_client}.xml"):
            st.balloons()
    else: st.warning("No saved bills found for this owner.")
