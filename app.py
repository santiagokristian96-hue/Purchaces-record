import json
from datetime import datetime
from pathlib import Path
import requests
import streamlit as st
from bs4 import BeautifulSoup
import urllib3
from supabase import create_client, Client

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
# SUPABASE CONNECTION SETUP
# ------------------------------------
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(
        "⚠️ Error connecting to Supabase. Please configure SUPABASE_URL and SUPABASE_KEY in Streamlit Secrets."
    )
    st.stop()


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
                rates = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("rates", [])
                )
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
    try:
        response = (
            supabase.table("app_data")
            .select("content")
            .eq("id", 1)
            .execute()
        )
        if response.data and len(response.data) > 0:
            return response.data[0]["content"]
    except Exception:
        pass

    default_data = {"semanas": [], "pending_purchases": []}
    save_data(default_data)
    return default_data


def save_data(data):
    try:
        supabase.table("app_data").upsert(
            {"id": 1, "content": data}
        ).execute()
    except Exception as e:
        st.error(f"Error saving data to Supabase: {e}")


def get_or_create_week(
    data, week_num, base_budget=25.0, initial_savings=60.0
):
    for sem in data["semanas"]:
        if sem["numero"] == week_num:
            if "budget_funded" not in sem:
                sem["budget_funded"] = False
            active_base = (
                sem["presupuesto_base"] if sem["budget_funded"] else 0.0
            )
            sem["presupuesto_disponible"] = (
                active_base + sem["remanente_anterior"]
            )
            return sem

    valid_weeks = [s for s in data["semanas"] if s["numero"] >= 41]

    if not valid_weeks:
        rollover = initial_savings
    else:
        prev = valid_weeks[-1]
        rate = st.session_state.get("tasa_usdt", 100.00)
        spent_usdt = prev["total_gastado"] / rate if rate > 0 else 0
        rollover = prev["presupuesto_disponible"] - spent_usdt

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
                            "date_added": datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
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
                prio_icon = (
                    "🔴"
                    if p_item["priority"] == "High"
                    else "🟡"
                    if p_item["priority"] == "Medium"
                    else "🟢"
                )
                table_pub.append(
                    {
                        "#": i,
                        "Item": p_item["item"],
                        "Priority": f"{prio_icon} {p_item['priority']}",
                        "Date Added": p_item["date_added"],
                    }
                )
            st.dataframe(table_pub, use_container_width=True)

            pub_del_options = [
                f"{i+1}. {it['item']}" for i, it in enumerate(pending_items_pub)
            ]
            pub_selected_del = st.selectbox(
                "Remove resolved item:", options=pub_del_options, key="pub_del_select"
            )
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

st.sidebar.title("⚙️ Settings")
st.sidebar.markdown(
    f"🪙 **USDT Rate:** `VES {st.session_state['tasa_usdt']:.2f}`"
)

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
                        "date_added": datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
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
        prio_color = (
            "🔴"
            if p_item["priority"] == "High"
            else "🟡"
            if p_item["priority"] == "Medium"
            else "🟢"
        )
        st.sidebar.markdown(f"{prio_color} **{p_item['item']}**")

    sb_del_options = [
        f"{i+1}. {it['item']}" for i, it in enumerate(pending_items)
    ]
    sb_selected_del = st.sidebar.selectbox(
        "Remove item:", options=sb_del_options, key="sb_del_select"
    )
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

# RECALCULATE AVAILABLE BALANCE DYNAMICALLY
is_funded = current_week.get("budget_funded", False)
base_amount = current_week["presupuesto_base"] if is_funded else 0.0
current_week["presupuesto_disponible"] = base_amount + current_week["remanente_anterior"]

total_spent_usdt = (
    current_week["total_gastado"] / current_rate if current_rate > 0 else 0.0
)
remaining_balance_usdt = (
    current_week["presupuesto_disponible"] - total_spent_usdt
)
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

# ------------------------------------
# DIRECT FUNDING CONTROL BUTTON NEAR BALANCE
# ------------------------------------
st.markdown("<br>", unsafe_allow_html=True)
c_fund1, c_fund2 = st.columns([1, 3])

with c_fund1:
    if not is_funded:
        if st.button(f"➕ Fund Week (+{current_week['presupuesto_base']:.2f} USDT)", type="primary", use_container_width=True):
            current_week["budget_funded"] = True
            save_data(data)
            st.success(f"Added +{current_week['presupuesto_base']:.2f} USDT to Available Balance!")
            st.rerun()
    else:
        if st.button(f"➖ Unfund Week (-{current_week['presupuesto_base']:.2f} USDT)", type="secondary", use_container_width=True):
            current_week["budget_funded"] = False
            save_data(data)
            st.warning(f"Removed {current_week['presupuesto_base']:.2f} USDT from Available Balance.")
            st.rerun()

with c_fund2:
    if is_funded:
        st.info("✅ **Status:** Weekly Budget has been transferred & added to Available Balance.")
    else:
        st.caption("ℹ️ **Status:** Weekly Budget not funded yet. Click the button on the left when you receive the transfer.")

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
        price_ves = st.number_input(
            "Price in Bolivars (VES):", min_value=0.0, step=0.5
        )
        receipt_file = st.file_uploader(
            "Attach Invoice / Receipt (optional):",
            type=["png", "jpg", "jpeg", "pdf"],
        )

        if receipt_file is not None:
            ext_preview = Path(receipt_file.name).suffix.lower()
            if ext_preview in [".png", ".jpg", ".jpeg"]:
                st.image(receipt_file, caption="Receipt Preview", width=300)

        btn_save = st.form_submit_button("💾 Save Expense")

        if btn_save:
            if not product_name.strip():
                st.error("Please enter a product or service name.")
            elif price_ves <= 0:
                st.error("Price must be greater than 0.")
            else:
                receipt_filename = None
                if receipt_file is not None:
                    ext = Path(receipt_file.name).suffix
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    receipt_filename = f"receipt_wk{week_num}_{timestamp}{ext}"
                    
                    file_bytes = receipt_file.getvalue()
                    supabase.storage.from_("receipts").upload(
                        receipt_filename, file_bytes, file_options={"upsert": "true"}
                    )

                p_usdt = (
                    round(price_ves / current_rate, 2)
                    if current_rate > 0
                    else 0.0
                )
                expense = {
                    "producto": product_name,
                    "precio": price_ves,
                    "precio_usdt": p_usdt,
                    "factura": receipt_filename,
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                current_week["gastos"].append(expense)
                current_week["total_gastado"] += price_ves
                save_data(data)
                st.success(
                    f"✅ Registered '{product_name}' for VES {price_ves:.2f}"
                    f" ({p_usdt:.2f} USDT)"
                )
                st.rerun()

# --- TAB 2: SUMMARY & HISTORY ---
with tab2:
    st.subheader(f"Expense History - Week {week_num}")
    if not current_week["gastos"]:
        st.info("No expenses recorded for this week.")
    else:
        table_data = []
        for i, g in enumerate(current_week["gastos"], 1):
            p_usdt = g.get(
                "precio_usdt",
                g["precio"] / current_rate if current_rate > 0 else 0,
            )
            table_data.append(
                {
                    "#": i,
                    "Item / Service": g["producto"],
                    "Price (VES)": f"VES {g['precio']:.2f}",
                    "Price (USDT)": f"{p_usdt:.2f} USDT",
                    "Receipt": (
                        g["factura"] if g.get("factura") else "No attachment"
                    ),
                    "Date & Time": g["fecha"],
                }
            )
        st.dataframe(table_data, use_container_width=True)

        expenses_with_receipts = [
            g for g in current_week["gastos"] if g.get("factura")
        ]
        if expenses_with_receipts:
            st.markdown("---")
            st.subheader("📎 View Attached Receipts")
            receipt_options = [
                f"{g['producto']} (VES {g['precio']:.2f})"
                for g in expenses_with_receipts
            ]
            selected_receipt_item = st.selectbox(
                "Select an expense to inspect its receipt:",
                options=receipt_options,
                key="select_receipt_summary",
            )

            idx_rec = receipt_options.index(selected_receipt_item)
            rec_filename = expenses_with_receipts[idx_rec]["factura"]
            
            try:
                public_url = supabase.storage.from_("receipts").get_public_url(rec_filename)
                ext_file = Path(rec_filename).suffix.lower()
                if ext_file in [".png", ".jpg", ".jpeg"]:
                    st.image(
                        public_url,
                        caption=f"Receipt: {rec_filename}",
                        use_container_width=True,
                    )
                elif ext_file == ".pdf":
                    file_res = supabase.storage.from_("receipts").download(rec_filename)
                    st.download_button(
                        label=f"📄 Download PDF Receipt ({rec_filename})",
                        data=file_res,
                        file_name=rec_filename,
                        mime="application/pdf",
                    )
            except Exception as e:
                st.error(f"Could not load receipt file: {e}")

# --- TAB 3: EDIT EXPENSE ---
with tab3:
    st.subheader(f"Edit Expense - Week {week_num}")
    if not current_week["gastos"]:
        st.info("No expenses recorded for this week to edit.")
    else:
        expense_options_edit = [
            f"{i+1}. {g['producto']} (VES {g['precio']:.2f})"
            for i, g in enumerate(current_week["gastos"])
        ]
        selected_expense_edit = st.selectbox(
            "Select expense to edit:",
            options=expense_options_edit,
            key="select_edit_expense",
        )

        idx_edit = expense_options_edit.index(selected_expense_edit)
        target_expense = current_week["gastos"][idx_edit]

        current_receipt = target_expense.get("factura")
        if current_receipt:
            st.markdown("##### 📎 Current Attached Receipt:")
            try:
                public_url_edit = supabase.storage.from_("receipts").get_public_url(current_receipt)
                ext_edit = Path(current_receipt).suffix.lower()
                if ext_edit in [".png", ".jpg", ".jpeg"]:
                    st.image(public_url_edit, width=280)
                elif ext_edit == ".pdf":
                    file_res_edit = supabase.storage.from_("receipts").download(current_receipt)
                    st.download_button(
                        label="📄 Download Attached PDF Receipt",
                        data=file_res_edit,
                        file_name=current_receipt,
                        mime="application/pdf",
                    )
            except Exception:
                pass

        with st.form("form_edit_compra"):
            edit_product_name = st.text_input(
                "Item or Service Name:", value=target_expense["producto"]
            )
            edit_price_ves = st.number_input(
                "Price in Bolivars (VES):",
                min_value=0.0,
                value=float(target_expense["precio"]),
                step=0.5,
            )

            edit_receipt_file = st.file_uploader(
                "Replace Invoice / Receipt (optional):",
                type=["png", "jpg", "jpeg", "pdf"],
                key="uploader_edit_receipt",
            )

            btn_update = st.form_submit_button("💾 Save Changes")

            if btn_update:
                if not edit_product_name.strip():
                    st.error("Please enter a product or service name.")
                elif edit_price_ves <= 0:
                    st.error("Price must be greater than 0.")
                else:
                    receipt_filename = target_expense.get("factura")

                    if edit_receipt_file is not None:
                        ext = Path(edit_receipt_file.name).suffix
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        receipt_filename = f"receipt_wk{week_num}_{timestamp}{ext}"
                        file_bytes = edit_receipt_file.getvalue()
                        supabase.storage.from_("receipts").upload(
                            receipt_filename, file_bytes, file_options={"upsert": "true"}
                        )

                    old_price = target_expense["precio"]
                    current_week["total_gastado"] = (
                        current_week["total_gastado"]
                        - old_price
                        + edit_price_ves
                    )
                    if current_week["total_gastado"] < 0:
                        current_week["total_gastado"] = 0.0

                    p_usdt = (
                        round(edit_price_ves / current_rate, 2)
                        if current_rate > 0
                        else 0.0
                    )

                    target_expense["producto"] = edit_product_name
                    target_expense["precio"] = edit_price_ves
                    target_expense["precio_usdt"] = p_usdt
                    target_expense["factura"] = receipt_filename

                    save_data(data)
                    st.success(f"✅ Successfully updated '{edit_product_name}'.")
                    st.rerun()

# --- TAB 4: FINANCIAL SETTINGS ---
with tab4:
    st.subheader("⚙️ Financial Settings")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### 💵 Budget & Rollover")
        new_budget = st.number_input(
            "Weekly Budget ($ USDT):",
            min_value=0.0,
            value=float(current_week["presupuesto_base"]),
            step=5.0,
        )
        new_rollover = st.number_input(
            "Rollover / Savings ($ USDT):",
            min_value=0.0,
            value=float(current_week["remanente_anterior"]),
            step=5.0,
        )

        if st.button("Save Budget Changes"):
            current_week["presupuesto_base"] = new_budget
            current_week["remanente_anterior"] = new_rollover

            save_data(data)
            st.success("✅ Budget and Rollover updated.")
            st.rerun()

    with col_b:
        st.markdown("##### 🪙 USDT Exchange Rate")
        manual_rate = st.number_input(
            "Manual USDT Rate (VES):",
            min_value=0.1,
            value=float(st.session_state["tasa_usdt"]),
            step=1.0,
        )

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("Apply Manual Rate"):
                st.session_state["tasa_usdt"] = manual_rate
                st.success(f"Rate set to VES {manual_rate:.2f}")
                st.rerun()
        with col_b2:
            if st.button("🔄 Sync with Binance P2P"):
                st.session_state["tasa_usdt"] = fetch_online_usdt_rate()
                st.success("Rate updated from Binance P2P.")
                st.rerun()
