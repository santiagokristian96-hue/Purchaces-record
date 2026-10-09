import json
from datetime import datetime
from pathlib import Path
import requests
import streamlit as st
from bs4 import BeautifulSoup
import urllib3
from PIL import Image

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Web Page Configuration
st.set_page_config(
    page_title="USDT Petty Cash Manager",
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

ARCH_DB = Path("caja_chica.json")
CARPETA_ADJUNTOS = Path("adjuntos")
CARPETA_ADJUNTOS.mkdir(parents=True, exist_ok=True)


# Helper function to save and optimize images/files
def save_optimized_file(uploaded_file, destination_path: Path):
    ext = destination_path.suffix.lower()
    if ext in [".png", ".jpg", ".jpeg"]:
        try:
            img = Image.open(uploaded_file)
            img.thumbnail((800, 800))  # Resize max dimensions to 800px
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(destination_path, optimize=True, quality=80)
            return
        except Exception:
            pass

    # Standard save for PDFs or fallback
    with open(destination_path, "wb") as f:
        f.write(uploaded_file.getbuffer())


# ------------------------------------
# FUNCTIONS & EXCHANGE RATE FETCHING
# ------------------------------------
@st.cache_data(ttl=600)
def fetch_online_usdt_rate() -> float:
    # 1. Primary Source: Official Binance P2P API (USDT / VES)
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

    # 2. Secondary Fallback Source: alcambio.app
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


def load_data():
    if ARCH_DB.exists():
        with open(ARCH_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"semanas": []}


def save_data(data):
    with open(ARCH_DB, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_or_create_week(
    data, week_num, base_budget=25.0, initial_savings=60.0
):
    for sem in data["semanas"]:
        if sem["numero"] == week_num:
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
        "presupuesto_disponible": base_budget + rollover,
        "gastos": [],
        "total_gastado": 0.0,
    }
    data["semanas"].append(new_week)
    save_data(data)
    return new_week


# ------------------------------------
# STATE INITIALIZATION
# ------------------------------------
if "tasa_usdt" not in st.session_state:
    st.session_state["tasa_usdt"] = fetch_online_usdt_rate()

data = load_data()

# ------------------------------------
# SIDEBAR
# ------------------------------------
st.sidebar.title("⚙️ Settings")
st.sidebar.markdown(
    f"🪙 **USDT Rate (Binance P2P):** `VES {st.session_state['tasa_usdt']:.2f}`"
)

existing_weeks = [s["numero"] for s in data.get("semanas", []) if s["numero"] >= 41] or [41]
week_num = st.sidebar.number_input(
    "Select Week:",
    min_value=41,
    value=int(existing_weeks[-1]),
    step=1,
)

current_week = get_or_create_week(data, week_num)

st.sidebar.markdown("---")
st.sidebar.caption("💡 Rate fetched in real-time from **Binance P2P**")

# ------------------------------------
# HEADER & METRICS PANEL
# ------------------------------------
st.title("💰 Petty Cash Management System (USDT)")

current_rate = st.session_state["tasa_usdt"]
total_spent_usdt = (
    current_week["total_gastado"] / current_rate if current_rate > 0 else 0.0
)
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
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "📝 Record Expense",
        "📊 Weekly Summary",
        "✏️ Edit Expense",
        "↩️ Delete Expense",
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
                st.image(receipt_file, caption="Receipt Preview", width=200)

        if price_ves > 0 and current_rate > 0:
            st.caption(
                f"Estimated equivalent: **{price_ves / current_rate:.2f} USDT**"
            )

        btn_save = st.form_submit_button("💾 Save Expense")

        if btn_save:
            if not product_name.strip():
                st.error("Please enter a product or service name.")
            elif price_ves <= 0:
                st.error("Price must be greater than 0.")
            else:
                receipt_filename = None
                if receipt_file is not None:
                    ext = Path(receipt_file.name).suffix.lower()
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    receipt_filename = f"receipt_wk{week_num}_{timestamp}{ext}"
                    dest_path = CARPETA_ADJUNTOS / receipt_filename
                    save_optimized_file(receipt_file, dest_path)

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

        # RECEIPT VIEWER SECTION
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
            rec_path = CARPETA_ADJUNTOS / rec_filename

            if rec_path.exists():
                ext_file = rec_path.suffix.lower()
                if ext_file in [".png", ".jpg", ".jpeg"]:
                    st.image(
                        str(rec_path),
                        caption=f"Receipt: {rec_filename}",
                        width=220,  # Compact thumbnail size
                    )
                elif ext_file == ".pdf":
                    with open(rec_path, "rb") as pdf_file:
                        st.download_button(
                            label=f"📄 Download PDF Receipt ({rec_filename})",
                            data=pdf_file,
                            file_name=rec_filename,
                            mime="application/pdf",
                        )

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

        # DISPLAY CURRENT RECEIPT IF IT EXISTS
        current_receipt = target_expense.get("factura")
        if current_receipt:
            st.markdown("##### 📎 Current Attached Receipt:")
            r_path_edit = CARPETA_ADJUNTOS / current_receipt
            if r_path_edit.exists():
                ext_edit = r_path_edit.suffix.lower()
                if ext_edit in [".png", ".jpg", ".jpeg"]:
                    st.image(str(r_path_edit), width=200)
                elif ext_edit == ".pdf":
                    with open(r_path_edit, "rb") as pdf_f:
                        st.download_button(
                            label="📄 Download Attached PDF Receipt",
                            data=pdf_f,
                            file_name=current_receipt,
                            mime="application/pdf",
                        )

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

            if edit_price_ves > 0 and current_rate > 0:
                st.caption(
                    f"New estimated equivalent: **{edit_price_ves / current_rate:.2f} USDT**"
                )

            btn_update = st.form_submit_button("💾 Save Changes")

            if btn_update:
                if not edit_product_name.strip():
                    st.error("Please enter a product or service name.")
                elif edit_price_ves <= 0:
                    st.error("Price must be greater than 0.")
                else:
                    receipt_filename = target_expense.get("factura")

                    # Handle file replacement if a new file is uploaded
                    if edit_receipt_file is not None:
                        if receipt_filename:
                            old_path = CARPETA_ADJUNTOS / receipt_filename
                            if old_path.exists():
                                try:
                                    old_path.unlink()
                                except Exception:
                                    pass
                        ext = Path(edit_receipt_file.name).suffix.lower()
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        receipt_filename = f"receipt_wk{week_num}_{timestamp}{ext}"
                        dest_path = CARPETA_ADJUNTOS / receipt_filename
                        save_optimized_file(edit_receipt_file, dest_path)

                    # Recalculate total spent
                    old_price = target_expense["precio"]
                    current_week["total_gastado"] = (
                        current_week["total_gastado"] - old_price + edit_price_ves
                    )
                    if current_week["total_gastado"] < 0:
                        current_week["total_gastado"] = 0.0

                    p_usdt = (
                        round(edit_price_ves / current_rate, 2)
                        if current_rate > 0
                        else 0.0
                    )

                    # Update expense data
                    target_expense["producto"] = edit_product_name
                    target_expense["precio"] = edit_price_ves
                    target_expense["precio_usdt"] = p_usdt
                    target_expense["factura"] = receipt_filename

                    save_data(data)
                    st.success(f"✅ Successfully updated '{edit_product_name}'.")
                    st.rerun()

# --- TAB 4: DELETE EXPENSE ---
with tab4:
    st.subheader(f"Delete Incorrect Expense - Week {week_num}")
    if not current_week["gastos"]:
        st.info("No expenses recorded for this week to delete.")
    else:
        expense_options_delete = [
            f"{i+1}. {g['producto']} (VES {g['precio']:.2f})"
            for i, g in enumerate(current_week["gastos"])
        ]
        selected_expense_delete = st.selectbox(
            "Select expense to delete:",
            options=expense_options_delete,
            key="select_delete_expense",
        )

        if st.button("🗑️ Delete Selected Expense", type="primary"):
            idx_del = expense_options_delete.index(selected_expense_delete)
            deleted_expense = current_week["gastos"].pop(idx_del)
            current_week["total_gastado"] -= deleted_expense["precio"]
            if current_week["total_gastado"] < 0:
                current_week["total_gastado"] = 0.0

            if deleted_expense.get("factura"):
                receipt_path = CARPETA_ADJUNTOS / deleted_expense["factura"]
                if receipt_path.exists():
                    try:
                        receipt_path.unlink()
                    except Exception:
                        pass

            save_data(data)
            st.success(
                f"🗑️ Successfully removed '{deleted_expense['producto']}'."
            )
            st.rerun()

# --- TAB 5: FINANCIAL SETTINGS ---
with tab5:
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
            current_week["presupuesto_disponible"] = new_budget + new_rollover
            save_data(data)
            st.success("✅ Budget and savings updated.")
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
