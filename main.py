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
# Added client_id to ledger_map to support multiple business owners
conn = sqlite3.connect("datapilot_v3.db", check_same_thread=False)
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
c.execute("""CREATE TABLE IF NOT EXISTS ledger_map 
             (client_id TEXT, ocr_name TEXT, tally_name TEXT, 
             PRIMARY KEY (client_id, ocr_name))""")
conn.commit()

# ================= 3. SECURITY & HELPERS =================
def hash_pw(p): 
    return hashlib.sha256(p.encode()).hexdigest()

def login_user(u, p):
    c.execute("SELECT * FROM users WHERE username=? AND password=?", (u, hash_pw(p)))
    return f"Authenticated as {u}" if c.fetchone() else None

def create_user(u, p):
    try:
        c.execute("INSERT INTO users VALUES (?,?)", (u, hash_pw(p)))
        conn.commit()
        return True
    except: 
        return False

def calculate_gst_breakup(total_amt, rate):
    if total_amt <= 0: return 0.0, 0.0
    taxable = round(total_amt / (1 + (rate / 100)), 2)
    gst = round(total_amt - taxable, 2)
    return taxable, gst

# ================= 4. TALLY XML ENGINE =================
def generate_tally_xml(df):
    xml_output = "<ENVELOPE>\n<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>\n<BODY><IMPORTDATA><REQUESTDATA>\n"
    for _, row in df.iterrows():
        try:
            # Tally expects YYYYMMDD
            d = pd.to_datetime(row['Date']).strftime('%Y%m%d')
        except:
            d = datetime.datetime.now().strftime('%Y%m%d')
            
        # Prioritize the Mapped Tally Name over the raw OCR Vendor Name
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

# ================= 5. OCR ENGINE =================
def vision_extract(file):
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

        return pd.DataFrame([{
            "Date": date_val,
            "Vendor_Name": vendor,
            "Bill_Number": bill_no,
            "GST_Rate": gst_rate,
            "Taxable_Value": taxable,
            "GST_Amount": gst_val,
            "Total_Amount": total_amt
        }])
    except: 
        return pd.DataFrame()

# ================= 6. AUTHENTICATION & CLIENT SELECTION =================
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "pool" not in st.session_state: st.session_state.pool = []

if not st.session_state.logged_in:
    st.title("🔐 DataPilot AI: Secure Login")
    u = st.sidebar.text_input("Username")
    p = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        if login_user(u, p):
            st.session_state.logged_in = True
            st.session_state.user = u
            st.rerun()
    st.info("Login to access the dashboard.")
    st.stop()

# --- CLIENT SELECTION (FOR THE 10 BUSINESS OWNERS) ---
# This ensures Client A's mappings don't mix with Client B's
st.sidebar.title(f"👤 {st.session_state.user}")
client_id = st.sidebar.selectbox("Select Business Owner", 
                                ["Business_Owner_1", "Business_Owner_2", "Business_Owner_3", "Client_Standard"])

if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.rerun()

menu = st.sidebar.radio("Navigation", ["1. Upload Bills", "2. Ledger Mapping", "3. Export to Tally"])

# ================= 7. MAIN APP CONTENT =================

# --- PAGE 1: UPLOAD ---
if menu == "1. Upload Bills":
    st.header(f"📂 Uploading for: {client_id}")
    files = st.file_uploader("Upload Bill Images", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])
    
    if files:
        for f in files:
            # Only process if not already in pool
            if not any(x['name'] == f.name for x in st.session_state.pool):
                with st.spinner(f"Scanning {f.name}..."):
                    df = vision_extract(f)
                    if not df.empty:
                        st.session_state.pool.append({"name": f.name, "data": df, "selected": True, "client": client_id})

    if st.session_state.pool:
        # Filter pool to show only current client's data
        current_client_files = [x for x in st.session_state.pool if x["client"] == client_id]
        if current_client_files:
            st.subheader("Document Pool")
            selected_dfs = []
            for item in current_client_files:
                if st.checkbox(item["name"], value=True):
                    selected_dfs.append(item["data"])
            
            if selected_dfs:
                st.session_state.master = pd.concat(selected_dfs, ignore_index=True)
                st.dataframe(st.session_state.master)

# --- PAGE 2: MAPPING ---
elif menu == "2. Ledger Mapping":
    st.header(f"🔗 Tally Mapping: {client_id}")
    st.info("Map vendor names from bills to your exact Tally Ledger names.")
    
    with st.form("mapping_form"):
        o = st.text_input("Vendor Name on Bill (Raw OCR)")
        t = st.text_input("Exact Name in Tally ERP Ledger")
        if st.form_submit_button("Save Mapping"):
            c.execute("INSERT OR REPLACE INTO ledger_map VALUES (?,?,?)", (client_id, o.strip(), t.strip()))
            conn.commit()
            st.success(f"Mapping saved for {client_id}!")
    
    st.subheader("Current Saved Mappings")
    mapping_df = pd.read_sql(f"SELECT ocr_name, tally_name FROM ledger_map WHERE client_id='{client_id}'", conn)
    st.dataframe(mapping_df, use_container_width=True)

# --- PAGE 3: EXPORT ---
elif menu == "3. Export to Tally":
    st.header(f"📑 Audit & Export: {client_id}")
    
    # Check if we have data for the current client
    if "master" in st.session_state and not st.session_state.master.empty:
        # 1. Fetch mappings for this specific client
        c.execute("SELECT ocr_name, tally_name FROM ledger_map WHERE client_id=?", (client_id,))
        maps = dict(c.fetchall())
        
        df = st.session_state.master.copy()
        
        # 2. AUTOMATIC MAPPING: Replace OCR name with Tally name
        # .map(maps) finds the Tally name; .fillna() keeps original if no mapping exists
        df['Tally_Ledger_Name'] = df['Vendor_Name'].map(maps).fillna(df['Vendor_Name'])
        
        st.write("Review and edit the data before Tally Export:")
        edited_df = st.data_editor(df, num_rows="dynamic")
        
        if st.download_button("🚀 Download Tally XML", generate_tally_xml(edited_df), f"{client_id}_import.xml"):
            st.balloons()
            st.success("File generated! Import this XML into Tally.")
    else:
        st.warning("No data found for this client. Please upload bills first.")
