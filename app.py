import json
from datetime import datetime
from pathlib import Path
import requests
import streamlit as st
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuración de página web
st.set_page_config(
    page_title="Gestor de Caja Chica USDT",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilos CSS personalizados (Modo Oscuro / Alto contraste)
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
# FUNCIONES BÁSICAS Y CONSULTA TASA
# ------------------------------------
@st.cache_data(ttl=600)
def obtener_tasa_usdt_online() -> float:
    # 1. Consulta directa a la API oficial de Binance P2P (USDT / VES)
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
                precios = [float(adv["adv"]["price"]) for adv in data["data"]]
                if precios:
                    return round(sum(precios) / len(precios), 2)
    except Exception:
        pass

    # 2. Respaldo secundario: alcambio.app
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
                    nombre = str(rate.get("source", "")).lower()
                    if "binance" in nombre or "usdt" in nombre:
                        return float(rate.get("rate", 0))
    except Exception:
        pass

    return 100.00


def cargar_datos():
    if ARCH_DB.exists():
        with open(ARCH_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"semanas": []}


def guardar_datos(datos):
    with open(ARCH_DB, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)


def obtener_o_crear_semana(
    datos, num_semana, presupuesto_base=25.0, ahorro_inicial=60.0
):
    for sem in datos["semanas"]:
        if sem["numero"] == num_semana:
            return sem

    # Considerar solo las semanas registradas desde la 41 en adelante
    semanas_validas = [s for s in datos["semanas"] if s["numero"] >= 41]

    if not semanas_validas:
        remanente = ahorro_inicial
    else:
        previa = semanas_validas[-1]
        tasa = st.session_state.get("tasa_usdt", 100.00)
        gastado_usdt = previa["total_gastado"] / tasa if tasa > 0 else 0
        remanente = previa["presupuesto_disponible"] - gastado_usdt

    nueva = {
        "numero": num_semana,
        "presupuesto_base": presupuesto_base,
        "remanente_anterior": remanente,
        "presupuesto_disponible": presupuesto_base + remanente,
        "gastos": [],
        "total_gastado": 0.0,
    }
    datos["semanas"].append(nueva)
    guardar_datos(datos)
    return nueva


# ------------------------------------
# INICIALIZACIÓN DE ESTADO
# ------------------------------------
if "tasa_usdt" not in st.session_state:
    st.session_state["tasa_usdt"] = obtener_tasa_usdt_online()

datos = cargar_datos()

# ------------------------------------
# BARRA LATERAL (SIDEBAR)
# ------------------------------------
st.sidebar.title("⚙️ Configuración")
st.sidebar.markdown(
    f"🪙 **Tasa USDT (Binance P2P):** `Bs. {st.session_state['tasa_usdt']:.2f}`"
)

# Filtramos la selección para que comience mínimo en la Semana 41
semanas_existentes = [s["numero"] for s in datos.get("semanas", []) if s["numero"] >= 41] or [41]
num_semana = st.sidebar.number_input(
    "Seleccionar Semana:",
    min_value=41,
    value=int(semanas_existentes[-1]),
    step=1,
)

semana_actual = obtener_o_crear_semana(datos, num_semana)

st.sidebar.markdown("---")
st.sidebar.caption("💡 Tasa obtenida en tiempo real de **Binance P2P**")

# ------------------------------------
# CABECERA Y PANEL DE MÉTRICAS
# ------------------------------------
st.title("💰 Sistema de Caja Chica (USDT)")

tasa_actual = st.session_state["tasa_usdt"]
total_gastado_usdt = (
    semana_actual["total_gastado"] / tasa_actual if tasa_actual > 0 else 0.0
)
saldo_restante_usdt = semana_actual["presupuesto_disponible"] - total_gastado_usdt
saldo_restante_bs = saldo_restante_usdt * tasa_actual

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(
        f"""
    <div class="metric-card">
        <div class="metric-title">Presupuesto Semanal</div>
        <div class="metric-value">{semana_actual['presupuesto_base']:.2f} USDT</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

with col2:
    st.markdown(
        f"""
    <div class="metric-card">
        <div class="metric-title">Ahorro / Remanente</div>
        <div class="metric-value">{semana_actual['remanente_anterior']:.2f} USDT</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

with col3:
    st.markdown(
        f"""
    <div class="metric-card">
        <div class="metric-title">Total Gastado</div>
        <div class="metric-value" style="color: #ff5555;">{total_gastado_usdt:.2f} USDT</div>
        <div class="metric-title">Bs. {semana_actual['total_gastado']:.2f}</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

with col4:
    st.markdown(
        f"""
    <div class="metric-card">
        <div class="metric-title">Saldo Disponible</div>
        <div class="metric-value" style="color: #00ff88;">{saldo_restante_usdt:.2f} USDT</div>
        <div class="metric-sub">Bs. {saldo_restante_bs:.2f}</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# ------------------------------------
# PESTAÑAS PRINCIPALES
# ------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(
    ["📝 Registrar Compra", "📊 Resumen Semanal", "↩️ Eliminar Compra", "⚙️ Ajustes"]
)

# --- TAB 1: REGISTRAR COMPRA ---
with tab1:
    st.subheader(f"Registrar Gasto - Semana {num_semana}")
    with st.form("form_compra", clear_on_submit=True):
        producto = st.text_input("Nombre del Producto o Servicio:")
        precio_bs = st.number_input(
            "Precio en Bolívares (Bs.):", min_value=0.0, step=0.5
        )
        factura_file = st.file_uploader(
            "Adjuntar Factura/Comprobante (opcional):",
            type=["png", "jpg", "jpeg", "pdf"],
        )

        if precio_bs > 0 and tasa_actual > 0:
            st.caption(
                f"Equivalente estimado: **{precio_bs / tasa_actual:.2f} USDT**"
            )

        btn_guardar = st.form_submit_button("💾 Registrar Compra")

        if btn_guardar:
            if not producto.strip():
                st.error("Por favor ingresa un nombre para el producto.")
            elif precio_bs <= 0:
                st.error("El precio debe ser mayor a 0.")
            else:
                nombre_factura = None
                if factura_file is not None:
                    ext = Path(factura_file.name).suffix
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    nombre_factura = f"factura_sem{num_semana}_{timestamp}{ext}"
                    with open(CARPETA_ADJUNTOS / nombre_factura, "wb") as f:
                        f.write(factura_file.getbuffer())

                p_usdt = (
                    round(precio_bs / tasa_actual, 2)
                    if tasa_actual > 0
                    else 0.0
                )
                gasto = {
                    "producto": producto,
                    "precio": precio_bs,
                    "precio_usdt": p_usdt,
                    "factura": nombre_factura,
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                semana_actual["gastos"].append(gasto)
                semana_actual["total_gastado"] += precio_bs
                guardar_datos(datos)
                st.success(
                    f"✅ Se registró '{producto}' por Bs. {precio_bs:.2f}"
                    f" ({p_usdt:.2f} USDT)"
                )
                st.rerun()

# --- TAB 2: RESUMEN Y HISTORIAL ---
with tab2:
    st.subheader(f"Historial de Compras - Semana {num_semana}")
    if not semana_actual["gastos"]:
        st.info("No hay compras registradas en esta semana.")
    else:
        tabla = []
        for i, g in enumerate(semana_actual["gastos"], 1):
            p_usdt = g.get(
                "precio_usdt",
                g["precio"] / tasa_actual if tasa_actual > 0 else 0,
            )
            tabla.append(
                {
                    "#": i,
                    "Producto": g["producto"],
                    "Precio (Bs.)": f"Bs. {g['precio']:.2f}",
                    "Precio (USDT)": f"{p_usdt:.2f} USDT",
                    "Factura": (
                        g["factura"] if g.get("factura") else "Sin adjunto"
                    ),
                    "Fecha": g["fecha"],
                }
            )
        st.dataframe(tabla, use_container_width=True)

# --- TAB 3: ELIMINAR COMPRA ---
with tab3:
    st.subheader(f"Eliminar Compra Errónea - Semana {num_semana}")
    if not semana_actual["gastos"]:
        st.info("No hay gastos registrados en esta semana para eliminar.")
    else:
        opciones_gastos = [
            f"{i+1}. {g['producto']} (Bs. {g['precio']:.2f})"
            for i, g in enumerate(semana_actual["gastos"])
        ]
        seleccion = st.selectbox(
            "Selecciona la compra a eliminar:", opciones=opciones_gastos
        )

        if st.button("🗑️ Eliminar Compra Seleccionada", type="primary"):
            idx = opciones_gastos.index(seleccion)
            gasto_borrado = semana_actual["gastos"].pop(idx)
            semana_actual["total_gastado"] -= gasto_borrado["precio"]
            if semana_actual["total_gastado"] < 0:
                semana_actual["total_gastado"] = 0.0

            if gasto_borrado.get("factura"):
                ruta_f = CARPETA_ADJUNTOS / gasto_borrado["factura"]
                if ruta_f.exists():
                    try:
                        ruta_f.unlink()
                    except Exception:
                        pass

            guardar_datos(datos)
            st.success(
                f"🗑️ Se eliminó '{gasto_borrado['producto']}' correctamente."
            )
            st.rerun()

# --- TAB 4: AJUSTES DE PRESUPUESTO Y TASA ---
with tab4:
    st.subheader("⚙️ Configuración Financiera")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### 💵 Presupuesto y Ahorro")
        nuevo_pres = st.number_input(
            "Presupuesto Semanal ($ USDT):",
            min_value=0.0,
            value=float(semana_actual["presupuesto_base"]),
            step=5.0,
        )
        nuevo_ahorro = st.number_input(
            "Remanente / Ahorro ($ USDT):",
            min_value=0.0,
            value=float(semana_actual["remanente_anterior"]),
            step=5.0,
        )

        if st.button("Guardar Cambios de Presupuesto"):
            semana_actual["presupuesto_base"] = nuevo_pres
            semana_actual["remanente_anterior"] = nuevo_ahorro
            semana_actual["presupuesto_disponible"] = nuevo_pres + nuevo_ahorro
            guardar_datos(datos)
            st.success("✅ Presupuesto y ahorro actualizados.")
            st.rerun()

    with col_b:
        st.markdown("##### 🪙 Tasa USDT")
        tasa_manual = st.number_input(
            "Tasa USDT Manual (Bs.):",
            min_value=0.1,
            value=float(st.session_state["tasa_usdt"]),
            step=1.0,
        )

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("Aplicar Tasa Manual"):
                st.session_state["tasa_usdt"] = tasa_manual
                st.success(f"Tasa fijada en Bs. {tasa_manual:.2f}")
                st.rerun()
        with col_b2:
            if st.button("🔄 Sincronizar con Binance P2P"):
                st.session_state["tasa_usdt"] = obtener_tasa_usdt_online()
                st.success("Tasa actualizada desde Binance P2P.")
                st.rerun()
