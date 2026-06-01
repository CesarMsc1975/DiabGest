import argparse
import os
from pathlib import Path
import sys

import Motor


def process_csv(ruta_csv: str, enviar: bool = False):
    ruta_csv = str(ruta_csv)
    if not os.path.exists(ruta_csv):
        raise FileNotFoundError(f"CSV no encontrado: {ruta_csv}")

    carpeta_salida = Motor.crear_carpeta_conv()
    Motor.limpiar_contenido_carpeta(carpeta_salida)
    nombre_excel = os.path.splitext(os.path.basename(ruta_csv))[0] + ".xlsx"
    salida_excel = os.path.join(carpeta_salida, nombre_excel)
    Motor.convertir_csv_a_excel(ruta_csv, salida_excel)
    carpeta, rutas = Motor.convertir_excel_a_fhir_en_carpeta(salida_excel, carpeta_salida)
    print(f"Recursos FHIR generados en: {carpeta}")
    print(f"Bundle JSON: {rutas.get('bundle')}")

    if enviar:
        print("Enviando bundle al servidor FHIR...")
        status, location, body = Motor.enviar_bundle_a_servidor(rutas["bundle"])
        print(f"Respuesta servidor: HTTP {status}")
        if location:
            print(f"Location: {location}")
        if body:
            print("Respuesta cuerpo (parcial):")
            print(body[:1000])


def main():
    parser = argparse.ArgumentParser(description="Procesar CSV de glucosa sin GUI y generar FHIR bundle.")
    parser.add_argument("csv", nargs="?", help="Ruta al archivo CSV (por defecto: primer CSV en la carpeta)")
    parser.add_argument("--send", action="store_true", help="Enviar el bundle al servidor FHIR")
    args = parser.parse_args()

    ruta_csv = args.csv
    if not ruta_csv:
        # buscar primer CSV en el directorio de trabajo
        cwd = Path(__file__).resolve().parent
        candidates = list(cwd.glob("*.csv"))
        if not candidates:
            print("No se encontró ningún CSV en el directorio. Especifica la ruta o coloca un CSV aquí.")
            sys.exit(1)
        ruta_csv = str(candidates[0])
        print(f"Usando CSV detectado: {ruta_csv}")

    try:
        process_csv(ruta_csv, enviar=args.send)
    except Exception as exc:
        print(f"Error durante el procesamiento: {exc}")
        raise


if __name__ == "__main__":
    main()
