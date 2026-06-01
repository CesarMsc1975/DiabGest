import argparse
import os
from pathlib import Path

import Motor
import fhir_client


def ingest_csv(csv_path, keep_files=False):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV no encontrado: {csv_path}")

    output_dir = Motor.crear_carpeta_conv()
    Motor.limpiar_contenido_carpeta(output_dir)

    excel_path = Path(output_dir) / f"{csv_path.stem}.xlsx"
    Motor.convertir_csv_a_excel(str(csv_path), str(excel_path))
    _, paths = Motor.convertir_excel_a_fhir_en_carpeta(str(excel_path), output_dir)

    status, location, body = fhir_client.post_bundle_file(paths["bundle"])
    bundle_url = fhir_client.extract_resource_url_from_response("Bundle", location, body)
    if not bundle_url:
        raise RuntimeError("El servidor recibio el Bundle, pero no entrego URL o id consultable.")

    result = {
        "csv": str(csv_path),
        "bundle_file": paths["bundle"],
        "status": status,
        "bundle_url": bundle_url,
    }

    if not keep_files:
        Motor.limpiar_contenido_carpeta(output_dir)
        result["bundle_file"] = ""

    return result


def main():
    parser = argparse.ArgumentParser(description="Lee un CSV, genera un Bundle FHIR y lo guarda en el servidor.")
    parser.add_argument("csv", help="Ruta al archivo CSV de glucosa.")
    parser.add_argument("--keep-files", action="store_true", help="Conservar archivos intermedios en conv/.")
    args = parser.parse_args()

    result = ingest_csv(args.csv, keep_files=args.keep_files)
    print(f"CSV: {result['csv']}")
    print(f"Servidor FHIR: HTTP {result['status']}")
    print(f"Bundle: {result['bundle_url']}")
    if result["bundle_file"]:
        print(f"Archivo local: {result['bundle_file']}")


if __name__ == "__main__":
    main()
