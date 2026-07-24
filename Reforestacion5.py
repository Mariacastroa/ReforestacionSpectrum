"""Spectrum | Prototipo por Maria Jose Castro"""

from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from datetime import date, datetime
from typing import Any

import folium
import pandas as pd
import requests
import streamlit as st
from folium.plugins import Draw, Fullscreen
from shapely.geometry import GeometryCollection, Polygon, mapping, shape
from shapely.ops import unary_union
from streamlit_folium import st_folium


# CONFIGURACIÓN GENERAL
st.set_page_config(
    page_title="Reforestación Spectrum",
    page_icon="🌳",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        .stApp { background: #F5F7F8; }
        .block-container { padding-top: 1.15rem; padding-bottom: 3rem; }
        .spectrum-header {
            background: linear-gradient(100deg, #0B5D3B 0%, #2E8B57 58%, #173B57 100%);
            color: white; padding: 1.25rem 1.5rem; border-radius: 14px;
            box-shadow: 0 5px 18px rgba(11, 93, 59, .18); margin-bottom: 1rem;
        }
        .spectrum-header h1 { margin: 0; font-size: 2rem; }
        .spectrum-header p { margin: .3rem 0 0; opacity: .92; }
        .info-box {
            background: white; border: 1px solid #D9E1E5; border-left: 5px solid #173B57;
            border-radius: 9px; padding: .85rem 1rem; margin-bottom: .75rem;
        }
        .area-ok {
            background: #E8F5E9; border-left-color: #2E8B57;
        }
        .area-pending {
            background: #FFF8E1; border-left-color: #F9A825;
        }
        .phase-card {
            color: white; padding: .8rem 1rem; border-radius: 9px; min-height: 82px;
        }
        div[data-testid="stMetric"] {
            background: white; border: 1px solid #DFE6E9; padding: .8rem 1rem;
            border-radius: 10px;
        }
        div[data-testid="stDataEditor"] { background: white; border-radius: 9px; }
        .small-note { font-size: .83rem; color: #546E7A; }
    </style>
    """,
    unsafe_allow_html=True,
)


# CONSTANTES
TREE_IMPACT_DATA = {
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


# COMPARACIÓN TERRITORIAL CONTRA SUPERFICIE CONSTRUIDA
# 1 manzana = 7,050.2 m²
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


def calcular_superficie_construida() -> dict[str, dict[str, float]]:
    """Convierte las superficies construidas de manzanas a metros cuadrados."""
    return {
        categoria: {
            "manzanas": float(manzanas),
            "m2": float(manzanas) * M2_POR_MANZANA,
        }
        for categoria, manzanas in SUPERFICIE_CONSTRUIDA_MANZANAS.items()
    }


def calcular_porcentaje_equivalencia(
    area_reforestada_m2: float,
    area_construida_m2: float,
) -> float:
    """Compara dos superficies y devuelve el porcentaje de equivalencia."""
    if area_construida_m2 <= 0:
        return 0.0

    return (max(0.0, float(area_reforestada_m2)) / area_construida_m2) * 100


def crear_barra_progreso(porcentaje: float, color: str) -> str:
    """Genera una barra HTML; su ancho visual se limita entre 0 % y 100 %."""
    ancho_visual = max(0.0, min(float(porcentaje), 100.0))

    return f"""
    <div style="
        width:100%;
        height:15px;
        background:#E6EBEE;
        border-radius:999px;
        overflow:hidden;
        margin:10px 0 7px 0;
    ">
        <div style="
            width:{ancho_visual:.2f}%;
            height:100%;
            background:{color};
            border-radius:999px;
            transition:width 0.5s ease;
        "></div>
    </div>
    """


def crear_panel_comparacion_superficies(
    impacto_neto_campo_m2: float,
    impacto_plantado_m2: float,
    impacto_removido_m2: float,
) -> str:
    """
    Genera el panel de comparación territorial.

    La comparación utiliza el impacto arbóreo estimado neto en campo:
    impacto plantado estimado menos impacto removido por tala.
    El dibujo del mapa no interviene en este cálculo y el inventario de
    viveros se excluye porque todavía no está plantado.
    """
    superficies = calcular_superficie_construida()
    total_construido_m2 = sum(
        datos["m2"]
        for datos in superficies.values()
    )
    total_construido_manzanas = sum(
        datos["manzanas"]
        for datos in superficies.values()
    )

    impacto_neto_original = float(impacto_neto_campo_m2)
    total_reforestado_m2 = max(0.0, impacto_neto_original)

    porcentaje_total = calcular_porcentaje_equivalencia(
        total_reforestado_m2,
        total_construido_m2,
    )
    equivalencia_manzanas = total_reforestado_m2 / M2_POR_MANZANA
    diferencia_m2 = total_reforestado_m2 - total_construido_m2

    if diferencia_m2 >= 0:
        mensaje_diferencia = (
            "La equivalencia territorial estimada supera la superficie "
            f"construida por <b>{diferencia_m2:,.0f} m²</b>."
        )
    else:
        mensaje_diferencia = (
            f"Faltan <b>{abs(diferencia_m2):,.0f} m²</b> para alcanzar "
            "una equivalencia territorial estimada del 100%."
        )

    if impacto_neto_original < 0:
        mensaje_balance = (
            "<b>Advertencia:</b> el impacto removido registrado supera al "
            "impacto plantado estimado. Para la comparación territorial se "
            "utiliza un valor mínimo de 0 m²."
        )
    else:
        mensaje_balance = (
            f"<b>Composición del valor:</b> "
            f"{float(impacto_plantado_m2):,.0f} m² plantados estimados − "
            f"{float(impacto_removido_m2):,.0f} m² removidos estimados = "
            f"<b>{total_reforestado_m2:,.0f} m² netos en campo</b>."
        )

    tarjetas_categorias = ""

    for categoria, datos in superficies.items():
        porcentaje = calcular_porcentaje_equivalencia(
            total_reforestado_m2,
            datos["m2"],
        )
        color = COLORES_COMPARACION[categoria]

        tarjetas_categorias += f"""
        <div style="
            flex:1 1 230px;
            min-width:0;
            background:white;
            border:1px solid #D9E1E5;
            border-top:5px solid {color};
            border-radius:12px;
            padding:18px;
            box-shadow:0 3px 10px rgba(23,59,87,0.09);
        ">
            <div style="
                color:{color};
                font-size:18px;
                font-weight:700;
                margin-bottom:8px;
            ">
                {categoria}
            </div>

            <div style="
                font-size:32px;
                font-weight:750;
                color:#263238;
                line-height:1.1;
            ">
                {porcentaje:,.2f}%
            </div>

            <div style="
                font-size:14px;
                color:#607D8B;
                margin-top:6px;
            ">
                equivalencia del impacto territorial estimado
            </div>

            {crear_barra_progreso(porcentaje, color)}

            <div style="
                font-size:14px;
                color:#455A64;
                line-height:1.55;
            ">
                Construido: <b>{datos["manzanas"]:,.1f} mz</b><br>
                Equivalente a: <b>{datos["m2"]:,.0f} m²</b>
            </div>
        </div>
        """

    detalle_propiedades = " · ".join(
        f"{nombre}: {manzanas:g} mz"
        for nombre, manzanas in DETALLE_PROPIEDADES_MANZANAS.items()
    )

    return f"""
    <div style="
        width:100%;
        box-sizing:border-box;
        margin:20px 0 22px 0;
        padding:26px;
        background:linear-gradient(135deg, #F4FBF6, #EEF4F7);
        border:1px solid #C9DDD1;
        border-radius:16px;
        font-family:Arial, sans-serif;
        box-shadow:0 5px 18px rgba(11,93,59,0.10);
    ">
        <div style="
            display:flex;
            flex-wrap:wrap;
            justify-content:space-between;
            align-items:flex-start;
            gap:20px;
        ">
            <div style="flex:1 1 420px;">
                <div style="
                    color:#0B5D3B;
                    font-weight:750;
                    font-size:22px;
                ">
                    Comparación territorial acumulada
                </div>

                <div style="
                    font-size:46px;
                    font-weight:800;
                    color:#173B57;
                    line-height:1.05;
                    margin-top:10px;
                ">
                    {total_reforestado_m2:,.0f} m²
                </div>

                <div style="
                    font-size:16px;
                    color:#546E7A;
                    margin-top:6px;
                ">
                    impacto arbóreo estimado neto acumulado en campo
                </div>
            </div>

            <div style="
                flex:0 1 300px;
                background:#173B57;
                color:white;
                padding:20px 24px;
                border-radius:14px;
                min-width:240px;
                text-align:center;
            ">
                <div style="font-size:16px; opacity:0.88;">
                    Equivalencia en manzanas
                </div>
                <div style="
                    font-size:38px;
                    font-weight:800;
                    margin-top:6px;
                ">
                    {equivalencia_manzanas:,.2f} mz
                </div>
            </div>
        </div>

        <div style="margin-top:28px;">
            <div style="
                display:flex;
                justify-content:space-between;
                flex-wrap:wrap;
                gap:8px 18px;
                font-size:16px;
                color:#37474F;
            ">
                <span>
                    <b>Área construida total:</b>
                    {total_construido_manzanas:,.1f} mz
                    ({total_construido_m2:,.0f} m²)
                </span>
                <span style="
                    color:#0B5D3B;
                    font-weight:750;
                ">
                    {porcentaje_total:,.2f}% alcanzado
                </span>
            </div>

            {crear_barra_progreso(porcentaje_total, "#0B5D3B")}

            <div style="
                font-size:16px;
                color:#455A64;
                margin-top:8px;
            ">
                {mensaje_diferencia}
            </div>

            <div style="
                font-size:14px;
                color:#455A64;
                margin-top:8px;
            ">
                {mensaje_balance}
            </div>
        </div>

        <div style="
            display:flex;
            flex-wrap:wrap;
            gap:16px;
            margin-top:24px;
        ">
            {tarjetas_categorias}
        </div>

        <div style="
            background:white;
            border-left:5px solid #2E8B57;
            padding:14px 16px;
            margin-top:18px;
            border-radius:7px;
            font-size:14px;
            color:#455A64;
            line-height:1.55;
        ">
            <b>Detalle de propiedades:</b> {detalle_propiedades}.<br>
            <b>Interpretación:</b> esta métrica compara superficies mediante
            la estimación de impacto por especie y cantidad de árboles.
            No utiliza el dibujo del mapa, no incluye árboles disponibles en
            viveros y no representa por sí sola una compensación de carbono
            o de otros impactos ambientales de la construcción.
        </div>
    </div>
    """

FASES_REFORESTACION = {
    1: {
        "nombre": "1. Establecimiento",
        "temporalidad": "Meses 1 a 12",
        "objetivo": "Evaluar adaptación inicial.",
        "indicadores": ["Porcentaje de supervivencia", "Causas de mortalidad"],
        "color_hex": "#8BC34A",
        "marker_color": "lightgreen",
    },
    2: {
        "nombre": "2. Desarrollo",
        "temporalidad": "Años 2 a 3",
        "objetivo": "Evaluar crecimiento y salud.",
        "indicadores": [
            "Altura y diámetro del tallo",
            "Estado fitosanitario (plagas)",
            "Control de malezas",
        ],
        "color_hex": "#2E8B57",
        "marker_color": "green",
    },
    3: {
        "nombre": "3. Consolidación",
        "temporalidad": "Años 4 a 5+",
        "objetivo": "Verificar autosuficiencia.",
        "indicadores": [
            "Incremento Medio Anual",
            "Retorno de biodiversidad",
            "Regeneración natural",
        ],
        "color_hex": "#0B5D3B",
        "marker_color": "darkgreen",
    },
}

ARCGIS_WEBMAP_ID = "73bcb606bd1f415081f04c8c75a377b4"
ARCGIS_ITEM_DATA_URL = (
    "https://www.arcgis.com/sharing/rest/content/items/"
    f"{ARCGIS_WEBMAP_ID}/data"
)

ZONAS_VALIDAS = [
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
    14, 15, 16, 17, 18, 19, 21, 24, 25,
]

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


# FECHAS Y FASES
def convertir_a_fecha(valor: Any) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        return datetime.strptime(valor, "%Y-%m-%d").date()
    raise ValueError("La fecha no tiene un formato válido.")


def meses_completos_transcurridos(
    fecha_inicio: Any,
    fecha_referencia: date | None = None,
) -> int:
    inicio = convertir_a_fecha(fecha_inicio)
    referencia = fecha_referencia or date.today()
    meses = (
        (referencia.year - inicio.year) * 12
        + referencia.month
        - inicio.month
    )
    if referencia.day < inicio.day:
        meses -= 1
    return max(0, meses)


def calcular_fase_reforestacion(
    fecha_proyecto: Any,
    fecha_referencia: date | None = None,
) -> dict[str, Any]:
    proyecto = convertir_a_fecha(fecha_proyecto)
    referencia = fecha_referencia or date.today()

    if proyecto > referencia:
        raise ValueError("La fecha del proyecto no puede estar en el futuro.")

    meses = meses_completos_transcurridos(proyecto, referencia)
    dias = (referencia - proyecto).days
    numero = 1 if meses < 12 else 2 if meses < 36 else 3
    fase = copy.deepcopy(FASES_REFORESTACION[numero])
    fase.update(
        {
            "numero": numero,
            "meses_transcurridos": meses,
            "dias_transcurridos": dias,
        }
    )

    if dias == 0:
        antiguedad = "Realizado hoy"
    elif meses == 0:
        antiguedad = f"{dias} día" if dias == 1 else f"{dias} días"
    else:
        anios, meses_restantes = divmod(meses, 12)
        partes: list[str] = []
        if anios:
            partes.append(f"{anios} año" if anios == 1 else f"{anios} años")
        if meses_restantes:
            partes.append(
                f"{meses_restantes} mes"
                if meses_restantes == 1
                else f"{meses_restantes} meses"
            )
        antiguedad = " y ".join(partes)

    fase["antiguedad"] = antiguedad
    return fase


def formatear_fecha(fecha_proyecto: Any) -> str:
    return convertir_a_fecha(fecha_proyecto).strftime("%d/%m/%Y")


# GEOMETRÍA VISUAL
def normalizar_feature_dibujo(valor: Any) -> dict[str, Any] | None:
    if not isinstance(valor, dict) or not valor:
        return None
    if valor.get("type") == "Feature":
        return valor
    if valor.get("type") == "FeatureCollection":
        features = valor.get("features", [])
        return features[-1] if features else None
    if valor.get("type") in {"Polygon", "MultiPolygon"}:
        return {"type": "Feature", "properties": {}, "geometry": valor}
    return None


def feature_bounds(feature: dict[str, Any] | None) -> list[list[float]] | None:
    if not feature or not feature.get("geometry"):
        return None
    try:
        min_lon, min_lat, max_lon, max_lat = shape(feature["geometry"]).bounds
        return [[min_lat, min_lon], [max_lat, max_lon]]
    except Exception:
        return None


# CARGA DE ZONAS DE CIUDAD DE GUATEMALA
def normalizar_texto(texto: Any) -> str:
    texto = str(texto).strip()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c)).upper()


def recorrer_capas(capas: list[dict[str, Any]] | None):
    for capa in capas or []:
        yield capa
        subcapas = capa.get("layers", [])
        if subcapas:
            yield from recorrer_capas(subcapas)


def obtener_wkid(
    capa_interna: dict[str, Any],
    feature_set: dict[str, Any],
    geometria: dict[str, Any],
) -> int:
    candidatos = [
        geometria.get("spatialReference", {}),
        feature_set.get("spatialReference", {}),
        capa_interna.get("layerDefinition", {}).get("spatialReference", {}),
        capa_interna.get("layerDefinition", {}).get("extent", {}).get("spatialReference", {}),
    ]
    for referencia in candidatos:
        wkid = referencia.get("latestWkid", referencia.get("wkid"))
        if wkid is not None:
            return int(wkid)
    return 4326


def convertir_xy_a_wgs84(x: float, y: float, wkid: int) -> list[float]:
    x, y = float(x), float(y)

    if wkid in {4326, 4269}:
        return [x, y]

    if wkid in {3857, 102100, 102113, 900913}:
        longitud = (x / 20037508.34) * 180.0
        latitud_aux = (y / 20037508.34) * 180.0
        latitud = 180.0 / math.pi * (
            2.0 * math.atan(math.exp(latitud_aux * math.pi / 180.0))
            - math.pi / 2.0
        )
        return [longitud, latitud]

    if -180 <= x <= 180 and -90 <= y <= 90:
        return [x, y]

    raise RuntimeError(
        f"El sistema de coordenadas WKID {wkid} no está soportado."
    )


def convertir_poligono_esri_a_shapely(
    geometria: dict[str, Any],
    wkid: int,
):
    poligonos_anillo = []

    for anillo in geometria.get("rings", []):
        coordenadas = [
            convertir_xy_a_wgs84(punto[0], punto[1], wkid)
            for punto in anillo
            if len(punto) >= 2
        ]

        if len(coordenadas) < 3:
            continue

        if coordenadas[0] != coordenadas[-1]:
            coordenadas.append(coordenadas[0])

        if len(coordenadas) < 4:
            continue

        poligono = Polygon(coordenadas)
        if not poligono.is_valid:
            poligono = poligono.buffer(0)

        if not poligono.is_empty:
            poligonos_anillo.append(poligono)

    if not poligonos_anillo:
        return None

    geometria_final = GeometryCollection()
    for poligono in poligonos_anillo:
        geometria_final = geometria_final.symmetric_difference(poligono)

    if not geometria_final.is_valid:
        geometria_final = geometria_final.buffer(0)

    return geometria_final if not geometria_final.is_empty else None


def obtener_geojson_desde_feature_collection(
    capa: dict[str, Any],
) -> dict[str, Any] | None:
    feature_collection = capa.get("featureCollection")
    if not feature_collection:
        return None

    features_geojson = []

    for capa_interna in feature_collection.get("layers", []):
        feature_set = capa_interna.get("featureSet", {})
        features = feature_set.get("features", [])
        geometry_type = feature_set.get(
            "geometryType",
            capa_interna.get("layerDefinition", {}).get("geometryType", ""),
        )

        if not features or "Polygon" not in geometry_type:
            continue

        for feature in features:
            geometria_esri = feature.get("geometry", {})
            wkid = obtener_wkid(capa_interna, feature_set, geometria_esri)
            geometria_shapely = convertir_poligono_esri_a_shapely(
                geometria_esri,
                wkid,
            )

            if geometria_shapely is None:
                continue

            features_geojson.append(
                {
                    "type": "Feature",
                    "properties": feature.get("attributes", {}).copy(),
                    "geometry": mapping(geometria_shapely),
                }
            )

    if not features_geojson:
        return None

    return {
        "type": "FeatureCollection",
        "features": features_geojson,
    }


def descargar_geojson_arcgis(url_capa: str) -> dict[str, Any]:
    respuesta = requests.get(
        f"{url_capa.rstrip('/')}/query",
        params={
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        },
        timeout=90,
    )
    respuesta.raise_for_status()
    geojson = respuesta.json()

    if geojson.get("type") != "FeatureCollection":
        raise RuntimeError("ArcGIS no devolvió un FeatureCollection válido.")

    if not geojson.get("features"):
        raise RuntimeError("La capa de zonas no devolvió polígonos.")

    return geojson


def encontrar_capa_de_zonas(datos_mapa: dict[str, Any]) -> dict[str, Any]:
    capas = list(recorrer_capas(datos_mapa.get("operationalLayers", [])))

    for capa in capas:
        if "ZONAS DE LA CIUDAD DE GUATEMALA" in normalizar_texto(
            capa.get("title", "")
        ):
            return capa

    for capa in capas:
        titulo = normalizar_texto(capa.get("title", ""))
        if "ZONA" in titulo and "GUATEMALA" in titulo:
            return capa

    raise RuntimeError(
        "No se encontró la capa de zonas dentro del mapa web de ArcGIS."
    )


def extraer_numero_zona(valor: Any) -> int | None:
    if valor is None or isinstance(valor, bool):
        return None

    if isinstance(valor, (int, float)):
        numero = int(valor)
        return numero if numero in ZONAS_VALIDAS else None

    texto = normalizar_texto(valor)
    patrones = [
        r"\bZONA\D{0,5}(\d{1,2})\b",
        r"\bZ\D{0,3}(\d{1,2})\b",
        r"^0*(\d{1,2})$",
    ]

    for patron in patrones:
        coincidencia = re.search(patron, texto)
        if coincidencia:
            numero = int(coincidencia.group(1))
            if numero in ZONAS_VALIDAS:
                return numero

    return None


def identificar_zona_feature(feature: dict[str, Any]) -> int | None:
    propiedades = feature.get("properties", {})
    prioritarias = [
        clave
        for clave in propiedades
        if "ZONA" in normalizar_texto(clave)
    ]

    for clave in prioritarias:
        numero = extraer_numero_zona(propiedades.get(clave))
        if numero is not None:
            return numero

    for valor in propiedades.values():
        numero = extraer_numero_zona(valor)
        if numero is not None:
            return numero

    return None


def preparar_geojson_zonas(
    geojson_original: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    validas = []

    for feature in geojson_original.get("features", []):
        if not feature.get("geometry"):
            continue

        numero = identificar_zona_feature(feature)
        if numero is None:
            continue

        feature = copy.deepcopy(feature)
        feature.setdefault("properties", {})
        feature["properties"].update(
            {
                "zona_numero": numero,
                "zona_nombre": f"Zona {numero}",
            }
        )
        validas.append(feature)

    if not validas:
        raise RuntimeError(
            "Se descargaron polígonos, pero no se pudo identificar el campo de zona."
        )

    unificadas = []
    lookup = {}

    for numero in ZONAS_VALIDAS:
        features_zona = [
            feature
            for feature in validas
            if feature["properties"]["zona_numero"] == numero
        ]

        if not features_zona:
            continue

        geometria = unary_union(
            [shape(feature["geometry"]) for feature in features_zona]
        )

        feature_unificada = {
            "type": "Feature",
            "properties": {
                "zona_numero": numero,
                "zona_nombre": f"Zona {numero}",
            },
            "geometry": geometria.__geo_interface__,
        }

        unificadas.append(feature_unificada)
        lookup[f"Zona {numero}"] = feature_unificada

    return (
        {
            "type": "FeatureCollection",
            "features": unificadas,
        },
        lookup,
    )


@st.cache_data(ttl=86_400, show_spinner=False)
def cargar_zonas_ciudad_guatemala() -> tuple[
    dict[str, Any],
    dict[str, Any],
    str,
]:
    try:
        respuesta = requests.get(
            ARCGIS_ITEM_DATA_URL,
            params={"f": "json"},
            timeout=60,
        )
        respuesta.raise_for_status()

        capa = encontrar_capa_de_zonas(respuesta.json())
        url_capa = capa.get("url")

        geojson_original = (
            descargar_geojson_arcgis(url_capa)
            if url_capa
            else obtener_geojson_desde_feature_collection(capa)
        )

        if geojson_original is None:
            raise RuntimeError(
                "La capa de zonas no contiene geometría pública utilizable."
            )

        geojson_limpio, lookup = preparar_geojson_zonas(geojson_original)
        return geojson_limpio, lookup, ""

    except Exception as error:
        return {
            "type": "FeatureCollection",
            "features": [],
        }, {}, str(error)


# SECTORES SYNERGY
def convertir_pixel_a_coordenada_synergy(
    x: float,
    y: float,
) -> tuple[float, float]:
    transformacion = TRANSFORMACION_SYNERGY
    longitud = (
        transformacion["lon_x"] * x
        + transformacion["lon_y"] * y
        + transformacion["lon_c"]
    )
    latitud = (
        transformacion["lat_x"] * x
        + transformacion["lat_y"] * y
        + transformacion["lat_c"]
    )
    return latitud, longitud


def preparar_geojson_synergy() -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
]:
    features = []
    lookup = {}

    for nombre_sector in ORDEN_SECTORES_SYNERGY:
        anillo = []

        for x, y in SECTORES_SYNERGY_PIXELES[nombre_sector]:
            latitud, longitud = convertir_pixel_a_coordenada_synergy(x, y)
            anillo.append([longitud, latitud])

        if anillo[0] != anillo[-1]:
            anillo.append(anillo[0])

        feature = {
            "type": "Feature",
            "properties": {
                "sector_nombre": nombre_sector,
                "fuente": "Digitalización aproximada de imagen Google Earth",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [anillo],
            },
        }

        geometria = shape(feature["geometry"])
        if not geometria.is_valid:
            geometria = geometria.buffer(0)
            feature["geometry"] = mapping(geometria)

        features.append(feature)
        lookup[nombre_sector] = feature

    return {
        "type": "FeatureCollection",
        "features": features,
    }, lookup


GEOJSON_SYNERGY, SYNERGY_LOOKUP = preparar_geojson_synergy()
GEOMETRIA_SYNERGY_TOTAL = unary_union(
    [shape(feature["geometry"]) for feature in GEOJSON_SYNERGY["features"]]
)

GEOJSON_ZONAS, ZONE_LOOKUP, ERROR_ZONAS = cargar_zonas_ciudad_guatemala()
ZONE_NAMES = sorted(
    ZONE_LOOKUP,
    key=lambda nombre: int(nombre.split()[-1]),
)


# DATOS DEL FORMULARIO Y ESTADO
def dataframe_arboles_inicial(cantidad: int = 100) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Especie": "Pino",
                "Cantidad": cantidad,
            }
        ]
    )


def inicializar_estado() -> None:
    defaults = {
        "proyectos": [],
        "viveros": [],
        "talas": [],
        "pending_feature": None,
        "map_nonce": 0,
        "form_nonce": 0,
        "form_nonce_vivero": 0,
        "form_nonce_tala": 0,
        "area_general": "Ciudad de Guatemala",
        "ubicacion": (
            ZONE_NAMES[0]
            if ZONE_NAMES
            else ORDEN_SECTORES_SYNERGY[0]
        ),
        "view_mode": "all",
        "flash_message": "",
        "next_project_number": 1,
        "next_vivero_number": 1,
        "next_tala_number": 1,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = copy.deepcopy(value)


def limpiar_dibujo_estado() -> None:
    st.session_state.pending_feature = None
    st.session_state.map_nonce += 1


def opciones_ubicacion_actuales() -> list[str]:
    if st.session_state.area_general == "Ciudad de Guatemala":
        return ZONE_NAMES or ["Zonas no disponibles"]
    return ORDEN_SECTORES_SYNERGY


def cambio_area_general() -> None:
    opciones = (
        ZONE_NAMES
        if st.session_state.area_general == "Ciudad de Guatemala"
        else ORDEN_SECTORES_SYNERGY
    )
    st.session_state.ubicacion = opciones[0] if opciones else "Sin datos"
    st.session_state.view_mode = "selection"
    limpiar_dibujo_estado()


def cambio_ubicacion() -> None:
    st.session_state.view_mode = "selection"
    limpiar_dibujo_estado()


def resetear_formulario() -> None:
    st.session_state.form_nonce += 1
    st.session_state.area_general = "Ciudad de Guatemala"
    st.session_state.ubicacion = (
        ZONE_NAMES[0]
        if ZONE_NAMES
        else ORDEN_SECTORES_SYNERGY[0]
    )
    st.session_state.view_mode = "all"
    st.session_state.flash_message = "Formulario restablecido."
    limpiar_dibujo_estado()


def resetear_todo() -> None:
    st.session_state.proyectos = []
    st.session_state.viveros = []
    st.session_state.talas = []
    st.session_state.next_project_number = 1
    st.session_state.next_vivero_number = 1
    st.session_state.next_tala_number = 1
    st.session_state.form_nonce_vivero += 1
    st.session_state.form_nonce_tala += 1
    resetear_formulario()
    st.session_state.flash_message = (
        "Se eliminaron los proyectos, inventarios de vivero "
        "y registros de tala."
    )


inicializar_estado()


# FUNCIONES GENERALES DE ÁRBOLES
def consolidar_arboles(editor: pd.DataFrame) -> list[dict[str, Any]]:
    acumulado: dict[str, int] = {}
    orden: list[str] = []

    for _, fila in editor.iterrows():
        especie = fila.get("Especie")
        cantidad = fila.get("Cantidad")

        if pd.isna(especie) or pd.isna(cantidad):
            continue

        especie = str(especie).strip()

        try:
            cantidad = int(cantidad)
        except (TypeError, ValueError):
            continue

        if especie not in TREE_IMPACT_DATA or cantidad <= 0:
            continue

        if especie not in acumulado:
            acumulado[especie] = 0
            orden.append(especie)

        acumulado[especie] += cantidad

    return [
        {
            "tipo": especie,
            "cantidad": acumulado[especie],
            "impacto_por_arbol": TREE_IMPACT_DATA[especie],
            "impacto_estimado_m2": (
                acumulado[especie]
                * TREE_IMPACT_DATA[especie]
            ),
        }
        for especie in orden
    ]


def totalizar_arboles(
    arboles: list[dict[str, Any]],
) -> tuple[int, float]:
    cantidad_total = sum(
        arbol["cantidad"]
        for arbol in arboles
    )
    impacto_total = sum(
        arbol["impacto_estimado_m2"]
        for arbol in arboles
    )
    return cantidad_total, impacto_total


def composicion_arboles_texto(
    arboles: list[dict[str, Any]],
) -> str:
    return "; ".join(
        f"{arbol['tipo']}: {arbol['cantidad']:,}"
        for arbol in arboles
    )


# FUNCIONES DE PROYECTOS Y VALIDACIÓN
def referencia_seleccionada() -> dict[str, Any] | None:
    if st.session_state.area_general == "Ciudad de Guatemala":
        return ZONE_LOOKUP.get(st.session_state.ubicacion)
    return SYNERGY_LOOKUP.get(st.session_state.ubicacion)


def validar_poligono_seleccionado(
    feature: dict[str, Any],
) -> str:
    referencia = referencia_seleccionada()

    if referencia is None:
        return ""

    try:
        geometria_proyecto = shape(feature["geometry"])
        punto_central = geometria_proyecto.representative_point()
        geometria_referencia = shape(referencia["geometry"])

        if not geometria_referencia.buffer(0.002).contains(punto_central):
            return (
                "El centro del dibujo está fuera de la ubicación seleccionada. "
                "El proyecto se guardó, pero conviene revisar la referencia visual."
            )
    except Exception:
        return ""

    return ""


def preparar_proyecto(
    nombre: str,
    fecha_proyecto: date,
    arboles: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str, str]:
    if not nombre.strip():
        return None, "El nombre del proyecto no puede quedar vacío.", ""

    if fecha_proyecto > date.today():
        return None, "La fecha del proyecto no puede estar en el futuro.", ""

    if not arboles:
        return None, (
            "Agrega al menos una especie con una cantidad mayor que cero."
        ), ""

    feature = None
    advertencia = ""

    if st.session_state.pending_feature is not None:
        feature = copy.deepcopy(st.session_state.pending_feature)

        try:
            geometria = shape(feature["geometry"])

            if geometria.is_empty:
                raise ValueError("Geometría vacía")

            if not geometria.is_valid:
                geometria = geometria.buffer(0)

            if geometria.is_empty:
                raise ValueError("Geometría inválida")

            feature["geometry"] = mapping(geometria)
            advertencia = validar_poligono_seleccionado(feature)

        except Exception:
            return None, (
                "El dibujo no es válido. Bórralo o vuelve a dibujarlo."
            ), ""

    cantidad_total, impacto_estimado = totalizar_arboles(arboles)
    area_general = st.session_state.area_general

    proyecto = {
        "numero": st.session_state.next_project_number,
        "nombre": nombre.strip(),
        "area_general": area_general,
        "ubicacion": st.session_state.ubicacion,
        "tipo_ubicacion": (
            "Zona"
            if area_general == "Ciudad de Guatemala"
            else "Sector"
        ),
        "arboles": copy.deepcopy(arboles),
        "cantidad_total": cantidad_total,
        "fecha_proyecto": fecha_proyecto.isoformat(),
        "impacto_estimado_m2": impacto_estimado,

        # El dibujo solo es una referencia visual aproximada.
        "poligono_geojson": feature,
    }

    return proyecto, "", advertencia


def eliminar_proyecto(numero: int) -> None:
    st.session_state.proyectos = [
        proyecto
        for proyecto in st.session_state.proyectos
        if proyecto["numero"] != numero
    ]
    st.session_state.flash_message = f"Proyecto {numero} eliminado."
    st.session_state.map_nonce += 1


# FUNCIONES DE VIVEROS
def guardar_o_actualizar_vivero(
    nombre: str,
    ubicacion: str,
    fecha_actualizacion: date,
    arboles: list[dict[str, Any]],
) -> tuple[bool, str]:
    nombre = nombre.strip()
    ubicacion = ubicacion.strip()

    if not nombre:
        return False, "El nombre del vivero no puede quedar vacío."

    if not ubicacion:
        return False, "Ingresa la ubicación del vivero."

    if fecha_actualizacion > date.today():
        return False, "La fecha de actualización no puede estar en el futuro."

    if not arboles:
        return False, "Agrega al menos una especie al inventario del vivero."

    cantidad_total, impacto_potencial = totalizar_arboles(arboles)

    indice_existente = next(
        (
            indice
            for indice, vivero in enumerate(st.session_state.viveros)
            if normalizar_texto(vivero["nombre"])
            == normalizar_texto(nombre)
        ),
        None,
    )

    if indice_existente is None:
        numero = st.session_state.next_vivero_number
        vivero = {
            "numero": numero,
            "nombre": nombre,
            "ubicacion": ubicacion,
            "fecha_actualizacion": fecha_actualizacion.isoformat(),
            "arboles": copy.deepcopy(arboles),
            "cantidad_total": cantidad_total,
            "impacto_potencial_m2": impacto_potencial,
        }
        st.session_state.viveros.append(vivero)
        st.session_state.next_vivero_number += 1
        return True, f"Vivero {nombre} registrado correctamente."

    numero = st.session_state.viveros[indice_existente]["numero"]
    st.session_state.viveros[indice_existente] = {
        "numero": numero,
        "nombre": nombre,
        "ubicacion": ubicacion,
        "fecha_actualizacion": fecha_actualizacion.isoformat(),
        "arboles": copy.deepcopy(arboles),
        "cantidad_total": cantidad_total,
        "impacto_potencial_m2": impacto_potencial,
    }

    return True, (
        f"Inventario del vivero {nombre} actualizado correctamente."
    )


def eliminar_vivero(numero: int) -> None:
    st.session_state.viveros = [
        vivero
        for vivero in st.session_state.viveros
        if vivero["numero"] != numero
    ]
    st.session_state.flash_message = f"Vivero {numero} eliminado."


# FUNCIONES DE TALA
def registrar_tala(
    nombre_obra: str,
    fecha_tala: date,
    area_general: str,
    ubicacion: str,
    motivo: str,
    permiso_referencia: str,
    arboles: list[dict[str, Any]],
) -> tuple[bool, str]:
    nombre_obra = nombre_obra.strip()
    motivo = motivo.strip()
    permiso_referencia = permiso_referencia.strip()

    if not nombre_obra:
        return False, "Ingresa el nombre de la obra o proyecto asociado."

    if fecha_tala > date.today():
        return False, "La fecha de tala no puede estar en el futuro."

    if not ubicacion or ubicacion == "Zonas no disponibles":
        return False, "Selecciona una zona o sector válido."

    if not arboles:
        return False, "Agrega al menos una especie y cantidad talada."

    cantidad_total, impacto_removido = totalizar_arboles(arboles)

    registro = {
        "numero": st.session_state.next_tala_number,
        "nombre_obra": nombre_obra,
        "fecha_tala": fecha_tala.isoformat(),
        "area_general": area_general,
        "ubicacion": ubicacion,
        "tipo_ubicacion": (
            "Zona"
            if area_general == "Ciudad de Guatemala"
            else "Sector"
        ),
        "motivo": motivo,
        "permiso_referencia": permiso_referencia,
        "arboles": copy.deepcopy(arboles),
        "cantidad_total": cantidad_total,
        "impacto_removido_m2": impacto_removido,
    }

    st.session_state.talas.append(registro)
    st.session_state.next_tala_number += 1

    return True, (
        f"Registro de tala guardado: "
        f"{cantidad_total:,} árbol(es) removido(s)."
    )


def eliminar_tala(numero: int) -> None:
    st.session_state.talas = [
        tala
        for tala in st.session_state.talas
        if tala["numero"] != numero
    ]
    st.session_state.flash_message = (
        f"Registro de tala {numero} eliminado."
    )


# MAPA
def bounds_ambas_areas() -> list[list[float]]:
    geometrias = [GEOMETRIA_SYNERGY_TOTAL]

    if GEOJSON_ZONAS.get("features"):
        geometrias.append(
            unary_union(
                [
                    shape(feature["geometry"])
                    for feature in GEOJSON_ZONAS["features"]
                ]
            )
        )

    union = unary_union(geometrias)
    min_lon, min_lat, max_lon, max_lat = union.bounds
    return [[min_lat, min_lon], [max_lat, max_lon]]


def popup_proyecto(
    proyecto: dict[str, Any],
    fase: dict[str, Any],
) -> str:
    detalle = "".join(
        f"<li><b>{arbol['tipo']}:</b> "
        f"{arbol['cantidad']:,} árboles "
        f"({arbol['impacto_estimado_m2']:,.0f} m² estimados)</li>"
        for arbol in proyecto["arboles"]
    )

    return f"""
    <div style="font-family:Arial; width:330px; line-height:1.5;">
        <h4 style="color:{fase['color_hex']}; margin:0 0 8px;">
            Proyecto {proyecto['numero']}: {proyecto['nombre']}
        </h4>
        <b>Área general:</b> {proyecto['area_general']}<br>
        <b>{proyecto['tipo_ubicacion']}:</b> {proyecto['ubicacion']}<br>
        <b>Fecha:</b> {formatear_fecha(proyecto['fecha_proyecto'])}<br>
        <b>Fase:</b> {fase['nombre']}<br>
        <b>Antigüedad:</b> {fase['antiguedad']}<br>
        <b>Composición:</b>
        <ul style="margin:4px 0 8px 18px; padding:0;">{detalle}</ul>
        <b>Total de árboles:</b> {proyecto['cantidad_total']:,}<br>
        <b>Impacto arbóreo estimado:</b>
        {proyecto['impacto_estimado_m2']:,.0f} m²
        <hr>
        <span style="font-size:12px; color:#607D8B;">
            El polígono representa una ubicación aproximada y no una
            medición oficial de superficie.
        </span>
    </div>
    """


def construir_mapa() -> folium.Map:
    mapa = folium.Map(
        location=[14.49, -90.63],
        zoom_start=10,
        tiles="CartoDB positron",
        control_scale=True,
        prefer_canvas=True,
    )

    if GEOJSON_ZONAS.get("features"):
        folium.GeoJson(
            GEOJSON_ZONAS,
            name="Zonas de Ciudad de Guatemala",
            style_function=lambda _: {
                "fillColor": "#F2F2F2",
                "color": "#607D8B",
                "weight": 1.2,
                "fillOpacity": 0.08,
            },
            highlight_function=lambda _: {
                "fillColor": "#DFF3E7",
                "color": "#087F23",
                "weight": 2.5,
                "fillOpacity": 0.25,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["zona_nombre"],
                aliases=["Zona:"],
            ),
        ).add_to(mapa)

    folium.GeoJson(
        GEOJSON_SYNERGY,
        name="Sectores del master plan de Synergy",
        style_function=lambda _: {
            "fillColor": "#EAF5EC",
            "color": "#0B5D3B",
            "weight": 2.2,
            "fillOpacity": 0.16,
        },
        highlight_function=lambda _: {
            "fillColor": "#9CCC65",
            "color": "#173B57",
            "weight": 3.2,
            "fillOpacity": 0.38,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["sector_nombre"],
            aliases=["Sector:"],
        ),
    ).add_to(mapa)

    centros = folium.FeatureGroup(
        name="Centros de sectores Synergy",
        show=False,
    )

    for nombre, feature in SYNERGY_LOOKUP.items():
        centro = shape(feature["geometry"]).representative_point()
        folium.CircleMarker(
            location=[centro.y, centro.x],
            radius=4,
            color="#173B57",
            weight=2,
            fill=True,
            fill_color="#FFFFFF",
            fill_opacity=0.95,
            popup=f"<b>Sector {nombre}</b>",
        ).add_to(centros)

    centros.add_to(mapa)

    seleccion = referencia_seleccionada()

    if seleccion is not None:
        folium.GeoJson(
            seleccion,
            name="Ubicación seleccionada",
            style_function=lambda _: {
                "fillColor": (
                    "#9CCC65"
                    if st.session_state.area_general == "Synergy"
                    else "#DFF3E7"
                ),
                "color": (
                    "#173B57"
                    if st.session_state.area_general == "Synergy"
                    else "#087F23"
                ),
                "weight": 4,
                "fillOpacity": 0.40,
            },
        ).add_to(mapa)

    proyectos_group = folium.FeatureGroup(
        name="Ubicaciones visuales de proyectos",
        show=True,
    )

    for proyecto in st.session_state.proyectos:
        feature_original = proyecto.get("poligono_geojson")

        if not feature_original:
            continue

        fase = calcular_fase_reforestacion(
            proyecto["fecha_proyecto"]
        )
        color = fase["color_hex"]
        feature = copy.deepcopy(feature_original)
        feature.setdefault("properties", {}).update(
            {
                "proyecto": proyecto["numero"],
                "nombre": proyecto["nombre"],
                "ubicacion": proyecto["ubicacion"],
                "referencia_visual": True,
            }
        )

        folium.GeoJson(
            feature,
            style_function=lambda _, c=color: {
                "fillColor": c,
                "color": c,
                "weight": 3,
                "fillOpacity": 0.48,
            },
            highlight_function=lambda _, c=color: {
                "fillColor": c,
                "color": "#173B57",
                "weight": 4,
                "fillOpacity": 0.68,
            },
            tooltip=(
                f"Proyecto {proyecto['numero']} · "
                f"{proyecto['nombre']} · "
                f"{proyecto['ubicacion']}"
            ),
        ).add_to(proyectos_group)

        centro = shape(feature["geometry"]).representative_point()
        folium.Marker(
            [centro.y, centro.x],
            tooltip=(
                f"Proyecto {proyecto['numero']} - "
                f"{proyecto['ubicacion']}"
            ),
            popup=folium.Popup(
                popup_proyecto(proyecto, fase),
                max_width=380,
            ),
            icon=folium.Icon(
                color=fase["marker_color"],
                icon="tree",
                prefix="fa",
            ),
        ).add_to(proyectos_group)

    proyectos_group.add_to(mapa)

    Draw(
        export=False,
        position="topleft",
        draw_options={
            "polygon": {
                "shapeOptions": {
                    "color": "#0B5D3B",
                    "weight": 3,
                    "fillColor": "#2E8B57",
                    "fillOpacity": 0.45,
                }
            },
            "rectangle": {
                "shapeOptions": {
                    "color": "#173B57",
                    "weight": 3,
                    "fillColor": "#4CAF50",
                    "fillOpacity": 0.40,
                }
            },
            "polyline": False,
            "circle": False,
            "marker": False,
            "circlemarker": False,
        },
        edit_options={
            "edit": True,
            "remove": True,
        },
    ).add_to(mapa)

    Fullscreen(position="topright").add_to(mapa)
    folium.LayerControl(
        position="topright",
        collapsed=True,
    ).add_to(mapa)

    if (
        st.session_state.view_mode == "selection"
        and seleccion is not None
    ):
        bounds = feature_bounds(seleccion)
        if bounds:
            mapa.fit_bounds(bounds, padding=(20, 20))
    else:
        mapa.fit_bounds(
            bounds_ambas_areas(),
            padding=(18, 18),
        )

    return mapa


def sincronizar_dibujo(
    resultado_mapa: dict[str, Any] | None,
) -> None:
    if not resultado_mapa or "all_drawings" not in resultado_mapa:
        return

    dibujos = resultado_mapa.get("all_drawings")

    if dibujos is None:
        return

    if not dibujos:
        st.session_state.pending_feature = None
        return

    feature = normalizar_feature_dibujo(dibujos[-1])

    if feature is None:
        return

    geometria = feature.get("geometry", {})

    if geometria.get("type") not in {
        "Polygon",
        "MultiPolygon",
    }:
        return

    # No se calcula área. Se conserva solamente la geometría visual.
    st.session_state.pending_feature = copy.deepcopy(feature)


# MÉTRICAS Y EXPORTACIÓN
def calcular_totales() -> dict[str, float | int]:
    total_plantados = sum(
        proyecto["cantidad_total"]
        for proyecto in st.session_state.proyectos
    )

    total_vivero = sum(
        vivero["cantidad_total"]
        for vivero in st.session_state.viveros
    )

    total_talados = sum(
        tala["cantidad_total"]
        for tala in st.session_state.talas
    )

    total_impacto_plantado = sum(
        proyecto["impacto_estimado_m2"]
        for proyecto in st.session_state.proyectos
    )

    total_impacto_vivero = sum(
        vivero["impacto_potencial_m2"]
        for vivero in st.session_state.viveros
    )

    total_impacto_removido = sum(
        tala["impacto_removido_m2"]
        for tala in st.session_state.talas
    )

    return {
        "total_plantados": total_plantados,
        "total_vivero": total_vivero,
        "total_talados": total_talados,
        "balance_campo": total_plantados - total_talados,
        "balance_total": (
            total_plantados
            + total_vivero
            - total_talados
        ),
        "impacto_plantado_m2": total_impacto_plantado,
        "impacto_vivero_m2": total_impacto_vivero,
        "impacto_removido_m2": total_impacto_removido,
        "impacto_neto_campo_m2": (
            total_impacto_plantado
            - total_impacto_removido
        ),
    }


def proyectos_dataframe() -> pd.DataFrame:
    filas = []

    for proyecto in st.session_state.proyectos:
        fase = calcular_fase_reforestacion(
            proyecto["fecha_proyecto"]
        )

        filas.append(
            {
                "Proyecto": proyecto["numero"],
                "Nombre": proyecto["nombre"],
                "Área general": proyecto["area_general"],
                "Zona / sector": proyecto["ubicacion"],
                "Fecha": formatear_fecha(
                    proyecto["fecha_proyecto"]
                ),
                "Fase": fase["nombre"],
                "Antigüedad": fase["antiguedad"],
                "Composición de árboles": composicion_arboles_texto(
                    proyecto["arboles"]
                ),
                "Total árboles": proyecto["cantidad_total"],
                "Referencia en mapa": (
                    "Sí"
                    if proyecto.get("poligono_geojson")
                    else "No"
                ),
                "Impacto estimado m²": round(
                    proyecto["impacto_estimado_m2"],
                    2,
                ),
            }
        )

    return pd.DataFrame(filas)


def viveros_dataframe() -> pd.DataFrame:
    filas = []

    for vivero in st.session_state.viveros:
        filas.append(
            {
                "Vivero": vivero["numero"],
                "Nombre": vivero["nombre"],
                "Ubicación": vivero["ubicacion"],
                "Última actualización": formatear_fecha(
                    vivero["fecha_actualizacion"]
                ),
                "Composición": composicion_arboles_texto(
                    vivero["arboles"]
                ),
                "Árboles disponibles": vivero["cantidad_total"],
                "Impacto potencial m²": round(
                    vivero["impacto_potencial_m2"],
                    2,
                ),
            }
        )

    return pd.DataFrame(filas)


def talas_dataframe() -> pd.DataFrame:
    filas = []

    for tala in st.session_state.talas:
        filas.append(
            {
                "Registro": tala["numero"],
                "Proyecto u obra": tala["nombre_obra"],
                "Fecha": formatear_fecha(tala["fecha_tala"]),
                "Área general": tala["area_general"],
                "Zona / sector": tala["ubicacion"],
                "Composición": composicion_arboles_texto(
                    tala["arboles"]
                ),
                "Árboles talados": tala["cantidad_total"],
                "Impacto removido m²": round(
                    tala["impacto_removido_m2"],
                    2,
                ),
                "Motivo": tala["motivo"],
                "Permiso / referencia": tala["permiso_referencia"],
            }
        )

    return pd.DataFrame(filas)


def proyecto_a_geojson_feature(
    proyecto: dict[str, Any],
) -> dict[str, Any] | None:
    poligono = proyecto.get("poligono_geojson")

    if not poligono:
        return None

    feature = copy.deepcopy(poligono)
    feature.setdefault("properties", {}).update(
        {
            "numero": proyecto["numero"],
            "nombre": proyecto["nombre"],
            "area_general": proyecto["area_general"],
            "ubicacion": proyecto["ubicacion"],
            "fecha_proyecto": proyecto["fecha_proyecto"],
            "cantidad_total": proyecto["cantidad_total"],
            "impacto_estimado_m2": proyecto["impacto_estimado_m2"],
            "arboles": proyecto["arboles"],
            "tipo_geometria": "Referencia visual aproximada",
        }
    )

    return feature


# INTERFAZ
st.markdown(
    """
    <div class="spectrum-header">
        <h1>Reforestación Spectrum</h1>
        <p>
            Plataforma de registro y seguimiento de reforestación,
            viveros y deforestación
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

if ERROR_ZONAS:
    st.warning(
        "No fue posible cargar temporalmente las zonas de Ciudad de "
        "Guatemala desde ArcGIS. Los sectores de Synergy siguen "
        f"disponibles. Detalle técnico: {ERROR_ZONAS}"
    )

if st.session_state.flash_message:
    st.toast(st.session_state.flash_message)
    st.session_state.flash_message = ""

with st.expander("¿Cómo utilizar la plataforma?", expanded=False):
    st.markdown(
        "**Reforestación:** selecciona la zona o sector, registra las "
        "especies, cantidades y fecha. El dibujo en el mapa es opcional "
        "y funciona únicamente como referencia visual aproximada.  "
        "\n\n**Viveros:** registra el inventario actual por especie. Si "
        "vuelves a guardar un vivero con el mismo nombre, su inventario "
        "se actualiza en lugar de duplicarse.  "
        "\n\n**Tala:** registra los árboles removidos por construcción, "
        "incluyendo la obra, ubicación, motivo y permiso.  "
        "\n\n**Balance:** árboles plantados + árboles disponibles en "
        "viveros − árboles talados."
    )


# MÉTRICAS ACUMULADAS SUPERIORES
totales = calcular_totales()
metricas = st.columns(5)

metricas[0].metric(
    "Proyectos",
    len(st.session_state.proyectos),
)
metricas[1].metric(
    "Árboles plantados",
    f"{totales['total_plantados']:,}",
)
metricas[2].metric(
    "Árboles en viveros",
    f"{totales['total_vivero']:,}",
)
metricas[3].metric(
    "Árboles talados",
    f"{totales['total_talados']:,}",
    delta=(
        f"-{totales['total_talados']:,}"
        if totales["total_talados"]
        else None
    ),
    delta_color="normal",
)
metricas[4].metric(
    "Balance arbóreo total",
    f"{totales['balance_total']:,}",
    help=(
        "Árboles plantados + inventario actual de viveros "
        "− árboles talados."
    ),
)

st.markdown(
    crear_panel_comparacion_superficies(
        impacto_neto_campo_m2=totales["impacto_neto_campo_m2"],
        impacto_plantado_m2=totales["impacto_plantado_m2"],
        impacto_removido_m2=totales["impacto_removido_m2"],
    ),
    unsafe_allow_html=True,
)

st.divider()
st.subheader("Registrar proyecto de reforestación")
col_mapa, col_form = st.columns([1.75, 1], gap="large")


# PRIMER BLOQUE DEL FORMULARIO
with col_form:
    st.radio(
        "Área general",
        ["Ciudad de Guatemala", "Synergy"],
        key="area_general",
        horizontal=True,
        on_change=cambio_area_general,
    )

    opciones = opciones_ubicacion_actuales()

    if st.session_state.ubicacion not in opciones:
        st.session_state.ubicacion = opciones[0]

    st.selectbox(
        (
            "Zona"
            if st.session_state.area_general == "Ciudad de Guatemala"
            else "Sector"
        ),
        opciones,
        key="ubicacion",
        on_change=cambio_ubicacion,
        disabled=(opciones == ["Zonas no disponibles"]),
    )

    acciones_mapa = st.columns(3)

    if acciones_mapa[0].button(
        "Centrar",
        use_container_width=True,
        help="Centra el mapa en la zona o sector seleccionado",
    ):
        st.session_state.view_mode = "selection"
        st.session_state.map_nonce += 1
        st.rerun()

    if acciones_mapa[1].button(
        "Ver ambas",
        use_container_width=True,
    ):
        st.session_state.view_mode = "all"
        st.session_state.map_nonce += 1
        st.rerun()

    acciones_mapa[2].button(
        "Borrar dibujo",
        use_container_width=True,
        on_click=limpiar_dibujo_estado,
        help=(
            "Elimina el dibujo pendiente sin borrar proyectos guardados"
        ),
    )


# MAPA
with col_mapa:
    st.subheader("Mapa interactivo")
    st.markdown(
        """
        <div class='info-box'>
            <b>Dibuja la ubicación aproximada del proyecto.</b><br>
            El dibujo es opcional y se utiliza únicamente como referencia
            visual. No representa una medición oficial y no se usa para
            calcular metros cuadrados, hectáreas o manzanas.
        </div>
        """,
        unsafe_allow_html=True,
    )

    resultado_mapa = st_folium(
        construir_mapa(),
        height=650,
        use_container_width=True,
        returned_objects=["all_drawings"],
        key=(
            f"mapa_reforestacion_"
            f"{st.session_state.map_nonce}"
        ),
    )

    sincronizar_dibujo(resultado_mapa)


# SEGUNDO BLOQUE DEL FORMULARIO
with col_form:
    nonce = st.session_state.form_nonce

    nombre_proyecto = st.text_input(
        "Nombre del proyecto",
        value="Jornada de Reforestación",
        key=f"nombre_proyecto_{nonce}",
    )

    fecha_proyecto = st.date_input(
        "Fecha del proyecto",
        value=date.today(),
        max_value=date.today(),
        key=f"fecha_proyecto_{nonce}",
    )

    st.markdown("**Composición de árboles**")
    st.caption(
        "Agrega o elimina filas. Las especies repetidas se "
        "consolidan al guardar."
    )

    editor_arboles = st.data_editor(
        dataframe_arboles_inicial(),
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key=f"editor_arboles_{nonce}",
        column_config={
            "Especie": st.column_config.SelectboxColumn(
                "Tipo de árbol",
                options=list(TREE_IMPACT_DATA),
                required=True,
                width="medium",
            ),
            "Cantidad": st.column_config.NumberColumn(
                "Cantidad",
                min_value=1,
                max_value=100_000,
                step=1,
                required=True,
                format="%d",
                width="small",
            ),
        },
    )

    arboles = consolidar_arboles(editor_arboles)
    cantidad_total, impacto_estimado = totalizar_arboles(arboles)

    if st.session_state.pending_feature is not None:
        st.markdown(
            """
            <div class='info-box area-ok'>
                <b>Referencia visual registrada</b><br>
                El dibujo se guardará como una ubicación aproximada del
                proyecto y no generará cálculos de superficie.
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class='info-box area-pending'>
                <b>Sin referencia visual:</b>
                puedes guardar el proyecto sin dibujar o utilizar el mapa
                para indicar aproximadamente dónde se realizó.
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.markdown("**Vista previa del proyecto**")
        vista = st.columns(3)

        vista[0].metric(
            "Referencia visual",
            (
                "Dibujada"
                if st.session_state.pending_feature is not None
                else "Opcional"
            ),
        )
        vista[1].metric(
            "Árboles",
            f"{cantidad_total:,}",
        )
        vista[2].metric(
            "Impacto estimado",
            f"{impacto_estimado:,.0f} m²",
            help=(
                "Estimación basada en la especie y cantidad de árboles, "
                "no en el tamaño del dibujo."
            ),
        )

        if arboles:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Tipo": arbol["tipo"],
                            "Cantidad": arbol["cantidad"],
                            "Impacto estimado m²": arbol[
                                "impacto_estimado_m2"
                            ],
                        }
                        for arbol in arboles
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )

    guardar, limpiar, reiniciar = st.columns(3)

    guardar_click = guardar.button(
        "Guardar proyecto",
        type="primary",
        use_container_width=True,
    )

    limpiar.button(
        "Limpiar formulario",
        use_container_width=True,
        on_click=resetear_formulario,
    )

    reiniciar.button(
        "Reiniciar todo",
        use_container_width=True,
        on_click=resetear_todo,
    )

    if guardar_click:
        proyecto, error, advertencia = preparar_proyecto(
            nombre_proyecto,
            fecha_proyecto,
            arboles,
        )

        if error:
            st.error(error)

        elif proyecto is not None:
            st.session_state.proyectos.append(proyecto)
            st.session_state.next_project_number += 1
            st.session_state.form_nonce += 1
            limpiar_dibujo_estado()

            st.session_state.flash_message = (
                f"Proyecto {proyecto['numero']} guardado. "
                f"{advertencia}"
                if advertencia
                else (
                    f"Proyecto {proyecto['numero']} "
                    "guardado correctamente."
                )
            )
            st.rerun()


# VIVEROS Y TALA
st.divider()
st.subheader("Gestión de viveros y tala")
tab_vivero, tab_tala = st.tabs(
    ["Inventario de viveros", "Registro deforestación"]
)

with tab_vivero:
    st.markdown("### Registrar o actualizar vivero")
    st.caption(
        "El vivero representa inventario actual. Si utilizas el mismo "
        "nombre, el registro se actualiza y no se suma dos veces."
    )

    nonce_vivero = st.session_state.form_nonce_vivero

    with st.form(f"formulario_vivero_{nonce_vivero}"):
        vivero_cols = st.columns(2)

        nombre_vivero = vivero_cols[0].text_input(
            "Nombre del vivero",
            placeholder="Ej. Vivero Synergy",
        )

        ubicacion_vivero = vivero_cols[1].text_input(
            "Ubicación del vivero",
            placeholder="Ej. San José Pinula, Guatemala",
        )

        fecha_inventario = st.date_input(
            "Fecha de actualización del inventario",
            value=date.today(),
            max_value=date.today(),
        )

        st.markdown("**Inventario actual por especie**")

        editor_vivero = st.data_editor(
            dataframe_arboles_inicial(),
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            key=f"editor_vivero_{nonce_vivero}",
            column_config={
                "Especie": st.column_config.SelectboxColumn(
                    "Tipo de árbol",
                    options=list(TREE_IMPACT_DATA),
                    required=True,
                    width="medium",
                ),
                "Cantidad": st.column_config.NumberColumn(
                    "Cantidad disponible",
                    min_value=1,
                    max_value=1_000_000,
                    step=1,
                    required=True,
                    format="%d",
                ),
            },
        )

        guardar_vivero_click = st.form_submit_button(
            "Guardar inventario",
            type="primary",
            use_container_width=True,
        )

    if guardar_vivero_click:
        arboles_vivero = consolidar_arboles(editor_vivero)
        guardado, mensaje = guardar_o_actualizar_vivero(
            nombre=nombre_vivero,
            ubicacion=ubicacion_vivero,
            fecha_actualizacion=fecha_inventario,
            arboles=arboles_vivero,
        )

        if guardado:
            st.session_state.form_nonce_vivero += 1
            st.session_state.flash_message = mensaje
            st.rerun()
        else:
            st.error(mensaje)


with tab_tala:
    st.markdown("### Registrar árboles talados")
    st.caption(
        "Este registro resta árboles del balance arbóreo. El impacto "
        "removido se estima por especie y cantidad, no por un polígono."
    )

    nonce_tala = st.session_state.form_nonce_tala

    with st.form(f"formulario_tala_{nonce_tala}"):
        nombre_obra = st.text_input(
            "Proyecto u obra asociada",
            placeholder="Ej. Construcción edificio C3",
        )

        fecha_tala = st.date_input(
            "Fecha de tala",
            value=date.today(),
            max_value=date.today(),
        )

        area_tala = st.radio(
            "Área general",
            ["Ciudad de Guatemala", "Synergy"],
            horizontal=True,
            key=f"area_tala_{nonce_tala}",
        )

        opciones_tala = (
            (ZONE_NAMES or ["Zonas no disponibles"])
            if area_tala == "Ciudad de Guatemala"
            else ORDEN_SECTORES_SYNERGY
        )

        ubicacion_tala = st.selectbox(
            (
                "Zona"
                if area_tala == "Ciudad de Guatemala"
                else "Sector"
            ),
            opciones_tala,
            disabled=(opciones_tala == ["Zonas no disponibles"]),
        )

        motivo_tala = st.text_area(
            "Motivo de la tala",
            placeholder=(
                "Ej. Liberación del terreno para construcción, "
                "árboles en riesgo o intervención autorizada."
            ),
        )

        permiso_referencia = st.text_input(
            "Permiso o referencia",
            placeholder="Número de licencia, resolución o expediente",
        )

        st.markdown("**Árboles removidos por especie**")

        editor_tala = st.data_editor(
            dataframe_arboles_inicial(cantidad=1),
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            key=f"editor_tala_{nonce_tala}",
            column_config={
                "Especie": st.column_config.SelectboxColumn(
                    "Tipo de árbol",
                    options=list(TREE_IMPACT_DATA),
                    required=True,
                    width="medium",
                ),
                "Cantidad": st.column_config.NumberColumn(
                    "Cantidad talada",
                    min_value=1,
                    max_value=100_000,
                    step=1,
                    required=True,
                    format="%d",
                ),
            },
        )

        guardar_tala_click = st.form_submit_button(
            "Guardar registro de tala",
            type="primary",
            use_container_width=True,
        )

    if guardar_tala_click:
        arboles_talados = consolidar_arboles(editor_tala)
        guardado, mensaje = registrar_tala(
            nombre_obra=nombre_obra,
            fecha_tala=fecha_tala,
            area_general=area_tala,
            ubicacion=ubicacion_tala,
            motivo=motivo_tala,
            permiso_referencia=permiso_referencia,
            arboles=arboles_talados,
        )

        if guardado:
            st.session_state.form_nonce_tala += 1
            st.session_state.flash_message = mensaje
            st.rerun()
        else:
            st.error(mensaje)


# TABLERO DE SEGUIMIENTO
st.divider()
st.subheader("Tablero de seguimiento")
totales = calcular_totales()

resumen = st.columns(5)
resumen[0].metric(
    "Proyectos",
    len(st.session_state.proyectos),
)
resumen[1].metric(
    "Viveros",
    len(st.session_state.viveros),
)
resumen[2].metric(
    "Registros de tala",
    len(st.session_state.talas),
)
resumen[3].metric(
    "Balance en campo",
    f"{totales['balance_campo']:,}",
)
resumen[4].metric(
    "Balance total",
    f"{totales['balance_total']:,}",
)

st.markdown(
    "<div class='info-box'><b>Lectura del balance:</b> "
    f"{totales['total_plantados']:,} plantados + "
    f"{totales['total_vivero']:,} disponibles en viveros − "
    f"{totales['total_talados']:,} talados = "
    f"<b>{totales['balance_total']:,} árboles bajo gestión</b>.<br>"
    "<span class='small-note'>El balance en campo excluye el inventario "
    "de viveros. Los dibujos del mapa son referencias visuales y no "
    "modifican ningún cálculo.</span></div>",
    unsafe_allow_html=True,
)


# FASES DE REFORESTACIÓN
conteo_fases = {1: 0, 2: 0, 3: 0}

for proyecto in st.session_state.proyectos:
    fase = calcular_fase_reforestacion(
        proyecto["fecha_proyecto"]
    )
    conteo_fases[fase["numero"]] += 1

fase_cols = st.columns(3)

for columna, numero in zip(fase_cols, [1, 2, 3]):
    datos = FASES_REFORESTACION[numero]

    with columna:
        st.markdown(
            f"<div class='phase-card' "
            f"style='background:{datos['color_hex']};'>"
            f"<b>{datos['nombre']}</b><br>"
            f"{conteo_fases[numero]} proyecto(s)<br>"
            f"<span style='font-size:.8rem;'>"
            f"{datos['temporalidad']}</span></div>",
            unsafe_allow_html=True,
        )

st.caption(
    "Los polígonos del mapa son referencias visuales aproximadas. "
    "El impacto arbóreo se estima únicamente con las especies y "
    "cantidades registradas."
)


# TABLAS PRINCIPALES
tab_proyectos, tab_viveros_tabla, tab_talas_tabla = st.tabs(
    [
        "Proyectos de reforestación",
        "Inventario de viveros",
        "Historial de tala",
    ]
)

with tab_proyectos:
    if not st.session_state.proyectos:
        st.info(
            "Todavía no se han agregado proyectos de reforestación."
        )
    else:
        tabla_proyectos = proyectos_dataframe()
        st.dataframe(
            tabla_proyectos,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Impacto estimado m²": (
                    st.column_config.NumberColumn(format="%.0f")
                ),
            },
        )

with tab_viveros_tabla:
    if not st.session_state.viveros:
        st.info("Todavía no se han registrado viveros.")
    else:
        tabla_viveros = viveros_dataframe()
        st.dataframe(
            tabla_viveros,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Impacto potencial m²": (
                    st.column_config.NumberColumn(format="%.0f")
                ),
            },
        )

with tab_talas_tabla:
    if not st.session_state.talas:
        st.info(
            "Todavía no se han registrado árboles talados."
        )
    else:
        tabla_talas = talas_dataframe()
        st.dataframe(
            tabla_talas,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Impacto removido m²": (
                    st.column_config.NumberColumn(format="%.0f")
                ),
            },
        )


# EXPORTACIONES
st.markdown("#### Exportaciones")
export_cols = st.columns(4)

if st.session_state.proyectos:
    tabla_proyectos = proyectos_dataframe()
else:
    tabla_proyectos = pd.DataFrame()

if st.session_state.viveros:
    tabla_viveros = viveros_dataframe()
else:
    tabla_viveros = pd.DataFrame()

if st.session_state.talas:
    tabla_talas = talas_dataframe()
else:
    tabla_talas = pd.DataFrame()

export_cols[0].download_button(
    "CSV proyectos",
    data=tabla_proyectos.to_csv(index=False).encode("utf-8-sig"),
    file_name="proyectos_reforestacion_spectrum.csv",
    mime="text/csv",
    use_container_width=True,
    disabled=tabla_proyectos.empty,
)

export_cols[1].download_button(
    "CSV viveros",
    data=tabla_viveros.to_csv(index=False).encode("utf-8-sig"),
    file_name="inventario_viveros_spectrum.csv",
    mime="text/csv",
    use_container_width=True,
    disabled=tabla_viveros.empty,
)

export_cols[2].download_button(
    "CSV tala",
    data=tabla_talas.to_csv(index=False).encode("utf-8-sig"),
    file_name="historial_tala_spectrum.csv",
    mime="text/csv",
    use_container_width=True,
    disabled=tabla_talas.empty,
)

respaldo_general = {
    "proyectos_reforestacion": st.session_state.proyectos,
    "inventario_viveros": st.session_state.viveros,
    "registros_tala": st.session_state.talas,
    "totales": totales,
    "fecha_exportacion": datetime.now().isoformat(),
}

export_cols[3].download_button(
    "Respaldo JSON",
    data=json.dumps(
        respaldo_general,
        ensure_ascii=False,
        indent=2,
    ),
    file_name="respaldo_ambiental_spectrum.json",
    mime="application/json",
    use_container_width=True,
)

features_geojson = []

for proyecto in st.session_state.proyectos:
    feature_exportable = proyecto_a_geojson_feature(proyecto)
    if feature_exportable is not None:
        features_geojson.append(feature_exportable)

if features_geojson:
    geojson_export = {
        "type": "FeatureCollection",
        "features": features_geojson,
    }

    st.download_button(
        "Descargar GeoJSON de referencias visuales",
        data=json.dumps(
            geojson_export,
            ensure_ascii=False,
            indent=2,
        ),
        file_name="referencias_visuales_reforestacion_spectrum.geojson",
        mime="application/geo+json",
        use_container_width=True,
    )


# DETALLE DE REGISTROS
st.markdown("#### Detalle de proyectos de reforestación")

if not st.session_state.proyectos:
    st.info("No hay proyectos para mostrar.")
else:
    for proyecto in st.session_state.proyectos:
        fase = calcular_fase_reforestacion(
            proyecto["fecha_proyecto"]
        )

        with st.expander(
            f"Proyecto {proyecto['numero']} · "
            f"{proyecto['nombre']} — "
            f"{proyecto['ubicacion']} "
            f"({formatear_fecha(proyecto['fecha_proyecto'])})"
        ):
            detalle_cols = st.columns([1.3, 1.3, 1])

            with detalle_cols[0]:
                st.write(
                    f"**Área general:** {proyecto['area_general']}"
                )
                st.write(
                    f"**{proyecto['tipo_ubicacion']}:** "
                    f"{proyecto['ubicacion']}"
                )
                st.write(
                    "**Referencia en mapa:** "
                    + (
                        "Dibujo aproximado guardado"
                        if proyecto.get("poligono_geojson")
                        else "Sin dibujo"
                    )
                )
                st.write(
                    f"**Fecha del proyecto:** "
                    f"{formatear_fecha(proyecto['fecha_proyecto'])}"
                )

            with detalle_cols[1]:
                st.write(f"**Fase:** {fase['nombre']}")
                st.write(f"**Antigüedad:** {fase['antiguedad']}")
                st.write(f"**Objetivo:** {fase['objetivo']}")
                st.write(
                    "**Indicadores:** "
                    + ", ".join(fase["indicadores"])
                )

            with detalle_cols[2]:
                st.write(
                    f"**Total árboles:** "
                    f"{proyecto['cantidad_total']:,}"
                )
                st.write(
                    f"**Impacto estimado:** "
                    f"{proyecto['impacto_estimado_m2']:,.0f} m²"
                )
                st.button(
                    "Eliminar proyecto",
                    key=f"eliminar_{proyecto['numero']}",
                    type="secondary",
                    use_container_width=True,
                    on_click=eliminar_proyecto,
                    args=(proyecto["numero"],),
                )

            st.dataframe(
                pd.DataFrame(proyecto["arboles"])[
                    [
                        "tipo",
                        "cantidad",
                        "impacto_por_arbol",
                        "impacto_estimado_m2",
                    ]
                ].rename(
                    columns={
                        "tipo": "Especie",
                        "cantidad": "Cantidad",
                        "impacto_por_arbol": "m² por árbol",
                        "impacto_estimado_m2": (
                            "Impacto estimado m²"
                        ),
                    }
                ),
                hide_index=True,
                use_container_width=True,
            )


st.markdown("#### Detalle de viveros")

if not st.session_state.viveros:
    st.info("No hay viveros para mostrar.")
else:
    for vivero in st.session_state.viveros:
        with st.expander(
            f"Vivero {vivero['numero']} · "
            f"{vivero['nombre']} — "
            f"{vivero['ubicacion']}"
        ):
            cols = st.columns([1.4, 1.2, 1])

            with cols[0]:
                st.write(f"**Ubicación:** {vivero['ubicacion']}")
                st.write(
                    f"**Última actualización:** "
                    f"{formatear_fecha(vivero['fecha_actualizacion'])}"
                )

            with cols[1]:
                st.write(
                    f"**Árboles disponibles:** "
                    f"{vivero['cantidad_total']:,}"
                )
                st.write(
                    f"**Impacto potencial:** "
                    f"{vivero['impacto_potencial_m2']:,.0f} m²"
                )

            with cols[2]:
                st.button(
                    "Eliminar vivero",
                    key=f"eliminar_vivero_{vivero['numero']}",
                    type="secondary",
                    use_container_width=True,
                    on_click=eliminar_vivero,
                    args=(vivero["numero"],),
                )

            st.dataframe(
                pd.DataFrame(vivero["arboles"])[
                    [
                        "tipo",
                        "cantidad",
                        "impacto_por_arbol",
                        "impacto_estimado_m2",
                    ]
                ].rename(
                    columns={
                        "tipo": "Especie",
                        "cantidad": "Cantidad disponible",
                        "impacto_por_arbol": "m² por árbol",
                        "impacto_estimado_m2": (
                            "Impacto potencial m²"
                        ),
                    }
                ),
                hide_index=True,
                use_container_width=True,
            )


st.markdown("#### Detalle de tala")

if not st.session_state.talas:
    st.info("No hay registros de tala para mostrar.")
else:
    for tala in st.session_state.talas:
        with st.expander(
            f"Tala {tala['numero']} · "
            f"{tala['nombre_obra']} — "
            f"{tala['ubicacion']} "
            f"({formatear_fecha(tala['fecha_tala'])})"
        ):
            cols = st.columns([1.3, 1.3, 1])

            with cols[0]:
                st.write(
                    f"**Área general:** {tala['area_general']}"
                )
                st.write(
                    f"**{tala['tipo_ubicacion']}:** "
                    f"{tala['ubicacion']}"
                )
                st.write(
                    f"**Motivo:** "
                    f"{tala['motivo'] or 'No especificado'}"
                )

            with cols[1]:
                st.write(
                    f"**Árboles talados:** "
                    f"{tala['cantidad_total']:,}"
                )
                st.write(
                    f"**Impacto removido:** "
                    f"{tala['impacto_removido_m2']:,.0f} m²"
                )
                st.write(
                    f"**Permiso / referencia:** "
                    f"{tala['permiso_referencia'] or 'No especificado'}"
                )

            with cols[2]:
                st.button(
                    "Eliminar registro",
                    key=f"eliminar_tala_{tala['numero']}",
                    type="secondary",
                    use_container_width=True,
                    on_click=eliminar_tala,
                    args=(tala["numero"],),
                )

            st.dataframe(
                pd.DataFrame(tala["arboles"])[
                    [
                        "tipo",
                        "cantidad",
                        "impacto_por_arbol",
                        "impacto_estimado_m2",
                    ]
                ].rename(
                    columns={
                        "tipo": "Especie",
                        "cantidad": "Cantidad talada",
                        "impacto_por_arbol": "m² por árbol",
                        "impacto_estimado_m2": (
                            "Impacto removido m²"
                        ),
                    }
                ),
                hide_index=True,
                use_container_width=True,
            )


st.markdown(
    """
    <div class='small-note' style='margin-top:1.5rem;'>
        Los dibujos del mapa son referencias visuales aproximadas. No se
        utilizan para calcular superficie física, hectáreas, manzanas ni
        equivalencias territoriales.
    </div>
    """,
    unsafe_allow_html=True,
)