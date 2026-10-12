import json
from datetime import datetime
from pathlib import Path
import requests
import streamlit as st
from bs4 import BeautifulSoup
import urllib3

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


def get_current_real_week() -> int:
    """Returns current real-world ISO week number (minimum 41)."""
    current_iso_week = datetime.now().isocalendar()[1]
    return max(41, current_iso_week)


def load_data():
    if ARCH_DB.exists():
        with open(ARCH_DB, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "semanas" not in data:
                data["semanas"] = []
            if "pending_purchases" not in data:
                data["pending_purchases"] = []
            return data
    return {"semanas": [], "pending_purchases": []}


def save_data(data):
    with open(ARCH_DB, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_or_create_week(
    data, week_num, base_budget=25.0, initial_savings=60.0
):
    for sem in data["semanas"]:
        if sem["numero"] == week_num:
            if "budget_funded" not in sem:
                sem["budget_funded"] = True
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
        "budget_funded": True,
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

real_current_week = get_current_real_week()

if "input_week_number" not in st.session_state:
    st.session_state["input_week_number"] = real_current_week

data = load_data()

# ------------------------------------
# SIDEBAR (LEFT PANEL)
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
        sb_item_cost = st.number_input("Est. USDT:", min_value=0.0, step=5.0)
        sb_item_prio = st.selectbox("Priority:", ["High", "Medium", "Low"])
        sb_submitted = st.form_submit_button("Add to List")
        if sb_submitted:
            if sb_item_name.strip():
                if "pending_purchases" not in data:
                    data["pending_purchases"] = []
                data["pending_purchases"].append(
                    {
                        "item": sb_item_name,
                        "est_cost": sb_item_cost,
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
        cost_str = (
            f" ({p_item['est_cost']:.2f} USDT)"
            if p_item.get("est_cost", 0) > 0
            else ""
        )
        st
