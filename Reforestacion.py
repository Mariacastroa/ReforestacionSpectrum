import copy
import math
import re
import unicodedata
from datetime import date, datetime

import folium
try:
    from folium.plugins import Draw, Fullscreen as FullScreen
except ImportError:
    from folium.plugins import Draw, FullScreen
import requests
import streamlit as st
from streamlit_folium import st_folium
from shapely.geometry import shape, Polygon, GeometryCollection, mapping
from shapely.ops import unary_union

# CONFIGURACIÓN DE LA PÁGINA
st.set_page_config(
    page_title="Reforestación Spectrum",
    page_icon="🌳",
    layout="wide"
)

# CONSTANTES Y DATOS DE IMPACTO
tree_impact_data = {
    "Pino": 9,
    "Ciprés": 8,
    "Encino": 15,
    "Caoba": 18,
    "Cedro": 16,
    "Matilisguate": 12,
    "Conacaste": 20,
    "Eucalipto": 9,
    "Hormigo": 9,
    "Nance": 12,
}

M2_POR_MANZANA = 7050.2

SUPERFICIE_CONSTRUIDA_MANZANAS = {
    "Vivienda": 254,
    "Propiedades": 38,
    "Synergy": 704,
}

DETALLE_PROPIEDADES_MANZANAS = {
    "Miraflores": 20,
    "Portales": 6,
    "Naranjo": 6,
    "Oakland": 4.5,
    "Centro Gerencial Margaritas": 1.5,
}

COLORES_COMPARACION = {
    "Vivienda": "#173B57",
    "Propiedades": "#2E8B57",
    "Synergy": "#0B5D3B",
}

FASES_REFORESTACION = {
    1: {
        "nombre": "1. Establecimiento",
        "temporalidad": "Meses 1 a 12",
        "objetivo": "Evaluar adaptación inicial.",
        "indicadores": ["Porcentaje de supervivencia", "Causas de mortalidad"],
        "color_hex": "#8BC34A",
    },
    2: {
        "nombre": "2. Desarrollo",
        "temporalidad": "Años 2 a 3",
        "objetivo": "Evaluar crecimiento y salud.",
        "indicadores": ["Altura y diámetro del tallo", "Estado fitosanitario (plagas)", "Control de malezas"],
        "color_hex": "#2E8B57",
    },
    3: {
        "nombre": "3. Consolidación",
        "temporalidad": "Años 4 a 5+",
        "objetivo": "Verificar autosuficiencia.",
        "indicadores": ["Incremento Medio Anual", "Retorno de biodiversidad", "Regeneración natural"],
        "color_hex": "#0B5D3B",
    },
}

ARCGIS_WEBMAP_ID = "73bcb606bd1f415081f04c8c75a377b4"
ARCGIS_ITEM_DATA_URL = f"https://www.arcgis.com/sharing/rest/content/items/{ARCGIS_WEBMAP_ID}/data"
ZONAS_VALIDAS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 24, 25]

TRANSFORMACION_SYNERGY = {
    "lon_x": 3.32620412e-05,
    "lon_y": -7.39465983e-06,
    "lon_c": -90.7990610,
    "lat_x": 1.78197706e-07,
    "lat_y": -3.11809558e-05,
    "lat_c": 14.3510306,
}

SECTORES_SYNERGY_PIXELES = {
    "C1": [(350, 820), (450, 820), (550, 940), (635, 1000), (550, 1010), (390, 1025), (330, 950)],
    "C2A": [(350, 410), (300, 475), (200, 600), (280, 660), (330, 555)],
    "C2B": [(280, 560), (390, 580), (410, 710), (330, 760), (260, 650)],
    "C2C": [(455, 397), (405, 395), (350, 430), (330, 550), (365, 565), (405, 400)],
    "C3": [(390, 580), (520, 620), (490, 710), (410, 710)],
    "C4": [(330, 760), (410, 710), (490, 710), (450, 900), (350, 920)],
    "C5": [(520, 620), (600, 660), (570, 780), (490, 710)],
    "C6A": [(405, 400), (610, 420), (575, 625), (390, 580)],
    "C6B": [(475, 55), (615, 105), (603, 405), (455, 397), (450, 250)],
    "C7": [(615, 105), (690, 130), (665, 380), (610, 420), (603, 200)],
    "C8A": [(600, 660), (720, 650), (760, 850), (650, 1000), (550, 1000), (570, 780)],
    "C8B": [(610, 420), (760, 390), (720, 650), (600, 660)],
    "C9A": [(760, 390), (910, 400), (865, 660), (720, 650)],
    "C9B": [(720, 650), (865, 660), (820, 850), (760, 850)],
    "C10": [(410, 710), (490, 710), (570, 780), (530, 830), (450, 820)],
    "Amenities": [(260, 650), (330, 760), (350, 820), (300, 850), (250, 750)],
    "Solar Park": [(690, 130), (930, 210), (910, 400), (760, 390), (665, 380)],
}

ORDEN_SECTORES_SYNERGY = [
    "C1", "C2A", "C2B", "C2C", "C3", "C4", "C5",
    "C6A", "C6B", "C7", "C8A", "C8B", "C9A", "C9B",
    "C10", "Amenities", "Solar Park",
]

# FUNCIONES MATEMÁTICAS Y GEOGRÁFICAS
RADIO_TIERRA_M = 6_371_008.8

def calcular_area_anillo_m2(coordenadas):
    if not coordenadas or len(coordenadas) < 3:
        return 0.0
    puntos = [list(punto[:2]) for punto in coordenadas]
    if puntos[0] != puntos[-1]:
        puntos.append(puntos[0])
    latitud_media = sum(punto[1] for punto in puntos[:-1]) / max(1, len(puntos) - 1)
    cos_latitud = math.cos(math.radians(latitud_media))
    puntos_metros = [
        (RADIO_TIERRA_M * math.radians(longitud) * cos_latitud, RADIO_TIERRA_M * math.radians(latitud))
        for longitud, latitud in puntos
    ]
    suma = 0.0
    for i in range(len(puntos_metros) - 1):
        x1, y1 = puntos_metros[i]
        x2, y2 = puntos_metros[i + 1]
        suma += x1 * y2 - x2 * y1
    return abs(suma) / 2.0

def calcular_area_geometria_m2(geometria):
    if not geometria:
        return 0.0
    tipo = geometria.get("type")
    coordenadas = geometria.get("coordinates", [])
    if tipo == "Polygon":
        if not coordenadas: return 0.0
        area_exterior = calcular_area_anillo_m2(coordenadas[0])
        area_huecos = sum(calcular_area_anillo_m2(a) for a in coordenadas[1:])
        return max(0.0, area_exterior - area_huecos)
    elif tipo == "MultiPolygon":
        return sum(calcular_area_geometria_m2({"type": "Polygon", "coordinates": p}) for p in coordenadas)
    return 0.0

def convertir_pixel_a_coordenada_synergy(x, y):
    t = TRANSFORMACION_SYNERGY
    longitud = t["lon_x"] * x + t["lon_y"] * y + t["lon_c"]
    latitud = t["lat_x"] * x + t["lat_y"] * y + t["lat_c"]
    return latitud, longitud

def preparar_geojson_synergy():
    features = []
    lookup = {}
    for nombre_sector in ORDEN_SECTORES_SYNERGY:
        puntos_pixel = SECTORES_SYNERGY_PIXELES[nombre_sector]
        anillo = []
        for x, y in puntos_pixel:
            latitud, longitud = convertir_pixel_a_coordenada_synergy(x, y)
            anillo.append([longitud, latitud])
        if anillo[0] != anillo[-1]:
            anillo.append(anillo[0])
        feature = {
            "type": "Feature",
            "properties": {"sector_nombre": nombre_sector},
            "geometry": {"type": "Polygon", "coordinates": [anillo]},
        }
        geometria = shape(feature["geometry"])
        if not geometria.is_valid:
            geometria = geometria.buffer(0)
            feature["geometry"] = mapping(geometria)
        features.append(feature)
        lookup[nombre_sector] = feature
    return {"type": "FeatureCollection", "features": features}, lookup

@st.cache_data(show_spinner=False)
def cargar_zonas_arcgis():
    try:
        res = requests.get(ARCGIS_ITEM_DATA_URL, params={"f": "json"}, timeout=30).json()
        capa = res.get("operationalLayers", [])[0]
        url = capa.get("url")
        q_res = requests.get(f"{url.rstrip('/')}/query", params={"where": "1=1", "outFields": "*", "f": "geojson"}, timeout=30).json()
        
        features = []
        lookup = {}
        for f in q_res.get("features", []):
            props = f.get("properties", {})
            zona_num = None
            for k, v in props.items():
                if "ZONA" in str(k).upper():
                    m = re.search(r'\d+', str(v))
                    if m: zona_num = int(m.group())
            if zona_num in ZONAS_VALIDAS:
                f["properties"]["zona_nombre"] = f"Zona {zona_num}"
                f["properties"]["zona_numero"] = zona_num
                features.append(f)
                lookup[f"Zona {zona_num}"] = f
        return {"type": "FeatureCollection", "features": features}, lookup
    except Exception:
        return {"type": "FeatureCollection", "features": []}, {}

# INICIALIZACIÓN DE ESTADO
if "proyectos" not in st.session_state:
    st.session_state.proyectos = []

geojson_synergy, synergy_lookup = preparar_geojson_synergy()
geojson_zonas, zone_lookup = cargar_zonas_arcgis()

# ==========================================
# INTERFAZ DE USUARIO (STREAMLIT)
# ==========================================
st.title("Reforestación Spectrum")
st.caption("Prototipo de seguimiento y comparación territorial por María José Castro")

# Panel Superior de Métricas
total_reforestado_m2 = sum(p["area_m2"] for p in st.session_state.proyectos)
total_arboles = sum(p["total_arboles"] for p in st.session_state.proyectos)

col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("Área Reforestada Total", f"{total_reforestado_m2:,.0f} m²")
col_m2.metric("Equivalente en Manzanas", f"{total_reforestado_m2 / M2_POR_MANZANA:,.2f} mz")
col_m3.metric("Árboles Registrados", f"{total_arboles:,} unidades")

st.divider()

# Layout Principal: Mapa y Formulario
col_mapa, col_form = st.columns([2, 1])

with col_form:
    st.subheader("📌 Registrar Proyecto")
    
    nombre_proj = st.text_input("Nombre del proyecto", "Jornada de Reforestación")
    fecha_proj = st.date_input("Fecha de reforestación", date.today())
    
    tipo_ub = st.radio("Tipo de ubicación", ["Ciudad de Guatemala (Zonas)", "Synergy (Sectores)"])
    
    if tipo_ub == "Ciudad de Guatemala (Zonas)":
        ub_opciones = sorted(list(zone_lookup.keys()), key=lambda x: int(re.search(r'\d+', x).group())) if zone_lookup else ["Zona 1"]
        ubicacion_sel = st.selectbox("Selecciona la Zona", ub_opciones)
    else:
        ubicacion_sel = st.selectbox("Selecciona el Sector", ORDEN_SECTORES_SYNERGY)

    st.markdown("**Especies a plantar:**")
    cantidades_arboles = {}
    total_est_m2 = 0
    total_cant_arboles = 0

    for arbol, m2_cob in tree_impact_data.items():
        cant = st.number_input(f"{arbol} ({m2_cob} m²/árbol)", min_value=0, value=0, step=5, key=f"arbol_{arbol}")
        if cant > 0:
            cantidades_arboles[arbol] = cant
            total_est_m2 += cant * m2_cob
            total_cant_arboles += cant

    st.info(f"💡 Cobertura proyectada: **{total_est_m2:,.0f} m²** ({total_cant_arboles} árboles)")

    # Captura de polígono dibujado
    area_dibujada_m2 = 0.0
    poligono_dibujado = None

    if "drawn_shapes" in st.session_state and st.session_state.drawn_shapes:
        last_shape = st.session_state.drawn_shapes[-1]
        if last_shape.get("geometry"):
            poligono_dibujado = last_shape["geometry"]
            area_dibujada_m2 = calcular_area_geometria_m2(poligono_dibujado)

    if area_dibujada_m2 > 0:
        st.success(f"Área dibujada en mapa: **{area_dibujada_m2:,.1f} m²**")
        area_final_m2 = area_dibujada_m2
    else:
        st.caption("Dibuja un polígono en el mapa para usar el área exacta dibujada, o se usará la estimación por árboles.")
        area_final_m2 = total_est_m2

    if st.button("Guardar Proyecto", type="primary", use_container_width=True):
        if total_cant_arboles == 0:
            st.error("Debes ingresar al menos 1 árbol.")
        else:
            nuevo_p = {
                "nombre": nombre_proj,
                "fecha": fecha_proj.strftime("%Y-%m-%d"),
                "ubicacion": ubicacion_sel,
                "tipo_ub": tipo_ub,
                "arboles": cantidades_arboles,
                "total_arboles": total_cant_arboles,
                "area_m2": area_final_m2,
                "geometry": poligono_dibujado
            }
            st.session_state.proyectos.append(nuevo_p)
            st.success("¡Proyecto guardado exitosamente!")
            st.rerun()

with col_mapa:
    st.subheader("Mapa Interactivo")
    
    # Crear Mapa base Folium (centrado en Ciudad de Guatemala)
    m = folium.Map(location=[14.634915, -90.506882], zoom_start=11, tiles="OpenStreetMap")
    
    # Agregar Zonas de la Ciudad
    if geojson_zonas.get("features"):
        folium.GeoJson(
            geojson_zonas,
            name="Zonas C. Guatemala",
            style_function=lambda x: {"fillColor": "#2E8B57", "color": "#173B57", "weight": 1, "fillOpacity": 0.15},
            tooltip=folium.GeoJsonTooltip(fields=["zona_nombre"], aliases=["Zona:"])
        ).add_to(m)

    # Agregar Sectores Synergy
    folium.GeoJson(
        geojson_synergy,
        name="Sectores Synergy",
        style_function=lambda x: {"fillColor": "#0B5D3B", "color": "#0B5D3B", "weight": 2, "fillOpacity": 0.3},
        tooltip=folium.GeoJsonTooltip(fields=["sector_nombre"], aliases=["Sector:"])
    ).add_to(m)

    # Agregar Proyectos Guardados
    for p in st.session_state.proyectos:
        if p.get("geometry"):
            folium.GeoJson(
                p["geometry"],
                style_function=lambda x: {"fillColor": "#173B57", "color": "#173B57", "weight": 3, "fillOpacity": 0.6},
                tooltip=f"<b>{p['nombre']}</b><br>{p['area_m2']:,.0f} m²"
            ).add_to(m)

    # Herramienta de Dibujo
    Draw(
        export=False,
        draw_options={"polygon": True, "polyline": False, "rectangle": True, "circle": False, "marker": False, "circlemarker": False},
        edit_options={"edit": False}
    ).add_to(m)
    
    FullScreen().add_to(m)
    folium.LayerControl().add_to(m)

    # Renderizar mapa en Streamlit
    output_map = st_folium(m, width="100%", height=550)
    
    if output_map and output_map.get("all_drawings"):
        st.session_state.drawn_shapes = output_map["all_drawings"]

# SECCIÓN DE REPORTES Y PROYECTOS REGISTRADOS
st.divider()
st.subheader("📋 Proyectos Registrados")

if not st.session_state.proyectos:
    st.info("Aún no hay proyectos registrados.")
else:
    for idx, p in enumerate(st.session_state.proyectos):
        with st.expander(f" {p['nombre']} — {p['ubicacion']} ({p['fecha']})"):
            c1, c2 = st.columns(2)
            c1.write(f"**Área Reforestada:** {p['area_m2']:,.1f} m²")
            c1.write(f"**Total Árboles:** {p['total_arboles']}")
            c2.write("**Especies:**")
            for arb, cant in p['arboles'].items():
                c2.write(f"- {arb}: {cant} unidades")
