import csv
import json
import os
import re
import shutil
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
import webbrowser

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from render_bundle_html import build_html

FHIR_SERVER_BASE_URL = "https://fhirserver.hl7chile.cl/fhir"
CONV_DIR = Path(__file__).resolve().parent / "conv"
sesiones_csv = []


def extraer_run_desde_ruta(ruta):
    nombre = os.path.basename(ruta)
    partes = os.path.splitext(nombre)[0].split("_")
    if len(partes) >= 4 and partes[3].strip():
        return partes[3].strip().upper()

    match = re.search(r"(\d{7,8}-[\dkK])", nombre)
    return match.group(1).upper() if match else ""


def crear_human_name(nombre_completo):
    partes = nombre_completo.split()
    if not partes:
        raise ValueError("A2 no contiene nombre del paciente.")

    if len(partes) >= 3:
        name = {
            "given": partes[:-2],
            "family": partes[-2],
            "extension": [
                {
                    "url": "http://hl7.org/fhir/StructureDefinition/humanname-mothers-family",
                    "valueString": partes[-1],
                }
            ],
        }
    elif len(partes) == 2:
        name = {
            "given": [partes[0]],
            "family": partes[1],
        }
    else:
        name = {"given": [partes[0]]}

    return name


def nombre_paciente_desde_df(df):
    return valor_celda(df, 1, 0, "A2")


def periodo_mediciones_desde_df(df):
    fechas = []
    row = 4

    while row < df.shape[0]:
        if pd.isna(df.iloc[row, 0]) or str(df.iloc[row, 0]).strip() == "":
            break

        fecha = valor_celda(df, row, 2, f"C{row + 1}")
        if fecha:
            fechas.append(fecha)
        row += 1

    if not fechas:
        return "", ""

    return fechas[0], fechas[-1]


def normalizar_fecha(valor):
    if pd.isna(valor):
        raise ValueError("fecha vacia")

    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d")

    texto = str(valor).strip()
    if not texto:
        raise ValueError("fecha vacia")

    formatos = ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d")
    for formato in formatos:
        try:
            return datetime.strptime(texto, formato).strftime("%Y-%m-%d")
        except ValueError:
            pass

    fecha = pd.to_datetime(texto, dayfirst=True, errors="coerce")
    if pd.isna(fecha):
        raise ValueError(f"fecha invalida: {texto}")

    return fecha.strftime("%Y-%m-%d")


def normalizar_fecha_hora(valor):
    if pd.isna(valor):
        raise ValueError("fecha/hora vacia")

    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%dT%H:%M:%S")

    texto = str(valor).strip()
    if not texto:
        raise ValueError("fecha/hora vacia")

    formatos = (
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    )
    for formato in formatos:
        try:
            return datetime.strptime(texto, formato).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass

    fecha = pd.to_datetime(texto, dayfirst=True, errors="coerce")
    if pd.isna(fecha):
        raise ValueError(f"fecha/hora invalida: {texto}")

    return fecha.to_pydatetime().strftime("%Y-%m-%dT%H:%M:%S")


def valor_celda(df, fila, columna, nombre):
    try:
        valor = df.iloc[fila, columna]
    except IndexError as exc:
        raise ValueError(f"Falta la celda {nombre}.") from exc

    if pd.isna(valor):
        return ""

    return str(valor).strip()


def convertir_csv_a_excel(ruta_csv, ruta_excel):
    filas = []

    with open(ruta_csv, "r", encoding="utf-8-sig", newline="") as archivo:
        lector = csv.reader(archivo)
        for fila in lector:
            if any(str(celda).strip() for celda in fila):
                filas.append(fila)

    if not filas:
        raise ValueError("El CSV no contiene filas con datos.")

    max_columnas = max(len(fila) for fila in filas)
    for fila in filas:
        fila.extend([""] * (max_columnas - len(fila)))

    carpeta = os.path.dirname(os.path.abspath(ruta_excel))
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)

    df = pd.DataFrame(filas)
    df.to_excel(ruta_excel, index=False, header=False)


def crear_patient(df, run=""):
    nombre_completo = nombre_paciente_desde_df(df)
    birth_raw = valor_celda(df, 1, 1, "B2")
    identifier_value = run.strip().upper()
    if not identifier_value:
        raise ValueError("No se encontro identificacion del paciente en el nombre del archivo.")

    patient = {
        "resourceType": "Patient",
        "id": "p1",
        "identifier": [
            {
                "system": "http://glucosa.cl/patient-identifier",
                "type": {"text": "Identificacion"},
                "value": identifier_value,
            }
        ],
        "name": [crear_human_name(nombre_completo)],
        "birthDate": normalizar_fecha(birth_raw),
    }

    return patient


def crear_device(df):
    device_name = valor_celda(df, 3, 0, "A4")
    serial_number = valor_celda(df, 3, 1, "B4")

    if not device_name:
        raise ValueError("A4 no contiene nombre del dispositivo.")
    if not serial_number:
        raise ValueError("B4 no contiene numero de serie del dispositivo.")

    return {
        "resourceType": "Device",
        "id": "d1",
        "deviceName": [
            {
                "name": device_name,
                "type": "user-friendly-name",
            }
        ],
        "serialNumber": serial_number,
    }


def crear_observations(df):
    observations = []
    row = 4

    display_0 = valor_celda(df, 2, 4, "E3")
    display_1 = valor_celda(df, 2, 5, "F3")

    while row < df.shape[0]:
        if pd.isna(df.iloc[row, 0]) or str(df.iloc[row, 0]).strip() == "":
            break

        effective = normalizar_fecha_hora(valor_celda(df, row, 2, f"C{row + 1}"))
        selector = valor_celda(df, row, 3, f"D{row + 1}")

        if selector not in ("0", "1"):
            row += 1
            continue

        value_0 = valor_celda(df, row, 4, f"E{row + 1}")
        value_1 = valor_celda(df, row, 5, f"F{row + 1}")

        if selector == "0":
            category_code = "0"
            category_display = display_0
            value = value_0
        else:
            category_code = "1"
            category_display = display_1
            value = value_1

        try:
            value_quantity = float(value)
        except ValueError as exc:
            raise ValueError(f"Valor numerico invalido en fila {row + 1}: {value}") from exc

        observations.append(
            {
                "resourceType": "Observation",
                "id": f"o{len(observations) + 1}",
                "status": "final",
                "code": {"text": "Resultado desde Excel"},
                "effectiveDateTime": effective,
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://sistemaMedicion.cl/CS",
                                "code": category_code,
                                "display": category_display,
                            }
                        ]
                    }
                ],
                "valueQuantity": {
                    "value": value_quantity,
                    "unit": "mg/dl",
                    "code": "mg/dl",
                    "system": "http://unitsofmeasure.org",
                },
            }
        )
        row += 1

    if not observations:
        raise ValueError("No se encontraron observaciones validas desde la fila 5.")

    return observations


def fecha_hora_observation(observation):
    return datetime.strptime(observation["effectiveDateTime"], "%Y-%m-%dT%H:%M:%S")


def calcular_porcentaje_tiempo(observations, in_range):
    ordered = sorted(observations, key=fecha_hora_observation)
    if len(ordered) < 2:
        effective = fecha_hora_observation(ordered[0]) if ordered else datetime.now()
        return 0.0, effective.date().isoformat(), effective.date().isoformat()

    total_minutes = 0.0
    matching_minutes = 0.0

    for current, next_observation in zip(ordered, ordered[1:]):
        current_time = fecha_hora_observation(current)
        next_time = fecha_hora_observation(next_observation)
        interval_minutes = (next_time - current_time).total_seconds() / 60
        if interval_minutes <= 0:
            continue

        total_minutes += interval_minutes
        value = float((current.get("valueQuantity") or {}).get("value", 0))
        if in_range(value):
            matching_minutes += interval_minutes

    percentage = (matching_minutes / total_minutes * 100) if total_minutes else 0.0
    start = fecha_hora_observation(ordered[0]).date().isoformat()
    end = fecha_hora_observation(ordered[-1]).date().isoformat()
    return round(percentage, 1), start, end


def calcular_tir(observations):
    return calcular_porcentaje_tiempo(observations, lambda value: 70 <= value <= 180)


def calcular_tar_moderada(observations):
    return calcular_porcentaje_tiempo(observations, lambda value: 180 < value <= 250)


def calcular_tar_muy_alta(observations):
    return calcular_porcentaje_tiempo(observations, lambda value: value > 250)


def calcular_tbr_bajo(observations):
    return calcular_porcentaje_tiempo(observations, lambda value: 54 <= value < 70)


def calcular_tbr_muy_bajo(observations):
    return calcular_porcentaje_tiempo(observations, lambda value: value < 54)


def crear_ranges_component(code, display, text, value):
    return {
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": code,
                    "display": display,
                }
            ],
            "text": text,
        },
        "valueQuantity": {
            "value": value,
            "unit": "%",
            "system": "http://unitsofmeasure.org",
            "code": "%",
        },
    }


def crear_observation_panel_rangos(observations):
    tir, start, end = calcular_tir(observations)
    tar_muy_alta, _, _ = calcular_tar_muy_alta(observations)
    tar_alta, _, _ = calcular_tar_moderada(observations)
    tbr_bajo, _, _ = calcular_tbr_bajo(observations)
    tbr_muy_bajo, _, _ = calcular_tbr_muy_bajo(observations)

    return {
        "resourceType": "Observation",
        "id": "ranges-panel",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "106793-3",
                    "display": "Continuous glucose monitoring time in ranges panel",
                }
            ]
        },
        "subject": {
            "reference": "Patient/p1",
        },
        "effectivePeriod": {
            "start": start,
            "end": end,
        },
        "method": {
            "text": "Calculated from continuous glucose monitoring device",
        },
        "component": [
            crear_ranges_component(
                "104639-0",
                "Glucose measurements above target range very high out of Total glucose measurements during reporting period",
                "TAR muy alto / hiperglucemia clínicamente significativa" if tar_muy_alta > 5 else "",
                tar_muy_alta,
            ),
            crear_ranges_component(
                "104640-8",
                "Glucose measurements above target range high out of Total glucose measurements during reporting period",
                "TAR alto / hiperglucemia moderada" if tar_alta > 25 else "",
                tar_alta,
            ),
            crear_ranges_component(
                "97510-2",
                "Glucose measurements in range out of Total glucose measurements during reporting period",
                "TIR" if tir >= 70 else "",
                tir,
            ),
            crear_ranges_component(
                "104641-6",
                "Glucose measurements below target range low out of Total glucose measurements during reporting period",
                "TBR bajo" if tbr_bajo > 4 else "",
                tbr_bajo,
            ),
            crear_ranges_component(
                "104642-4",
                "Glucose measurements below target range very low out of Total glucose measurements during reporting period",
                "TBR muy bajo" if tbr_muy_bajo > 1 else "",
                tbr_muy_bajo,
            ),
        ],
    }


def crear_composition(observations, ranges_panel=None):
    fecha_reporte = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    sections = [
        {
            "title": "Observaciones de Glucosa",
            "entry": [{"reference": f"Observation/{obs['id']}"} for obs in observations],
        }
    ]

    if ranges_panel:
        sections.append(
            {
                "title": "Panel de Tiempo en Rangos",
                "entry": [{"reference": f"Observation/{ranges_panel['id']}"}],
            }
        )

    return {
        "resourceType": "Composition",
        "id": "c1",
        "identifier": [
            {
                "system": "http://glucosa.cl/composition",
                "value": f"comp-{int(datetime.now().timestamp())}",
            }
        ],
        "status": "final",
        "type": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "11502-2",
                    "display": "Laboratory report",
                }
            ],
            "text": "Laboratory report",
        },
        "title": "Informe de Perfil Ambulatorio de Glucosa",
        "date": fecha_reporte,
        "author": [{"reference": "Device/d1"}],
        "subject": {"reference": "Patient/p1"},
        "section": sections,
    }


def crear_bundle(patient, device, observations, composition, ranges_panel=None):
    entries = [
        {
            "fullUrl": f"urn:uuid:{uuid.uuid4()}",
            "resource": composition,
        },
        {
            "fullUrl": f"urn:uuid:{uuid.uuid4()}",
            "resource": patient,
        },
        {
            "fullUrl": f"urn:uuid:{uuid.uuid4()}",
            "resource": device,
        },
    ]

    for obs in observations:
        entries.append(
            {
                "fullUrl": f"urn:uuid:{uuid.uuid4()}",
                "resource": obs,
            }
        )

    if ranges_panel:
        entries.append(
            {
                "fullUrl": f"urn:uuid:{uuid.uuid4()}",
                "resource": ranges_panel,
            }
        )

    return {
        "resourceType": "Bundle",
        "type": "document",
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "entry": entries,
    }


def guardar_json(ruta, recurso):
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(recurso, archivo, ensure_ascii=False, indent=4)


def convertir_excel_a_fhir(ruta_excel):
    return convertir_excel_a_fhir_en_carpeta(ruta_excel)


def convertir_excel_a_fhir_en_carpeta(ruta_excel, carpeta_salida=None):
    salida_base = os.path.splitext(ruta_excel)[0]
    carpeta_salida = carpeta_salida or salida_base
    nombre_excel = os.path.basename(salida_base)

    os.makedirs(carpeta_salida, exist_ok=True)

    rutas = {
        "patient": os.path.join(carpeta_salida, f"{nombre_excel}_patient.json"),
        "device": os.path.join(carpeta_salida, f"{nombre_excel}_device.json"),
        "observations": os.path.join(carpeta_salida, f"{nombre_excel}_observations.json"),
        "ranges_panel": os.path.join(carpeta_salida, f"{nombre_excel}_ranges_panel.json"),
        "composition": os.path.join(carpeta_salida, f"{nombre_excel}_composition.json"),
        "bundle": os.path.join(carpeta_salida, f"{nombre_excel}_bundle.json"),
    }

    df = pd.read_excel(ruta_excel, header=None)
    run = extraer_run_desde_ruta(ruta_excel)

    patient = crear_patient(df, run)
    device = crear_device(df)
    observations = crear_observations(df)
    ranges_panel = crear_observation_panel_rangos(observations)
    composition = crear_composition(observations, ranges_panel)
    bundle = crear_bundle(patient, device, observations, composition, ranges_panel)

    guardar_json(rutas["patient"], patient)
    guardar_json(rutas["device"], device)
    guardar_json(rutas["observations"], observations)
    guardar_json(rutas["ranges_panel"], ranges_panel)
    guardar_json(rutas["composition"], composition)
    guardar_json(rutas["bundle"], bundle)

    return carpeta_salida, rutas


def crear_carpeta_conv():
    CONV_DIR.mkdir(parents=True, exist_ok=True)
    return str(CONV_DIR)


def limpiar_contenido_carpeta(carpeta):
    carpeta = Path(carpeta).resolve()
    carpeta_conv = CONV_DIR.resolve()
    if carpeta != carpeta_conv:
        raise ValueError(f"No se limpiara una carpeta distinta a conv: {carpeta}")

    carpeta.mkdir(parents=True, exist_ok=True)
    for item in carpeta.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def generar_informe_desde_bundle(ruta_bundle):
    bundle_path = Path(ruta_bundle)
    output_path = bundle_path.with_suffix(".html")

    with bundle_path.open("r", encoding="utf-8-sig") as archivo:
        bundle = json.load(archivo)

    if bundle.get("resourceType") != "Bundle":
        raise ValueError("El archivo seleccionado no parece ser un recurso FHIR Bundle.")

    output_path.write_text(build_html(bundle, bundle_path.name), encoding="utf-8")
    return output_path


def generar_informe_desde_bundle_servidor(bundle, output_path, source_name):
    if bundle.get("resourceType") != "Bundle":
        raise ValueError("La respuesta del servidor no parece ser un recurso FHIR Bundle.")

    output_path = Path(output_path)
    output_path.write_text(build_html(bundle, source_name), encoding="utf-8")
    return output_path


def extraer_url_recurso_servidor(location):
    if not location:
        return ""

    recurso_url = location.split("/_history/", 1)[0]
    if recurso_url.startswith("http://") or recurso_url.startswith("https://"):
        return recurso_url

    recurso_url = recurso_url.lstrip("/")
    base_url = FHIR_SERVER_BASE_URL.rstrip("/")
    if recurso_url.startswith("Bundle/"):
        return f"{base_url}/{recurso_url}"

    return f"{base_url}/Bundle/{recurso_url}"


def extraer_url_bundle_desde_respuesta(location, body):
    bundle_url = extraer_url_recurso_servidor(location)
    if bundle_url:
        return bundle_url

    if not body:
        return ""

    try:
        recurso = json.loads(body)
    except json.JSONDecodeError:
        return ""

    if recurso.get("resourceType") == "Bundle" and recurso.get("id"):
        return f"{FHIR_SERVER_BASE_URL.rstrip('/')}/Bundle/{recurso['id']}"

    return ""


def enviar_bundle_a_servidor(ruta_bundle):
    bundle_path = Path(ruta_bundle)

    with bundle_path.open("rb") as archivo:
        payload = archivo.read()

    url = FHIR_SERVER_BASE_URL.rstrip("/") + "/Bundle"
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, response.headers.get("Location", ""), body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Servidor FHIR respondio {exc.code}:\n{body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar al servidor FHIR:\n{exc.reason}") from exc


def obtener_bundle_desde_servidor(bundle_url):
    if not bundle_url:
        raise ValueError("No hay URL del Bundle en el servidor FHIR.")

    request = urllib.request.Request(
        bundle_url,
        method="GET",
        headers={"Accept": "application/fhir+json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Servidor FHIR respondio {exc.code}:\n{body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar al servidor FHIR:\n{exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("El servidor FHIR no respondio con JSON valido.") from exc


def seleccionar_archivo():
    ruta = filedialog.askopenfilename(
        title="Seleccionar archivo CSV",
        filetypes=[("Archivos CSV", "*.csv"), ("Todos los archivos", "*.*")],
    )
    entrada_var.set(ruta)


def leer_csv():
    ruta_csv = filedialog.askopenfilename(
        title="Seleccionar archivo CSV",
        filetypes=[("Archivos CSV", "*.csv"), ("Todos los archivos", "*.*")],
    )

    if not ruta_csv:
        return

    try:
        carpeta_salida = crear_carpeta_conv()
        limpiar_contenido_carpeta(carpeta_salida)
        nombre_excel = os.path.splitext(os.path.basename(ruta_csv))[0] + ".xlsx"
        salida_excel = os.path.join(carpeta_salida, nombre_excel)
        convertir_csv_a_excel(ruta_csv, salida_excel)
        df = pd.read_excel(salida_excel, header=None)
        primera_medicion, ultima_medicion = periodo_mediciones_desde_df(df)
        _, rutas = convertir_excel_a_fhir_en_carpeta(salida_excel, carpeta_salida)
        status, location, body = enviar_bundle_a_servidor(rutas["bundle"])
        bundle_url = extraer_url_bundle_desde_respuesta(location, body)
        if not bundle_url:
            raise RuntimeError("El servidor FHIR recibio el Bundle, pero no entrego una URL o id para consultarlo por GET.")
        limpiar_contenido_carpeta(carpeta_salida)

        sesion = {
            "csv": ruta_csv,
            "excel": salida_excel,
            "carpeta_salida": carpeta_salida,
            "nombre": nombre_paciente_desde_df(df),
            "run": extraer_run_desde_ruta(ruta_csv),
            "primera_medicion": primera_medicion,
            "ultima_medicion": ultima_medicion,
            "bundle": rutas["bundle"],
            "bundle_server_url": bundle_url,
            "server_status": f"Enviado ({status})",
            "html": "",
        }
        sesiones_csv.append(sesion)
        agregar_paciente_a_tabla(sesion)
        notebook.select(paciente_tab)
        detalle = f"CSV leido y Bundle enviado al servidor FHIR.\n\nEstado HTTP: {status}\nCarpeta conv limpiada."
        if bundle_url:
            detalle += f"\nGET: {bundle_url}"
        messagebox.showinfo("Servidor FHIR", detalle)
    except Exception as exc:
        messagebox.showerror("Error", f"Ocurrio un problema al leer el CSV:\n{exc}")


def procesar():
    entrada = entrada_var.get().strip()
    salida = salida_var.get().strip()

    if not entrada:
        messagebox.showerror("Error", "Debe seleccionar un archivo CSV de entrada.")
        return
    if not salida:
        messagebox.showerror("Error", "Debe ingresar un nombre para el archivo de salida.")
        return

    if not salida.lower().endswith(".xlsx"):
        salida += ".xlsx"

    try:
        convertir_csv_a_excel(entrada, salida)
        messagebox.showinfo("Exito", f"Archivo Excel generado:\n{salida}")
    except Exception as exc:
        messagebox.showerror("Error", f"Ocurrio un problema:\n{exc}")


def convertir_a_fhir():
    ruta_excel = filedialog.askopenfilename(
        title="Seleccionar archivo Excel generado",
        filetypes=[("Archivos Excel", "*.xlsx"), ("Todos los archivos", "*.*")],
    )

    if not ruta_excel:
        return

    try:
        carpeta_salida, _ = convertir_excel_a_fhir(ruta_excel)
        messagebox.showinfo(
            "FHIR generado",
            f"Se generaron los recursos en:\n\n{carpeta_salida}",
        )
    except Exception as exc:
        messagebox.showerror("Error", f"Ocurrio un problema al convertir:\n{exc}")


def generar_informe_para_sesion(sesion):
    try:
        bundle_url = sesion.get("bundle_server_url", "")
        if not bundle_url:
            raise ValueError("Este paciente no tiene un Bundle registrado en el servidor FHIR.")

        bundle = obtener_bundle_desde_servidor(bundle_url)
        nombre_base = os.path.splitext(os.path.basename(sesion["csv"]))[0]
        carpeta_salida = Path(crear_carpeta_conv())
        output_path = carpeta_salida / f"{nombre_base}_bundle.html"
        output_path = generar_informe_desde_bundle_servidor(bundle, output_path, bundle_url)
        sesion["html"] = str(output_path)

        abrir = messagebox.askyesno(
            "Informe generado",
            f"Se genero el informe HTML desde el servidor FHIR:\n\n{output_path}\n\nDesea abrirlo ahora?",
        )
        if abrir:
            webbrowser.open(output_path.resolve().as_uri())
    except Exception as exc:
        messagebox.showerror("Error", f"Ocurrio un problema al generar el informe:\n{exc}")


def generar_informe_paciente_seleccionado():
    seleccion = pacientes_tabla.selection()
    if not seleccion:
        messagebox.showerror("Error", "Debe seleccionar un paciente de la tabla.")
        return

    indice = int(seleccion[0])
    generar_informe_para_sesion(sesiones_csv[indice])


def renderizar_bundle():
    ruta_bundle = filedialog.askopenfilename(
        title="Seleccionar bundle FHIR",
        filetypes=[("Bundle JSON", "*_bundle.json"), ("Archivos JSON", "*.json"), ("Todos los archivos", "*.*")],
    )

    if not ruta_bundle:
        return

    try:
        output_path = generar_informe_desde_bundle(ruta_bundle)
        abrir = messagebox.askyesno(
            "Informe generado",
            f"Se genero el informe HTML:\n\n{output_path}\n\nDesea abrirlo ahora?",
        )
        if abrir:
            webbrowser.open(output_path.resolve().as_uri())
    except Exception as exc:
        messagebox.showerror("Error", f"Ocurrio un problema al renderizar el bundle:\n{exc}")


def crear_tab_paciente():
    global paciente_tab, pacientes_tabla

    paciente_tab = ttk.Frame(notebook)
    notebook.add(paciente_tab, text="Paciente")

    contenedor = ttk.Frame(paciente_tab, padding=12)
    contenedor.pack(fill="both", expand=True)

    pacientes_tabla = ttk.Treeview(
        contenedor,
        columns=("paciente", "run", "primera_medicion", "ultima_medicion", "servidor"),
        show="headings",
        height=10,
    )
    pacientes_tabla.heading("paciente", text="Paciente")
    pacientes_tabla.heading("run", text="RUN")
    pacientes_tabla.heading("primera_medicion", text="Primera medicion")
    pacientes_tabla.heading("ultima_medicion", text="Ultima medicion")
    pacientes_tabla.heading("servidor", text="Servidor FHIR")
    pacientes_tabla.column("paciente", width=240, anchor="w")
    pacientes_tabla.column("run", width=130, anchor="center")
    pacientes_tabla.column("primera_medicion", width=180, anchor="center")
    pacientes_tabla.column("ultima_medicion", width=180, anchor="center")
    pacientes_tabla.column("servidor", width=130, anchor="center")
    pacientes_tabla.pack(fill="both", expand=True, pady=(0, 14))

    acciones = ttk.Frame(contenedor)
    acciones.pack(anchor="w")

    tk.Button(
        acciones,
        text="Generar informe",
        command=generar_informe_paciente_seleccionado,
        bg="#6D28D9",
        fg="white",
        width=18,
    ).pack(side="left", padx=(0, 10))


def agregar_paciente_a_tabla(sesion):
    indice = len(sesiones_csv) - 1
    pacientes_tabla.insert(
        "",
        "end",
        iid=str(indice),
        values=(
            sesion["nombre"],
            sesion["run"] or "No encontrado",
            sesion["primera_medicion"] or "Sin datos",
            sesion["ultima_medicion"] or "Sin datos",
            sesion.get("server_status", "Pendiente"),
        ),
    )


def crear_interfaz():
    global entrada_var, salida_var, notebook

    root = tk.Tk()
    root.title("Gestor CSV + FHIR")
    root.geometry("860x420")

    entrada_var = tk.StringVar()
    salida_var = tk.StringVar()

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    inicio = ttk.Frame(notebook, padding=18)
    notebook.add(inicio, text="Inicio")

    tk.Label(inicio, text="Lectura de CSV").pack(anchor="w", pady=(0, 10))

    tk.Button(
        inicio,
        text="Leer CSV",
        command=leer_csv,
        bg="#4CAF50",
        fg="white",
        width=22,
    ).pack(anchor="w")

    crear_tab_paciente()

    return root


if __name__ == "__main__":
    crear_interfaz().mainloop()
