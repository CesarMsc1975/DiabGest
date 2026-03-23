
import csv
import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox
import json
from datetime import datetime
import os

def seleccionar_archivo():
    ruta = filedialog.askopenfilename(
        title="Seleccionar archivo CSV",
        filetypes=[("Archivos CSV", "*.csv"), ("Todos los archivos", "*.*")]
    )
    entrada_var.set(ruta)

def procesar():
    entrada = entrada_var.get().strip()
    salida = salida_var.get().strip()

    if not entrada:
        messagebox.showerror("Error", "Debe seleccionar un archivo CSV de entrada.")
        return
    if not salida:
        messagebox.showerror("Error", "Debe ingresar un nombre para el archivo de salida.")
        return

    # Asegurar extensión .xlsx
    if not salida.lower().endswith(".xlsx"):
        salida += ".xlsx"

    try:
        filas = []
        with open(entrada, "r", encoding="utf-8") as f:
            lector = csv.reader(f)
            for fila in lector:
                if any(c.strip() for c in fila):
                    filas.append(fila)

        max_cols = max(len(fila) for fila in filas)

        for fila in filas:
            while len(fila) < max_cols:
                fila.append("")

        df = pd.DataFrame(filas)
        df.to_excel(salida, index=False, header=False)

        messagebox.showinfo("Éxito", f"Archivo Excel generado:\n{salida}")

    except Exception as e:
        messagebox.showerror("Error", f"Ocurrió un problema:\n{e}")


# ============================================================
#                   FUNCIÓN: CONVERTIR A FHIR
# ============================================================


def convertir_a_fhir():
    ruta_excel = filedialog.askopenfilename(
        title="Seleccionar archivo Excel generado",
        filetypes=[("Archivos Excel", "*.xlsx"), ("Todos los archivos", "*.*")]
    )

    if not ruta_excel:
        return

    try:
        # Base sin extensión
        salida_base = os.path.splitext(ruta_excel)[0]

        # Crear carpeta con el nombre del Excel
        carpeta_salida = salida_base
        if not os.path.exists(carpeta_salida):
            os.makedirs(carpeta_salida)

        nombre_excel = os.path.basename(salida_base)

        # Rutas de salida
        ruta_patient      = os.path.join(carpeta_salida, nombre_excel + "_patient.json")
        ruta_device       = os.path.join(carpeta_salida, nombre_excel + "_device.json")
        ruta_observations = os.path.join(carpeta_salida, nombre_excel + "_observations.json")
        ruta_composition  = os.path.join(carpeta_salida, nombre_excel + "_composition.json")
        ruta_bundle       = os.path.join(carpeta_salida, nombre_excel + "_bundle.json")

        df = pd.read_excel(ruta_excel, header=None)

        # =====================================================
        #                   PATIENT
        # =====================================================
        nombre_completo = str(df.iloc[1, 0]).strip()  # A2
        birth_raw       = str(df.iloc[1, 1]).strip()  # B2

        partes = nombre_completo.split()
        if len(partes) == 0:
            messagebox.showerror("Error", "A2 no contiene nombre del paciente.")
            return

        given = partes[0]
        family = partes[1] if len(partes) >= 2 else None
        mothers_family = partes[2] if len(partes) >= 3 else None

        try:
            birthdate = datetime.strptime(birth_raw, "%d-%m-%Y").strftime("%Y-%m-%d")
        except:
            messagebox.showerror("Error", f"Fecha inválida en B2: {birth_raw}")
            return

        patient = {
            "resourceType": "Patient",
            "id": "p1",
            "name": [
                { "given": [given] }
            ],
            "birthDate": birthdate
        }

        if family:
            patient["name"][0]["family"] = family

        if mothers_family:
            patient["name"][0]["extension"] = [
                {
                    "url": "http://hl7.org/fhir/StructureDefinition/humanname-mothers-family",
                    "valueString": mothers_family
                }
            ]

        with open(ruta_patient, "w", encoding="utf-8") as f:
            json.dump(patient, f, ensure_ascii=False, indent=4)

        # =====================================================
        #                   DEVICE
        # =====================================================
        device_name   = str(df.iloc[3, 0]).strip()  # A4
        serial_number = str(df.iloc[3, 1]).strip()  # B4

        device = {
            "resourceType": "Device",
            "id": "d1",
            "deviceName": [
                {
                    "name": device_name,
                    "type": "user-friendly-name"
                }
            ],
            "serialNumber": serial_number
        }

        with open(ruta_device, "w", encoding="utf-8") as f:
            json.dump(device, f, ensure_ascii=False, indent=4)

        # =====================================================
        #             MULTIPLE OBSERVATIONS (FILAS 5+)
        # =====================================================
        observations = []
        row = 4  # Fila 5 visible

        display_0 = str(df.iloc[2, 4]).strip()  # E3
        display_1 = str(df.iloc[2, 5]).strip()  # F3

        while True:

            if row >= df.shape[0]:
                break

            if pd.isna(df.iloc[row, 0]) or str(df.iloc[row, 0]).strip() == "":
                break

            effective = str(df.iloc[row, 2]).strip()  # C(row)
            selector  = str(df.iloc[row, 3]).strip()  # D(row)

            if selector not in ["0", "1"]:
                row += 1
                continue

            value_0 = str(df.iloc[row, 4]).strip()
            value_1 = str(df.iloc[row, 5]).strip()

            if selector == "0":
                category_code = "0"
                category_display = display_0
                value = value_0
            else:
                category_code = "1"
                category_display = display_1
                value = value_1

            obs = {
                "resourceType": "Observation",
                "id": f"o{len(observations)+1}",
                "status": "final",
                "code": { "text": "Resultado desde Excel" },
                "effectiveDateTime": effective,
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://sistemaMedicion.cl/CS",
                                "code": category_code,
                                "display": category_display
                            }
                        ]
                    }
                ],
                "valueQuantity": {
                    "value": float(value),
                    "unit": "mg/dl",
                    "code": "mg/dl",
                    "system": "http://unitsofmeasure.org"
                }
            }

            observations.append(obs)
            row += 1

        with open(ruta_observations, "w", encoding="utf-8") as f:
            json.dump(observations, f, ensure_ascii=False, indent=4)

        # =====================================================
        #                  COMPOSITION
        # =====================================================
        fecha_reporte = datetime.now().isoformat()

        composition = {
            "resourceType": "Composition",
            "id": "c1",
            "identifier": [{
                "system": "http://glucosa.cl/composition",
                "value": f"comp-{int(datetime.now().timestamp())}"
            }],
            "status": "final",
            "type": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "11502-2",
                    "display": "Laboratory report"
                }],
                "text": "Laboratory report"
            },
            "title": "Informe de Perfil Ambulatorio de Glucosa",
            "date": fecha_reporte,
            "author": [{"reference": "Device/d1"}],
            "subject": {"reference": "Patient/p1"},
            "section": [
                {
                    "title": "Observaciones de Glucosa",
                    "entry": [
                        {"reference": f"Observation/{obs['id']}"} 
                        for obs in observations
                    ]
                }
            ]
        }

        with open(ruta_composition, "w", encoding="utf-8") as f:
            json.dump(composition, f, ensure_ascii=False, indent=4)

        # =====================================================
        #                  BUNDLE DOCUMENT
        # =====================================================
        import uuid

        # FullURLs
        full_composition = f"urn:uuid:{uuid.uuid4()}"
        full_patient     = f"urn:uuid:{uuid.uuid4()}"
        full_device      = f"urn:uuid:{uuid.uuid4()}"

        observation_entries = []
        for obs in observations:
            full_obs = f"urn:uuid:{uuid.uuid4()}"
            observation_entries.append({
                "fullUrl": full_obs,
                "resource": obs
            })

        bundle_entries = []

        bundle_entries.append({
            "fullUrl": full_composition,
            "resource": composition
        })

        bundle_entries.append({
            "fullUrl": full_patient,
            "resource": patient
        })

        bundle_entries.append({
            "fullUrl": full_device,
            "resource": device
        })

        bundle_entries.extend(observation_entries)

        bundle = {
            "resourceType": "Bundle",
            "type": "document",
            "timestamp": datetime.now().isoformat(),
            "entry": bundle_entries
        }

        with open(ruta_bundle, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False, indent=4)

        # =====================================================
        #        FIN - MOSTRAR MENSAJE
        # =====================================================
        messagebox.showinfo(
            "FHIR generado",
            f"Se generaron los recursos en:\n\n{carpeta_salida}"
        )

    except Exception as e:
        messagebox.showerror("Error", f"Ocurrió un problema al convertir:\n{e}")

    ruta_excel = filedialog.askopenfilename(
        title="Seleccionar archivo Excel generado",
        filetypes=[("Archivos Excel", "*.xlsx"), ("Todos los archivos", "*.*")]
    )

    if not ruta_excel:
        return

    try:
        salida_base = os.path.splitext(ruta_excel)[0]
        df = pd.read_excel(ruta_excel, header=None)
        
        
        # Crear carpeta con el nombre del Excel
        carpeta_salida = salida_base  # ejemplo: C:/Glucosa/salida.xlsx -> C:/Glucosa/salida
        if not os.path.exists(carpeta_salida):
            os.makedirs(carpeta_salida)
        
        # Actualizamos los paths para guardar los archivos dentro de esa carpeta
        ruta_patient       = os.path.join(carpeta_salida, os.path.basename(salida_base) + "_patient.json")
        ruta_device        = os.path.join(carpeta_salida, os.path.basename(salida_base) + "_device.json")
        ruta_observations  = os.path.join(carpeta_salida, os.path.basename(salida_base) + "_observations.json")
        ruta_composition   = os.path.join(carpeta_salida, os.path.basename(salida_base) + "_composition.json")
        ruta_bundle        = os.path.join(carpeta_salida, os.path.basename(salida_base) + "_bundle.json")


        # =====================================================
        #                   PATIENT
        # =====================================================
        nombre_completo = str(df.iloc[1, 0]).strip()  # A2
        birth_raw       = str(df.iloc[1, 1]).strip()  # B2

        partes = nombre_completo.split()
        if len(partes) == 0:
            messagebox.showerror("Error", "A2 no contiene nombre del paciente.")
            return

        given = partes[0]
        family = partes[1] if len(partes) >= 2 else None
        mothers_family = partes[2] if len(partes) >= 3 else None

        try:
            birthdate = datetime.strptime(birth_raw, "%d-%m-%Y").strftime("%Y-%m-%d")
        except:
            messagebox.showerror("Error", f"Fecha inválida en B2: {birth_raw}")
            return

        patient = {
            "resourceType": "Patient",
            "name": [
                {
                    "given": [given]
                }
            ],
            "birthDate": birthdate
        }

        if family:
            patient["name"][0]["family"] = family

        if mothers_family:
            patient["name"][0]["extension"] = [
                {
                    "url": "http://hl7.org/fhir/StructureDefinition/humanname-mothers-family",
                    "valueString": mothers_family
                }
            ]

        ruta_patient = salida_base + "_patient.json"
        with open(ruta_patient, "w", encoding="utf-8") as f:
            json.dump(patient, f, ensure_ascii=False, indent=4)

        # =====================================================
        #                   DEVICE
        # =====================================================
        device_name = str(df.iloc[3, 0]).strip()  # A4
        serial_number = str(df.iloc[3, 1]).strip()  # B4

        device = {
            "resourceType": "Device",
            "deviceName": [
                {
                    "name": device_name,
                    "type": "user-friendly-name"
                }
            ],
            "serialNumber": serial_number
        }

        ruta_device = salida_base + "_device.json"
        with open(ruta_device, "w", encoding="utf-8") as f:
            json.dump(device, f, ensure_ascii=False, indent=4)

        # =====================================================
        #             MULTIPLE OBSERVATIONS (FILAS 5+)
        # =====================================================
        observations = []

        row = 4  # fila 5 en Excel

        display_0 = str(df.iloc[2, 4]).strip()  # E3
        display_1 = str(df.iloc[2, 5]).strip()  # F3

        while True:
            # protección contra salir del rango
            if row >= df.shape[0]:
                break

            # si columna A está vacía, terminar
            if pd.isna(df.iloc[row, 0]) or str(df.iloc[row, 0]).strip() == "":
                break

            effective = str(df.iloc[row, 2]).strip()
            selector  = str(df.iloc[row, 3]).strip()

            if selector not in ["0", "1"]:
                row += 1
                continue

            value_0 = str(df.iloc[row, 4]).strip()
            value_1 = str(df.iloc[row, 5]).strip()

            if selector == "0":
                category_code = "0"
                category_display = display_0
                value = value_0
            else:
                category_code = "1"
                category_display = display_1
                value = value_1

            obs = {
                "resourceType": "Observation",
                "status": "final",
                "code": {"text": "Resultado desde Excel"},
                "effectiveDateTime": effective,
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://sistemaMedicion.cl/CS",
                                "code": category_code,
                                "display": category_display
                            }
                        ]
                    }
                ],
                "valueQuantity": {
                    "value": float(value),
                    "unit": "mg/dl",
                    "code": "mg/dl",
                    "system": "http://unitsofmeasure.org"
                }
            }

            observations.append(obs)
            row += 1

        ruta_observations = salida_base + "_observations.json"
        with open(ruta_observations, "w", encoding="utf-8") as f:
            json.dump(observations, f, ensure_ascii=False, indent=4)
            
            
        
        
        # =====================================================
        #                  COMPOSITION FHIR
        # =====================================================

        # Asignar IDs internos a los recursos para poder referenciarlos
        patient["id"] = "p1"
        device["id"] = "d1"

        # Asignar ID a cada Observation
        for idx, obs in enumerate(observations, start=1):
            obs["id"] = f"o{idx}"

        # Fecha actual ISO para el Composition
        fecha_reporte = datetime.now().isoformat()

        # Construcción del Composition
        composition = {
            "resourceType": "Composition",
            "id": "c1",
            "identifier": [{
                "system": "http://glucosa.cl/composition",
                "value": f"comp-{int(datetime.now().timestamp())}"
            }],
            "status": "final",
            "type": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "11502-2",
                    "display": "Laboratory report"
                }],
                "text": "Laboratory report"
            },
            "title": "Informe de Perfil Ambulatorio de Glucosa",
            "date": fecha_reporte,
            "author": [
                {"reference": "Device/d1"}
            ],
            "subject": {
                "reference": "Patient/p1"
            },
            "section": [
                {
                    "title": "Observaciones de Glucosa",
                    "entry": [
                        {"reference": f"Observation/{obs['id']}"} 
                        for obs in observations
                    ]
                }
            ]
        }


        # Guardar el Composition como JSON
        ruta_composition = salida_base + "_composition.json"
        with open(ruta_composition, "w", encoding="utf-8") as f:
            json.dump(composition, f, ensure_ascii=False, indent=4)
            
            


        # =====================================================
        #                 BUNDLE TYPE DOCUMENT
        # =====================================================
        import uuid

        # Crear fullURLs
        full_patient     = f"urn:uuid:{uuid.uuid4()}"
        full_device      = f"urn:uuid:{uuid.uuid4()}"
        full_composition = f"urn:uuid:{uuid.uuid4()}"

        # IDs internos ya asignados arriba:
        # patient["id"] = "p1"
        # device["id"]  = "d1"
        # obs["id"]     = "o1", "o2", ...

        # Generar fullURLs para observaciones
        observation_entries = []
        for obs in observations:
            full_obs = f"urn:uuid:{uuid.uuid4()}"
            observation_entries.append({
                "fullUrl": full_obs,
                "resource": obs
            })

        # Construir entries del Bundle
        bundle_entries = []

        # Composition como primer recurso del bundle (regla FHIR)
        bundle_entries.append({
            "fullUrl": full_composition,
            "resource": composition
        })

        # Patient
        bundle_entries.append({
            "fullUrl": full_patient,
            "resource": patient
        })

        # Device
        bundle_entries.append({
            "fullUrl": full_device,
            "resource": device
        })

        # Observations
        bundle_entries.extend(observation_entries)

        # Construir el Bundle final
        bundle = {
            "resourceType": "Bundle",
            "type": "document",
            "timestamp": datetime.now().isoformat(),
            "entry": bundle_entries
        }

        # Guardar el bundle document
        ruta_bundle = salida_base + "_bundle.json"
        with open(ruta_bundle, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False, indent=4)


        # =====================================================
        #        MENSAJE FINAL
        # =====================================================
        messagebox.showinfo(
            "FHIR generado",
            f"Archivos generados:\n\n{ruta_patient}\n{ruta_device}\n{ruta_observations}"
        )

    except Exception as e:
        messagebox.showerror("Error", f"Ocurrió un problema al convertir:\n{e}")


# ============================================================
#                  INTERFAZ TKINTER
# ============================================================

root = tk.Tk()
root.title("Conversor CSV → Excel + FHIR")
root.geometry("400x300")

entrada_var = tk.StringVar()
salida_var = tk.StringVar()

tk.Label(root, text="Archivo CSV de entrada:").pack(anchor="w", pady=5)
frame1 = tk.Frame(root)
frame1.pack(fill="x")
tk.Entry(frame1, textvariable=entrada_var, width=50).pack(side="left", padx=5)
tk.Button(frame1, text="Seleccionar", command=seleccionar_archivo).pack(side="left")

tk.Label(root, text="Nombre del archivo Excel de salida:").pack(anchor="w", pady=5)
tk.Entry(root, textvariable=salida_var, width=40).pack(padx=5)

tk.Button(root, text="Generar Excel", command=procesar,
          bg="#4CAF50", fg="white").pack(pady=10)

tk.Button(root, text="Convertir Excel a FHIR",
          command=convertir_a_fhir,
          bg="#2196F3", fg="white").pack(pady=10)

root.mainloop()
