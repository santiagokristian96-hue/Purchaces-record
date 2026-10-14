import io
import json
from datetime import datetime
from pathlib import Path
import requests
import streamlit as st
from bs4 import BeautifulSoup
import urllib3
import base64
import os
from supabase import create_client, Client

# ReportLab imports for PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ========================================
# CONFIGURACIÓN DE SUPABASE (SIN SECRETOS)
# ========================================
NG_SUPABASE_URL = "https://aswdqhmityjxyerblsfo.supabase.co"
NG_SUPABASE_KEY = "sb_publishable_zOQEgkqE7PcpsqTOFUWN2w_Om3JjrxJ"

try:
    supabase: Client = create_client(NG_SUPABASE_URL, NG_SUPABASE_KEY)
except Exception:
    supabase = None

# =====================
# CÓDIGO LOGO
# =====================
logo_NG = "logo.txt"
if os.path.exists(logo_NG):
    with open(logo_NG, "r") as f:
        NG_LOGO_BASE64 = f.read().strip()
else:
    NG_LOGO_BASE64 = ""

# Web Page Configuration
st.set_page_config(
    page_title="Weekly Budget Record",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Dark Mode / High Contrast CSS Styles
st.markdown(
    """
<style>
    .stApp {
        background-color: #0e1117;
        color: #ffffff;
    }
    .metric-card {
        background-color: #1e222d;
        border: 1px solid #2b3245;
        border-radius: 10px;
        padding: 15px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
    }
    .metric-title {
        color: #8b9bb4;
        font-size: 14px;
        font-weight: 500;
    }
    .metric-value {
        color: #00d2ff;
        font-size: 22px;
        font-weight: bold;
    }
    .metric-sub {
        color: #00ff88;
        font-size: 14px;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ------------------------------------
# FUNCTIONS & EXCHANGE RATE FETCHING
# ------------------------------------
@st.cache_data(ttl=600)
def fetch_online_usdt_rate() -> float:
    try:
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Content-Type": "application/json",
        }
        payload = {
            "asset": "USDT",
            "fiat": "VES",
            "merchantCheck": False,
            "page": 1,
            "payTypes": [],
            "publisherType": None,
            "rows": 5,
            "tradeType": "BUY",
        }
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("data"):
                prices = [float(adv["adv"]["price"]) for adv in data["data"]]
                if prices:
                    return round(sum(prices) / len(prices), 2)
    except Exception:
        pass

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://alcambio.app/", headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.content, "html.parser")
            next_data = soup.find("script", id="__NEXT_DATA__")
            if next_data and next_data.string:
                data = json.loads(next_data.string)
                rates = data.get("props", {}).get("pageProps", {}).get("rates", [])
                for rate in rates:
                    name = str(rate.get("source", "")).lower()
                    if "binance" in name or "usdt" in name:
                        return float(rate.get("rate", 0))
    except Exception:
        pass

    return 100.00


def get_current_real_week() -> int:
    current_iso_week = datetime.now().isocalendar()[1]
    return max(41, current_iso_week)


def load_data():
    if supabase is not None:
        try:
            response = supabase.table("app_data").select("content").eq("id", 1).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]["content"]
        except Exception:
            pass

    if "local_data_store" not in st.session_state:
        st.session_state["local_data_store"] = {"semanas": [], "pending_purchases": []}
    return st.session_state["local_data_store"]


def save_data(data):
    st.session_state["local_data_store"] = data
    if supabase is not None:
        try:
            supabase.table("app_data").upsert({"id": 1, "content": data}).execute()
        except Exception as e:
            st.warning(f"Note: Saved locally. Supabase sync error: {e}")


def get_or_create_week(data, week_num, base_budget=25.0, initial_savings=60.0):
    for sem in data["semanas"]:
        if sem["numero"] == week_num:
            if "budget_funded" not in sem:
                sem["budget_funded"] = False
            return sem

    valid_weeks = [s for s in data["semanas"] if s["numero"] >= 41]

    if not valid_weeks:
        rollover = initial_savings
    else:
        prev = valid_weeks[-1]
        rate = st.session_state.get("tasa_usdt", 100.00)
        spent_usdt = prev["total_gastado"] / rate if rate > 0 else 0
        
        prev_is_funded = prev.get("budget_funded", False)
        prev_base = prev["presupuesto_base"] if prev_is_funded else 0.0
        prev_available = prev_base + prev["remanente_anterior"]
        rollover = prev_available - spent_usdt

    new_week = {
        "numero": week_num,
        "presupuesto_base": base_budget,
        "remanente_anterior": rollover,
        "budget_funded": False,
        "presupuesto_disponible": rollover,
        "gastos": [],
        "total_gastado": 0.0,
    }
    data["semanas"].append(new_week)
    save_data(data)
    return new_week


def generate_pdf_report(week_data, rate):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        "DocTitle", parent=styles["Title"], fontSize=18, leading=22, textColor=colors.HexColor("#1e222d")
    )
    sub_style = ParagraphStyle(
        "DocSub", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#555555")
    )

    story.append(Paragraph("NEXTGLOBAL - WEEKLY EXPENSE REPORT", title_style))
    story.append(Paragraph(f"Week {week_data['numero']} | Date Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", sub_style))
    story.append(Paragraph(f"USDT Exchange Rate: <b>VES {rate:.2f}</b>", sub_style))
    story.append(Spacer(1, 15))

    is_funded = week_data.get("budget_funded", False)
    funded_text = "Funded" if is_funded else "Not Funded"
    total_spent_usdt = week_data["total_gastado"] / rate if rate > 0 else 0.0
    rem_usdt = week_data["presupuesto_disponible"] - total_spent_usdt
    rem_ves = rem_usdt * rate

    summary_data = [
        ["Weekly Budget", "Rollover / Savings", "Status", "Total Spent", "Available Balance"],
        [
            f"${week_data['presupuesto_base']:.2f} USDT",
            f"${week_data['remanente_anterior']:.2f} USDT",
            funded_text,
            f"${total_spent_usdt:.2f} USDT\n(VES {week_data['total_gastado']:.2f})",
            f"${rem_usdt:.2f} USDT\n(VES {rem_ves:.2f})",
        ],
    ]

    summary_table = Table(summary_data, colWidths=[100, 110, 80, 120, 130])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e222d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f4f6f9")),
                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#cccccc")),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 20))

    story.append(Paragraph("<b>Expenses Breakdown</b>", styles["Heading2"]))
    story.append(Spacer(1, 8))

    expenses = week_data.get("gastos", [])
    if not expenses:
        story.append(Paragraph("No expenses recorded for this week.", styles["Normal"]))
    else:
        item_table_data = [["#", "Item / Service Name", "Price (VES)", "Price (USDT)", "Receipts", "Date & Time"]]
        for idx, g in enumerate(expenses, 1):
            p_usdt = g.get("precio_usdt", g["precio"] / rate if rate > 0 else 0)
            receipts = g.get("facturas", [g.get("factura")] if g.get("factura") else [])
            receipts = [r for r in receipts if r]
            att_count = f"{len(receipts)} file(s)" if receipts else "None"
            item_table_data.append([
                str(idx),
                g["producto"],
                f"VES {g['precio']:.2f}",
                f"${p_usdt:.2f}",
                att_count,
                g["fecha"],
            ])

        expense_table = Table(item_table_data, colWidths=[25, 180, 90, 80, 65, 100])
        expense_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b3245")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("ALIGN", (0, 0), (0, -1), "CENTER"),
                    ("ALIGN", (2, 0), (3, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ]
            )
        )
        story.append(expense_table)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ------------------------------------
# STATE & AUTHENTICATION INITIALIZATION
# ------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if "tasa_usdt" not in st.session_state:
    st.session_state["tasa_usdt"] = fetch_online_usdt_rate()

real_current_week = get_current_real_week()

if "input_week_number" not in st.session_state:
    st.session_state["input_week_number"] = real_current_week

data = load_data()

# ------------------------------------
# LOGIN SCREEN (IF NOT AUTHENTICATED)
# ------------------------------------
if not st.session_state["authenticated"]:
    if NG_LOGO_BASE64:
        st.markdown(
            f'<div style="text-align: center; margin-bottom: 20px;"><img src="data:image/png;base64,{NG_LOGO_BASE64}" width="180"></div>',
            unsafe_allow_html=True,
        )

    st.title("🔒 Weekly Budget Record")
    st.subheader("Welcome to Nextglobal Portal")

    col_login, col_pending = st.columns([1, 1.2], gap="large")

    with col_login:
        st.markdown("### 🔑 System Access")
        with st.form("login_form"):
            st.text_input("Username:", value="Nextglobal", disabled=True)
            password_input = st.text_input("Password:", type="password")
            btn_login = st.form_submit_button("🔓 Log In")

            if btn_login:
                if password_input == "Ng90071":
                    st.session_state["authenticated"] = True
                    st.success("✅ Login successful!")
                    st.rerun()
                else:
                    st.error("❌ Incorrect password. Please try again.")

    with col_pending:
        st.markdown("### 🛒 Pending Purchases List")
        st.caption("View and register items or needs before logging into full system.")

        with st.form("public_add_pending", clear_on_submit=True):
            pub_item_name = st.text_input("Item Name / Need:")
            pub_item_prio = st.selectbox("Priority Level:", ["High", "Medium", "Low"])
            pub_add_btn = st.form_submit_button("➕ Add Pending Item")

            if pub_add_btn:
                if pub_item_name.strip():
                    if "pending_purchases" not in data:
                        data["pending_purchases"] = []
                    data["pending_purchases"].append(
                        {
                            "item": pub_item_name,
                            "priority": pub_item_prio,
                            "notes": "",
                            "date_added": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )
                    save_data(data)
                    st.success(f"Added '{pub_item_name}' to list!")
                    st.rerun()
                else:
                    st.error("Please enter an item name.")

        st.markdown("---")
        pending_items_pub = data.get("pending_purchases", [])
        if not pending_items_pub:
            st.info("No pending items registered yet.")
        else:
            table_pub = []
            for i, p_item in enumerate(pending_items_pub, 1):
                prio_icon = "🔴" if p_item["priority"] == "High" else "🟡" if p_item["priority"] == "Medium" else "🟢"
                table_pub.append(
                    {
                        "#": i,
                        "Item": p_item["item"],
                        "Priority": f"{prio_icon} {p_item['priority']}",
                        "Date Added": p_item["date_added"],
                    }
                )
            st.dataframe(table_pub, use_container_width=True)

            pub_del_options = [f"{i+1}. {it['item']}" for i, it in enumerate(pending_items_pub)]
            pub_selected_del = st.selectbox("Remove resolved item:", options=pub_del_options, key="pub_del_select")
            if st.button("🗑️ Remove Selected Item"):
                idx_to_del = pub_del_options.index(pub_selected_del)
                removed = data["pending_purchases"].pop(idx_to_del)
                save_data(data)
                st.success(f"Removed '{removed['item']}'.")
                st.rerun()

    st.stop()


# ------------------------------------
# MAIN APPLICATION (AUTHENTICATED USER)
# ------------------------------------

if NG_LOGO_BASE64:
    st.sidebar.markdown(
        f'<div style="text-align: center; margin-bottom: 15px;"><img src="data:image/png;base64,{NG_LOGO_BASE64}" width="140"></div>',
        unsafe_allow_html=True,
    )

st.sidebar.title("⚙️ Settings")
st.sidebar.markdown(f"🪙 **USDT Rate:** `VES {st.session_state['tasa_usdt']:.2f}`")

st.sidebar.caption(f"📅 Real Current Week: **Week {real_current_week}**")

if st.sidebar.button("📅 Sync to Real Current Week"):
    st.session_state["input_week_number"] = real_current_week
    st.rerun()

week_num = st.sidebar.number_input(
    "Select Week:",
    min_value=41,
    step=1,
    key="input_week_number",
)

current_week = get_or_create_week(data, week_num)

# --- SIDEBAR PENDING PURCHASES / INVENTORY ---
st.sidebar.markdown("---")
st.sidebar.subheader("🛒 Pending Purchases")

with st.sidebar.expander("➕ Add Pending Item"):
    with st.form("sb_add_form", clear_on_submit=True):
        sb_item_name = st.text_input("Item Name:")
        sb_item_prio = st.selectbox("Priority:", ["High", "Medium", "Low"])
        sb_submitted = st.form_submit_button("Add to List")
        if sb_submitted:
            if sb_item_name.strip():
                if "pending_purchases" not in data:
                    data["pending_purchases"] = []
                data["pending_purchases"].append(
                    {
                        "item": sb_item_name,
                        "priority": sb_item_prio,
                        "notes": "",
                        "date_added": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
                save_data(data)
                st.success("Added!")
                st.rerun()

pending_items = data.get("pending_purchases", [])
if not pending_items:
    st.sidebar.caption("No pending items.")
else:
    for idx, p_item in enumerate(pending_items):
        prio_color = "🔴" if p_item["priority"] == "High" else "🟡" if p_item["priority"] == "Medium" else "🟢"
        st.sidebar.markdown(f"{prio_color} **{p_item['item']}**")

    sb_del_options = [f"{i+1}. {it['item']}" for i, it in enumerate(pending_items)]
    sb_selected_del = st.sidebar.selectbox("Remove item:", options=sb_del_options, key="sb_del_select")
    if st.sidebar.button("🗑️ Remove Selected Item"):
        idx_to_del = sb_del_options.index(sb_selected_del)
        data["pending_purchases"].pop(idx_to_del)
        save_data(data)
        st.success("Removed!")
        st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("🚪 Log Out", type="secondary"):
    st.session_state["authenticated"] = False
    st.rerun()

# ------------------------------------
# HEADER & PROMINENT EXCHANGE RATE BANNER
# ------------------------------------
st.title("💰 Weekly Budget Record")

current_rate = st.session_state["tasa_usdt"]

st.markdown(
    f"""
    <div style="background: linear-gradient(135deg, #1e222d 0%, #2b3245 100%); border: 2px solid #00d2ff; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);">
        <div style="color: #8b9bb4; font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px;">Live USDT / VES Exchange Rate (Binance P2P)</div>
        <div style="color: #00d2ff; font-size: 32px; font-weight: bold; margin-top: 4px;">VES {current_rate:.2f}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------
# FUNDING CONTROL BUTTON
# ------------------------------------
is_funded = current_week.get("budget_funded", False)

c_fund1, c_fund2 = st.columns([1, 3])

with c_fund1:
    if not is_funded:
        if st.button(f"➕ Fund Week (+{current_week['presupuesto_base']:.2f} USDT)", type="primary", use_container_width=True):
            current_week["budget_funded"] = True
            save_data(data)
            st.rerun()
    else:
        if st.button(f"➖ Unfund Week (-{current_week['presupuesto_base']:.2f} USDT)", type="secondary", use_container_width=True):
            current_week["budget_funded"] = False
            save_data(data)
            st.rerun()

with c_fund2:
    if is_funded:
        st.info("✅ **Status:** Weekly Budget transferred & added to Available Balance.")
    else:
        st.caption("ℹ️ **Status:** Weekly Budget not funded yet. Click the button on the left when you receive the transfer.")

st.markdown("<br>", unsafe_allow_html=True)

# ------------------------------------
# CALCULATE METRICS
# ------------------------------------
is_funded = current_week.get("budget_funded", False)
base_amount = current_week["presupuesto_base"] if is_funded else 0.0
current_week["presupuesto_disponible"] = base_amount + current_week["remanente_anterior"]

total_spent_usdt = current_week["total_gastado"] / current_rate if current_rate > 0 else 0.0
remaining_balance_usdt = current_week["presupuesto_disponible"] - total_spent_usdt
remaining_balance_ves = remaining_balance_usdt * current_rate

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(
        f"""
    <div class="metric-card">
        <div class="metric-title">Weekly Budget</div>
        <div class="metric-value">{current_week['presupuesto_base']:.2f} USDT</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

with col2:
    st.markdown(
        f"""
    <div class="metric-card">
        <div class="metric-title">Rollover / Savings</div>
        <div class="metric-value">{current_week['remanente_anterior']:.2f} USDT</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

with col3:
    st.markdown(
        f"""
    <div class="metric-card">
        <div class="metric-title">Total Spent</div>
        <div class="metric-value" style="color: #ff5555;">{total_spent_usdt:.2f} USDT</div>
        <div class="metric-title">VES {current_week['total_gastado']:.2f}</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

with col4:
    st.markdown(
        f"""
    <div class="metric-card">
        <div class="metric-title">Available Balance</div>
        <div class="metric-value" style="color: #00ff88;">{remaining_balance_usdt:.2f} USDT</div>
        <div class="metric-sub">VES {remaining_balance_ves:.2f}</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# ------------------------------------
# MAIN TABS
# ------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📝 Record Expense",
        "📊 Weekly Summary",
        "✏️ Edit Expense",
        "⚙️ Settings",
    ]
)

# --- TAB 1: RECORD EXPENSE ---
with tab1:
    st.subheader(f"Record Expense - Week {week_num}")
    with st.form("form_compra", clear_on_submit=True):
        product_name = st.text_input("Item or Service Name:")
        price_ves = st.number_input("Price in Bolivars (VES):", min_value=0.0, step=0.5)
        receipt_files = st.file_uploader(
            "Attach Invoices / Receipts (up to 3 files):",
            type=["png", "jpg", "jpeg", "pdf"],
            accept_multiple_files=True,
        )

        if receipt_files:
            if len(receipt_files) > 3:
                st.warning("⚠️ Maximum 3 files allowed. Only the first 3 will be saved.")
                receipt_files = receipt_files[:3]

            cols_prev = st.columns(len(receipt_files))
            for idx_f, rf in enumerate(receipt_files):
                ext_preview = Path(rf.name).suffix.lower()
                with cols_prev[idx_f]:
                    if ext_preview in [".png", ".jpg", ".jpeg"]:
                        st.image(rf, caption=f"Preview {idx_f+1}", width=120)

        btn_save = st.form_submit_button("💾 Save Expense")

        if btn_save:
            if not product_name.strip():
                st.error("Please enter a product or service name.")
            elif price_ves <= 0:
                st.error("Price must be greater than 0.")
            else:
                receipt_filenames = []
                if receipt_files:
                    for rf in receipt_files[:3]:
                        ext = Path(rf.name).suffix
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        r_name = f"receipt_wk{week_num}_{timestamp}{ext}"
                        
                        if supabase is not None:
                            try:
                                file_bytes = rf.getvalue()
                                supabase.storage.from_("receipts").upload(
                                    r_name, file_bytes, file_options={"upsert": "true"}
                                )
                            except Exception:
                                pass
                        receipt_filenames.append(r_name)

                p_usdt = round(price_ves / current_rate, 2) if current_rate > 0 else 0.0
                expense = {
                    "producto": product_name,
                    "precio": price_ves,
                    "precio_usdt": p_usdt,
                    "factura": receipt_filenames[0] if receipt_filenames else None,
                    "facturas": receipt_filenames,
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                current_week["gastos"].append(expense)
                current_week["total_gastado"] += price_ves
                save_data(data)
                st.success(f"✅ Registered '{product_name}' for VES {price_ves:.2f} ({p_usdt:.2f} USDT)")
                st.rerun()

# --- TAB 2: SUMMARY & HISTORY ---
with tab2:
    st.subheader(f"Expense History & Exports - Week {week_num}")
    
    col_pdf, col_csv, _ = st.columns([1.2, 1.2, 2.6])
    with col_pdf:
        try:
            pdf_bytes = generate_pdf_report(current_week, current_rate)
            st.download_button(
                label="📄 Download Weekly PDF Report",
                data=pdf_bytes,
                file_name=f"Expense_Report_Week_{week_num}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Could not generate PDF: {e}")

    with col_csv:
        if current_week["gastos"]:
            csv_lines = ["Item / Service,Price (VES),Price (USDT),Date & Time"]
            for g in current_week["gastos"]:
                p_usdt = g.get("precio_usdt", g["precio"] / current_rate if current_rate > 0 else 0)
                csv_lines.append(f'"{g["producto"]}",{g["precio"]:.2f},{p_usdt:.2f},"{g["fecha"]}"')
            csv_data = "\n".join(csv_lines)
            st.download_button(
                label="📊 Download CSV Data",
                data=csv_data,
                file_name=f"Expenses_Week_{week_num}.csv",
                mime="text/csv",
                use_container_width=True,
            )

    st.markdown("---")

    if not current_week["gastos"]:
        st.info("No expenses recorded for this week.")
    else:
        table_data = []
        for i, g in enumerate(current_week["gastos"], 1):
            p_usdt = g.get("precio_usdt", g["precio"] / current_rate if current_rate > 0 else 0)
            list_f = g.get("facturas", [g.get("factura")] if g.get("factura") else [])
            list_f = [r for r in list_f if r]
            att_desc = f"{len(list_f)} file(s)" if list_f else "No attachment"
            
            table_data.append(
                {
                    "#": i,
                    "Item / Service": g["producto"],
                    "Price (VES)": f"VES {g['precio']:.2f}",
                    "Price (USDT)": f"{p_usdt:.2f} USDT",
                    "Receipts": att_desc,
                    "Date & Time": g["fecha"],
                }
            )
        st.dataframe(table_data, use_container_width=True)

        expenses_with_receipts = [
            g for g in current_week["gastos"]
            if g.get("facturas") or g.get("factura")
        ]
        if expenses_with_receipts:
            st.markdown("---")
            st.subheader("📎 View Attached Receipts")
            receipt_options = [f"{g['producto']} (VES {g['precio']:.2f})" for g in expenses_with_receipts]
            selected_receipt_item = st.selectbox(
                "Select an expense to inspect its receipts:",
                options=receipt_options,
                key="select_receipt_summary",
            )

            idx_rec = receipt_options.index(selected_receipt_item)
            item_selected = expenses_with_receipts[idx_rec]
            rec_files = item_selected.get("facturas", [item_selected.get("factura")] if item_selected.get("factura") else [])
            rec_files = [r for r in rec_files if r]

            if rec_files:
                cols_rec = st.columns(len(rec_files))
                for r_idx, rec_filename in enumerate(rec_files):
                    with cols_rec[r_idx]:
                        try:
                            if supabase is not None:
                                public_url = supabase.storage.from_("receipts").get_public_url(rec_filename)
                                ext_file = Path(rec_filename).suffix.lower()
                                if ext_file in [".png", ".jpg", ".jpeg"]:
                                    st.image(public_url, caption=f"File {r_idx+1}", width=150)
                                elif ext_file == ".pdf":
                                    file_res = supabase.storage.from_("receipts").download(rec_filename)
                                    st.download_button(
                                        label=f"📄 PDF {r_idx+1}",
                                        data=file_res,
                                        file_name=rec_filename,
                                        mime="application/pdf",
                                    )
                        except Exception as e:
                            st.error(f"Error loading file: {e}")

# --- TAB 3: EDIT EXPENSE ---
with tab3:
    st.subheader(f"Edit Expense - Week {week_num}")
    if not current_week["gastos"]:
        st.info("No expenses recorded for this week to edit.")
    else:
        expense_options_edit = [f"{i+1}. {g['producto']} (VES {g['precio']:.2f})" for i, g in enumerate(current_week["gastos"])]
        selected_expense_edit = st.selectbox(
            "Select expense to edit:",
            options=expense_options_edit,
            key="select_edit_expense",
        )

        idx_edit = expense_options_edit.index(selected_expense_edit)
        target_expense = current_week["gastos"][idx_edit]

        current_receipts = target_expense.get("facturas", [target_expense.get("factura")] if target_expense.get("factura") else [])
        current_receipts = [r for r in current_receipts if r]

        if current_receipts:
            st.markdown("##### 📎 Current Attached Receipts:")
            cols_edit_prev = st.columns(len(current_receipts))
            for cr_idx, cr_file in enumerate(current_receipts):
                with cols_edit_prev[cr_idx]:
                    try:
                        if supabase is not None:
                            public_url_edit = supabase.storage.from_("receipts").get_public_url(cr_file)
                            ext_edit = Path(cr_file).suffix.lower()
                            if ext_edit in [".png", ".jpg", ".jpeg"]:
                                st.image(public_url_edit, width=130)
                            elif ext_edit == ".pdf":
                                file_res_edit = supabase.storage.from_("receipts").download(cr_file)
                                st.download_button(
                                    label=f"📄 Download PDF {cr_idx+1}",
                                    data=file_res_edit,
                                    file_name=cr_file,
                                    mime="application/pdf",
                                )
                    except Exception:
                        pass

        with st.form("form_edit_compra
