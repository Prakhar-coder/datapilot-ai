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

# ================= VALIDATION =================
def validate(df):
    df = df.copy()
    df["Total_Amount"] = pd.to_numeric(df.get("Total_Amount"), errors="coerce")
    df["Date"] = pd.to_datetime(df.get("Date"), errors="coerce")

    df["flag_amount"] = df["Total_Amount"].isna() | (df["Total_Amount"] <= 0)
    df["flag_vendor"] = df.get("Vendor_Name").isna()
    df["flag_bill"] = df.get("Bill_Number").isna()
    df["flag_date"] = df["Date"].isna()

    df["needs_review"] = df[["flag_amount","flag_vendor","flag_bill","flag_date"]].any(axis=1)
    return df

# ================= SESSION =================
st.session_state.setdefault("logged_in", False)
st.session_state.setdefault("user", None)
st.session_state.setdefault("pool", [])
st.session_state.setdefault("master", pd.DataFrame())

# ================= LOGIN (REPLIT SAFE) =================
st.sidebar.title("Login")

u = st.sidebar.text_input("Username")
p = st.sidebar.text_input("Password", type="password")

if st.sidebar.button("Login"):
    if login_user(u, p):
        st.session_state.logged_in = True
        st.session_state.user = u
        st.sidebar.success("Login successful")
    else:
        st.sidebar.error("Invalid login")

if not st.session_state.logged_in:
    st.warning("Please login to continue")
    st.stop()

st.sidebar.success(f"Welcome {st.session_state.user}")

# ================= MENU =================
menu = st.sidebar.radio("Menu", ["Upload","Clean & Export","Advanced"])

# ================= UPLOAD =================
if menu == "Upload":
    files = st.file_uploader("Upload Files", accept_multiple_files=True)

    if files:
        for f in files:
            if f.name not in [x["name"] for x in st.session_state.pool]:
                try:
                    if f.name.endswith(".csv"):
                        df = pd.read_csv(f)
                    elif f.name.endswith(".xlsx"):
                        df = pd.read_excel(f, engine="openpyxl")
                    else:
                        df = vision_extract(f)

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
            item["selected"] = st.checkbox(item["name"], value=item["selected"], key=i)
            if item["selected"]:
                selected.append(item["data"])

        if selected:
            st.session_state.master = pd.concat(selected, ignore_index=True)
            st.dataframe(st.session_state.master.head(20))

    if st.button("Clear All Files"):
        st.session_state.pool = []
        st.session_state.master = pd.DataFrame()

# ================= CLEAN =================
elif menu == "Clean & Export":
    df = st.session_state.master

    if df.empty:
        st.warning("Upload data first")
        st.stop()

    if st.button("Auto Clean"):
        df = df.drop_duplicates().dropna()
        df = validate(df)
        st.session_state.master = df

    edited = st.data_editor(df)

    if st.button("Revalidate"):
        edited = validate(edited)
        st.session_state.master = edited

    if "needs_review" in edited.columns:
        clean = edited[~edited["needs_review"]]
        st.download_button("Download Clean CSV", clean.to_csv(index=False), "clean_data.csv")
    else:
        st.info("Click 'Auto Clean' first to validate and filter rows before downloading.")
        st.download_button("Download All as CSV", edited.to_csv(index=False), "data.csv")

# ================= ADVANCED =================
elif menu == "Advanced":
    dfs = [x["data"] for x in st.session_state.pool]

    if len(dfs) >= 2:
        st.subheader("Combine using common column")

        df1 = st.selectbox("Dataset 1", dfs)
        df2 = st.selectbox("Dataset 2", dfs)

        common = list(set(df1.columns) & set(df2.columns))
        key = st.selectbox("Column", common if common else df1.columns)

        if st.button("Run Join"):
            st.session_state.master = df1.merge(df2, on=key)
            st.dataframe(st.session_state.master)

print("ULTRA STABLE APP READY 🚀")
