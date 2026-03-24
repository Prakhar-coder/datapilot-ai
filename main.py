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
# We use a persistent connection for the session
conn = sqlite3.connect("datapilot_v3.db", check_same_thread=False)
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
# Primary key is now a combination of client and ocr_name to allow unique maps per owner
c.execute("""CREATE TABLE IF NOT EXISTS ledger_map 
             (client_id TEXT, ocr_name TEXT, tally_name TEXT, 
             PRIMARY KEY (client_id, ocr_name))""")
conn.commit()

# ================= 3. SECURITY & HELPERS =================
def hash_pw(p): 
    return hashlib.sha256(p.encode()).hexdigest()

def login_user(u, p):
    c.execute("SELECT * FROM users WHERE username=? AND password=?", (u, hash_pw(p)))
    return c.fetchone()

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

# ================= 6. AUTHENTICATION UI =================
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "pool" not in st.session_state: st.session_state.pool = []

if not st.session_state.logged_in:
    st.title("🔐 DataPilot AI: Secure Access")
    with st.sidebar:
        st.header("Access Control")
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        
        col1, col2 = st.columns(2)
        if col1.button("Login"):
            if login_user(u, p):
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("Invalid credentials")
        
        if col2.button("Signup"):
            if create_user(u, p):
                st.success("Account created! Now login.")
            else:
                st.error("User already exists")
    st.info("Please login from the sidebar to start processing bills.")
    st.stop()

# ================= 7. CLIENT NAVIGATION =================
st.sidebar.success("Logged In Successfully")
# This dropdown allows the CA to manage 10+ different clients separately
client_id = st.sidebar.selectbox("Select Business Owner", 
                                ["Owner_A", "Owner_B", "Owner_C", "Owner_D", "Owner_E"])

if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.rerun()

menu = st.sidebar.radio("Navigation", ["1. Upload & Pre-Audit", "2. Ledger Mapping", "3. Export to Tally"])

# ================= 8. MAIN APP CONTENT =================

# --- PAGE 1: UPLOAD & PRE-AUDIT ---
if menu == "1. Upload & Pre-Audit":
    st.header(f"📂 Processing for: {client_id}")
    files = st.file_uploader("Upload Bill Images", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])
    
    if files:
        for f in files:
            # Check if file is already processed in the current session
            if not any(x['name'] == f.name for x in st.session_state.pool):
                with st.spinner(f"Extracting {f.name}..."):
                    df = vision_extract(f)
                    if not df.empty:
                        # We tag the data with the client_id selected at time of upload
                        st.session_state.pool.append({"name": f.name, "data": df, "client": client_id})

    if st.session_state.pool:
        # Filter pool for ONLY the currently selected client
        current_client_data = [x for x in st.session_state.pool if x["client"] == client_id]
        
        if current_client_data:
            master_df = pd.concat([x["data"] for x in current_client_data], ignore_index=True)
            
            # --- PRE-MAPPING CHECK ---
            c.execute("SELECT ocr_name FROM ledger_map WHERE client_id=?", (client_id,))
            saved_mappings = [r[0] for r in c.fetchall()]
            
            all_vendors = master_df['Vendor_Name'].unique()
            missing_vendors = [v for v in all_vendors if v not in saved_mappings]
            
            st.divider()
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Bills", len(master_df))
            m2.metric("Ready for Tally", len(master_df) - master_df['Vendor_Name'].isin(missing_vendors).sum())
            m3.metric("Action Required", len(missing_vendors))

            if missing_vendors:
                st.error(f"⚠️ {len(missing_vendors)} unique vendors are not mapped to Tally ledgers.")
                with st.expander("View Missing Vendor List"):
                    st.write("Go to 'Ledger Mapping' and link these raw names to Tally ledgers:")
                    st.table(pd.DataFrame(missing_vendors, columns=["OCR Vendor Name"]))
            else:
                st.success("✅ Perfect! All vendors are recognized. Ready for Export.")

            st.subheader("Data Preview")
            st.dataframe(master_df, use_container_width=True)
        else:
            st.info("No bills uploaded for this specific owner yet.")

# --- PAGE 2: LEDGER MAPPING ---
elif menu == "2. Ledger Mapping":
    st.header(f"🔗 Tally Ledger Mapping: {client_id}")
    st.write("Link messy bill names to your exact Tally Ledger names.")
    
    with st.form("mapping_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            raw_ocr = st.text_input("Vendor Name on Bill (OCR Name)")
        with col2:
            clean_tally = st.text_input("Exact Name in Tally Ledger")
            
        if st.form_submit_button("Save Mapping"):
            if raw_ocr and clean_tally:
                c.execute("INSERT OR REPLACE INTO ledger_map VALUES (?,?,?)", (client_id, raw_ocr.strip(), clean_tally.strip()))
                conn.commit()
                st.success(f"Mapping saved for {client_id}!")
            else:
                st.error("Please fill both fields.")
    
    st.divider()
    st.subheader("Stored Dictionary")
    mapping_df = pd.read_sql(f"SELECT ocr_name, tally_name FROM ledger_map WHERE client_id='{client_id}'", conn)
    st.dataframe(mapping_df, use_container_width=True)

# --- PAGE 3: EXPORT ---
elif menu == "3. Export to Tally":
    st.header(f"📑 Audit & XML Export: {client_id}")
    
    client_data = [x for x in st.session_state.pool if x["client"] == client_id]
    
    if client_data:
        export_df = pd.concat([x["data"] for x in client_data], ignore_index=True)
        
        # Apply Mapping logic
        c.execute("SELECT ocr_name, tally_name FROM ledger_map WHERE client_id=?", (client_id,))
        mapping_dict = dict(c.fetchall())
        
        export_df['Tally_Ledger_Name'] = export_df['Vendor_Name'].map(mapping_dict).fillna(export_df['Vendor_Name'])
        
        st.write("Edit values before generating XML:")
        final_edited = st.data_editor(export_df, use_container_width=True, num_rows="dynamic")
        
        if st.download_button("🚀 Download Tally XML", generate_tally_xml(final_edited), f"{client_id}_tally.xml"):
            st.balloons()
            st.success("XML Generated! Import this file into Tally using 'Import Data > Transactions'.")
    else:
        st.warning("No processed data found. Please upload bills first.")
