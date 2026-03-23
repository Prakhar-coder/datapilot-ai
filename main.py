# ================= FINAL ULTRA-STABLE VERSION (REPLIT SAFE) =================
import streamlit as st
import pandas as pd
import sqlite3
import hashlib
from PIL import Image
import pytesseract
import re
import time

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
    except:
        return False

# ================= OCR =================
def vision_extract(file):
    try:
        img = Image.open(file)
        text = pytesseract.image_to_string(img)

        data = {"Date": None, "Vendor_Name": None, "Bill_Number": None, "Total_Amount": None}

        date_match = re.search(r"\d{2}[-/]\d{2}[-/]\d{4}", text)
        if date_match:
            data["Date"] = date_match.group()

        amounts = re.findall(r"\d+\.\d+|\d+", text)
        if amounts:
            try:
                data["Total_Amount"] = max([float(a) for a in amounts])
            except:
                pass

        bill_match = re.search(r"(INV[- ]?\d+|BILL[- ]?\d+)", text.upper())
        if bill_match:
            data["Bill_Number"] = bill_match.group()

        lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 5]
        if lines:
            data["Vendor_Name"] = lines[0]

        return pd.DataFrame([data])
    except Exception as e:
        st.error(f"OCR Error: {e}")
        return pd.DataFrame()

# ================= VALIDATION =================
def validate(df):
    if df.empty:
        return df
    df = df.copy()
    
    # Financial data cleaning
    if "Total_Amount" in df.columns:
        df["Total_Amount"] = pd.to_numeric(df["Total_Amount"], errors="coerce")
        df["flag_amount"] = df["Total_Amount"].isna() | (df["Total_Amount"] <= 0)
    
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["flag_date"] = df["Date"].isna()

    # Generic flags for missing data
    df["flag_vendor"] = df.get("Vendor_Name", pd.Series([None]*len(df))).isna()
    df["flag_bill"] = df.get("Bill_Number", pd.Series([None]*len(df))).isna()

    # Identify rows needing review
    flag_cols = [c for c in df.columns if c.startswith("flag_")]
    if flag_cols:
        df["needs_review"] = df[flag_cols].any(axis=1)
    
    return df

# ================= SESSION =================
st.session_state.setdefault("logged_in", False)
st.session_state.setdefault("user", None)
st.session_state.setdefault("pool", [])
st.session_state.setdefault("master", pd.DataFrame())

# ================= LOGIN (REPLIT SAFE) =================
st.sidebar.title("Login / Signup")

tab1, tab2 = st.sidebar.tabs(["Login", "Signup"])

with tab1:
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Login"):
        if login_user(u, p):
            st.session_state.logged_in = True
            st.session_state.user = u
            st.success("Login successful")
            st.rerun()
        else:
            st.error("Invalid login")

with tab2:
    new_u = st.text_input("New Username")
    new_p = st.text_input("New Password", type="password")
    if st.button("Create Account"):
        if create_user(new_u, new_p):
            st.success("Account created! Now login.")
        else:
            st.error("User already exists")

if not st.session_state.get("logged_in", False):
    st.warning("Please login to continue")
    st.stop()

# ================= MENU =================
menu = st.sidebar.radio("Menu", ["Upload", "Clean & Export", "Advanced"])

# ================= UPLOAD =================
if menu == "Upload":
    # Restricted types to prevent OCR errors with PDFs
    files = st.file_uploader("Upload Files", accept_multiple_files=True, type=['csv', 'xlsx', 'png', 'jpg', 'jpeg'])

    if files:
        for f in files:
            if f.name not in [x["name"] for x in st.session_state.pool]:
                try:
                    if f.name.endswith(".csv"):
                        df = pd.read_csv(f)
                    elif f.name.endswith((".xlsx", ".xls")):
                        df = pd.read_excel(f, engine="openpyxl")
                    elif f.type in ["image/png", "image/jpeg", "image/jpg"]:
                        df = vision_extract(f)
                    else:
                        st.warning(f"Skipped {f.name}: Unsupported type.")
                        continue

                    st.session_state.pool.append({
                        "name": f.name,
                        "data": df,
                        "selected": True
                    })
                    st.success(f"Loaded: {f.name}")
                except Exception as e:
                    st.error(f"Could not read '{f.name}': {e}")

    if st.session_state.pool:
        st.subheader("Select Files to Include")
        selected = []
        for i, item in enumerate(st.session_state.pool):
            item["selected"] = st.checkbox(item["name"], value=item["selected"], key=f"check_{i}")
            if item["selected"]:
                selected.append(item["data"])

        if selected:
            st.session_state.master = pd.concat(selected, ignore_index=True)
            st.dataframe(st.session_state.master.head(20))

    if st.button("Clear All Files"):
        st.session_state.pool = []
        st.session_state.master = pd.DataFrame()
        st.rerun()

# ================= CLEAN & EXPORT =================
elif menu == "Clean & Export":
    # Check if master dataframe exists and is not empty
    if st.session_state.master.empty:
        st.warning("⚠️ No data available. Please upload and select files first.")
        st.stop()

    df = st.session_state.master

    if st.button("Auto Clean"):
        # Create a deep copy to process
        cleaned_df = df.copy()
        
        # 1. Remove truly empty rows and duplicates
        cleaned_df = cleaned_df.drop_duplicates().dropna(how='all')
        
        # 2. Specific cleaning for 'Missing Data Indicator' if it exists in your CSV
        if 'Missing Data Indicator' in cleaned_df.columns:
            cleaned_df = cleaned_df[cleaned_df['Missing Data Indicator'] == False]
        
        # 3. Run validation flags
        cleaned_df = validate(cleaned_df)
        
        st.session_state.master = cleaned_df
        st.success("Cleaning complete!")
        st.rerun()

    st.subheader("Edit Data Manually")
    edited_df = st.data_editor(st.session_state.master)

    if st.button("Save Edits & Revalidate"):
        st.session_state.master = validate(edited_df)
        st.success("Changes saved!")
        st.rerun()

    st.divider()
    
    # Download logic
    if "needs_review" in edited_df.columns:
        clean_only = edited_df[~edited_df["needs_review"]]
        st.download_button("Download Clean Data (CSV)", clean_only.to_csv(index=False), "clean_data.csv")
        st.info(f"Showing {len(clean_only)} clean rows for download.")
    else:
        st.download_button("Download All Data (CSV)", edited_df.to_csv(index=False), "data.csv")

# ================= ADVANCED =================
elif menu == "Advanced":
    dfs = [x["data"] for x in st.session_state.pool if x["selected"]]

    if len(dfs) >= 2:
        st.subheader("Combine Datasets")
        df1_idx = st.selectbox("Select First Dataset", range(len(dfs)), format_func=lambda x: f"Dataset {x+1}")
        df2_idx = st.selectbox("Select Second Dataset", range(len(dfs)), format_func=lambda x: f"Dataset {x+1}")
        
        df1, df2 = dfs[df1_idx], dfs[df2_idx]
        common = list(set(df1.columns) & set(df2.columns))
        
        if common:
            key = st.selectbox("Join on Column", common)
            if st.button("Run Join"):
                st.session_state.master = df1.merge(df2, on=key)
                st.success("Datasets joined!")
                st.dataframe(st.session_state.master)
        else:
            st.error("No common columns found to join these datasets.")
    else:
        st.info("Upload and select at least 2 files to use Advanced Join features.")

print("ULTRA STABLE APP READY 🚀")
