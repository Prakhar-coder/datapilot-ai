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
# Added client_id to support multiple business owners in mapping
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
            
        # Use mapped name if available, else original
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
    st.title("🔐 DataPilot AI: Secure Login")
    u = st.sidebar.text_input("Username")
    p = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        if login_user(u, p):
            st.session_state.logged_in = True
            st.rerun()
    st.info("Login from the sidebar to continue.")
    st.stop()

# ================= 7. CLIENT SELECTION & NAVIGATION =================
st.sidebar.success("Authenticated")
client_id = st.sidebar.selectbox("Select Business Owner", 
                                ["Owner_A", "Owner_B", "Owner_C", "Owner_D"])

if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.rerun()

menu = st.sidebar.radio("Navigation", ["1. Upload & Pre-Audit", "2. Ledger Mapping", "3. Export to Tally"])

# ================= 8. MAIN APP CONTENT =================

# --- PAGE 1: UPLOAD & PRE-AUDIT ---
if menu == "1. Upload & Pre-Audit":
    st.header(f"📂 Processing Bills for: {client_id}")
    files = st.file_uploader("Upload Bill Images", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])
    
    if files:
        for f in files:
            if not any(x['name'] == f.name for x in st.session_state.pool):
                with st.spinner(f"Extracting {f.name}..."):
                    df = vision_extract(f)
                    if not df.empty:
                        st.session_state.pool.append({"name": f.name, "data": df, "selected": True, "client": client_id})

    if st.session_state.pool:
        # Filter pool for current client
        client_files = [x for x in st.session_state.pool if x["client"] == client_id]
        
        if client_files:
            master_data = pd.concat([x["data"] for x in client_files], ignore_index=True)
            
            # CHECK MAPPING STATUS IMMEDIATELY
            c.execute("SELECT ocr_name FROM ledger_map WHERE client_id=?", (client_id,))
            mapped_list = [r[0] for r in c.fetchall()]
            
            all_vendors = master_data['Vendor_Name'].unique()
            missing = [v for v in all_vendors if v not in mapped_list]
            
            # --- Status Metrics ---
            st.divider()
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Transactions", len(master_data))
            m2.metric("Ready for Tally", len(master_data) - master_data['Vendor_Name'].isin(missing).sum())
            m3.metric("Missing Mappings", len(missing))

            if missing:
                st.error(f"⚠️ {len(missing)} unique vendors need mapping before Tally Export.")
                with st.expander("Show Missing Vendors"):
                    st.write("Go to 'Ledger Mapping' and add these raw names:")
                    st.table(pd.DataFrame(missing, columns=["OCR Vendor Name"]))
            else:
                st.success("✅ All vendors are mapped. Proceed to Export!")

            st.subheader("Data Preview")
            st.dataframe(master_data, use_container_width=True)

# --- PAGE 2: LEDGER MAPPING ---
elif menu == "2. Ledger Mapping":
    st.header(f"🔗 Tally Ledger Dictionary: {client_id}")
    
    with st.form("mapping_form", clear_on_submit=True):
        o = st.text_input("Vendor Name on Bill (OCR Raw Name)")
        t = st.text_input("Exact Name in Tally ERP Ledger")
        if st.form_submit_button("Save Rule"):
            if o and t:
                c.execute("INSERT OR REPLACE INTO ledger_map VALUES (?,?,?)", (client_id, o.strip(), t.strip()))
                conn.commit()
                st.success(f"Linked '{o}' to '{t}'")
            else:
                st.error("Please provide both names.")
    
    st.divider()
    st.subheader("Saved Mappings")
    mapping_df = pd.read_sql(f"SELECT ocr_name, tally_name FROM ledger_map WHERE client_id='{client_id}'", conn)
    st.table(mapping_df)

# --- PAGE 3: EXPORT ---
elif menu == "3. Export to Tally":
    st.header(f"📑 Final Audit & XML Export: {client_id}")
    
    # Re-check pool for client
    client_files = [x for x in st.session_state.pool if x["client"] == client_id]
    
    if client_files:
        raw_df = pd.concat([x["data"] for x in client_files], ignore_index=True)
        
        # Apply Mappings
        c.execute("SELECT ocr_name, tally_name FROM ledger_map WHERE client_id=?", (client_id,))
        maps = dict(c.fetchall())
        
        raw_df['Tally_Ledger_Name'] = raw_df['Vendor_Name'].map(maps).fillna(raw_df['Vendor_Name'])
        
        st.write("Edit any values manually if required:")
        edited = st.data_editor(raw_df, num_rows="dynamic", use_container_width=True)
        
        # Recalculate tax on edits
        for i, r in edited.iterrows():
            tx, gs = calculate_gst_breakup(r['Total_Amount'], r['GST_Rate'])
            edited.at[i, 'Taxable_Value'] = tx
            edited.at[i, 'GST_Amount'] = gs

        if st.download_button("🚀 Download Tally XML", generate_tally_xml(edited), f"{client_id}_export.xml"):
            st.balloons()
    else:
        st.warning("No data found. Upload bills first.")
