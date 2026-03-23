# ================= FINAL ULTRA-STABLE VERSION (FULLY FIXED) =================
import streamlit as st
import pandas as pd
import sqlite3
import hashlib
from PIL import Image
import pytesseract
import re

# ================= CONFIG =================
st.set_page_config(page_title="DataPilot AI", layout="wide")
st.title("📊 DataPilot AI")
st.markdown("### Upload → Clean → Export")

# ================= DATABASE =================
conn = sqlite3.connect("datapilot.db", check_same_thread=False)
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
conn.commit()

# ================= SECURITY =================
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
    except: return False

# ================= OCR =================
def vision_extract(file):
    try:
        img = Image.open(file)
        text = pytesseract.image_to_string(img)
        data = {"Date": None, "Vendor_Name": None, "Bill_Number": None, "Total_Amount": None}
        
        date_match = re.search(r"\d{2}[-/]\d{2}[-/]\d{4}", text)
        if date_match: data["Date"] = date_match.group()
        
        amounts = re.findall(r"\d+\.\d+|\d+", text)
        if amounts: 
            try:
                data["Total_Amount"] = max([float(a) for a in amounts])
            except: pass
        
        bill_match = re.search(r"(INV[- ]?\d+|BILL[- ]?\d+)", text.upper())
        if bill_match: data["Bill_Number"] = bill_match.group()
        
        lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 5]
        if lines: data["Vendor_Name"] = lines[0]
        
        return pd.DataFrame([data])
    except: 
        return pd.DataFrame()

# ================= SMART VALIDATION =================
def validate(df):
    if df.empty: return df
    df = df.copy()
    
    # SMART COLUMN MAPPING
    amt_col = next((c for c in ["Transaction Amount", "Total_Amount", "Amount"] if c in df.columns), None)
    
    if amt_col:
        df[amt_col] = pd.to_numeric(df[amt_col], errors="coerce")
        df["flag_amount"] = df[amt_col].isna() | (df[amt_col] <= 0)
    else:
        df["flag_amount"] = False

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["flag_date"] = df["Date"].isna()
    else:
        df["flag_date"] = False

    flag_cols = [c for c in df.columns if c.startswith("flag_")]
    if flag_cols:
        df["needs_review"] = df[flag_cols].any(axis=1)
    
    return df

# ================= SESSION STATE =================
st.session_state.setdefault("logged_in", False)
st.session_state.setdefault("pool", [])
st.session_state.setdefault("master", pd.DataFrame())

# ================= AUTHENTICATION UI =================
if not st.session_state.logged_in:
    st.sidebar.title("Access Control")
    tab1, tab2 = st.sidebar.tabs(["Login", "Signup"])
    
    with tab1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Login"):
            if login_user(u, p):
                st.session_state.logged_in = True
                st.rerun()
            else: 
                st.error("Login failed. Check credentials.")
            
    with tab2:
        nu = st.text_input("New Username")
        np = st.text_input("New Password", type="password")
        if st.button("Create Account"):
            if create_user(nu, np): st.success("Account created! Go to Login.")
    st.stop()

# ================= MAIN MENU =================
menu = st.sidebar.radio("Navigation", ["Upload Hub", "Clean & Export"])

# ================= UPLOAD PAGE =================
if menu == "Upload Hub":
    files = st.file_uploader("Upload CSV or Images", accept_multiple_files=True, type=['csv', 'xlsx', 'png', 'jpg', 'jpeg'])
    
    if files:
        for f in files:
            if f.name not in [x["name"] for x in st.session_state.pool]:
                try:
                    if f.name.endswith(".csv"):
                        df = pd.read_csv(f)
                    elif f.name.endswith((".xlsx", ".xls")):
                        df = pd.read_excel(f)
                    else:
                        df = vision_extract(f)
                    st.session_state.pool.append({"name": f.name, "data": df, "selected": True})
                    st.success(f"Added: {f.name}")
                except Exception as e:
                    st.error(f"Error loading {f.name}: {e}")

    if st.session_state.pool:
        st.subheader("Files in Current Session")
        selected_list = []
        for i, item in enumerate(st.session_state.pool):
            if st.checkbox(item["name"], value=item["selected"], key=f"file_{i}"):
                selected_list.append(item["data"])
        
        if selected_list:
            st.session_state.master = pd.concat(selected_list, ignore_index=True)
            st.write("Preview:")
            st.dataframe(st.session_state.master.head(10))

# ================= CLEANING PAGE =================
elif menu == "Clean & Export":
    if st.session_state.master.empty:
        st.warning("No data found. Please upload files first.")
        st.stop()

    df = st.session_state.master

    if st.button("Auto Clean (Keep All Rows)"):
        cleaned = df.drop_duplicates()
        st.session_state.master = validate(cleaned)
        st.success(f"Cleaned! Showing {len(st.session_state.master)} records.")
        st.rerun()

    st.info("Edit cells directly below if needed:")
    edited_df = st.data_editor(st.session_state.master)
    
    st.divider()
    
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            label="📥 Download Full Dataset (All Rows)",
            data=edited_df.to_csv(index=False),
            file_name="full_export.csv",
            mime="text/csv"
        )
    
    with c2:
        if "needs_review" in edited_df.columns:
            clean_only = edited_df[~edited_df["needs_review"]]
            st.download_button(
                label=f"✅ Download Validated ({len(clean_only)} rows)",
                data=clean_only.to_csv(index=False),
                file_name="clean_export.csv",
                mime="text/csv"
            )
