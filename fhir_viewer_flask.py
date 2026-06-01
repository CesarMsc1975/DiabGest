import os

from flask import Flask, abort, render_template_string, url_for

import fhir_client
from render_bundle_html import build_html, first_resource, observations, patient_name


app = Flask(__name__)


INDEX_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pacientes FHIR</title>
  <style>
    :root {
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #18212f;
      --muted: #607086;
      --line: #dce3ea;
      --accent: #0f766e;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 20px clamp(16px, 4vw, 44px);
    }
    main {
      width: min(1180px, calc(100% - 32px));
      margin: 24px auto 44px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: 26px;
      letter-spacing: 0;
    }
    .meta {
      color: var(--muted);
      font-size: 14px;
    }
    .toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 14px;
    }
    .button {
      display: inline-flex;
      align-items: center;
      min-height: 36px;
      padding: 8px 12px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      color: #ffffff;
      background: var(--accent);
      text-decoration: none;
      font-size: 14px;
      font-weight: 700;
    }
    .table-wrap {
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }
    th, td {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: middle;
      font-size: 14px;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      background: #fbfcfd;
    }
    tr:last-child td { border-bottom: 0; }
    .empty {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 22px;
      color: var(--muted);
    }
    .link {
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }
  </style>
</head>
<body>
  <header>
    <h1>Pacientes en servidor FHIR</h1>
    <div class="meta">{{ base_url }}</div>
  </header>
  <main>
    <div class="toolbar">
      <div class="meta">{{ patients|length }} informes encontrados</div>
      <a class="button" href="{{ url_for('index') }}">Actualizar</a>
    </div>
    {% if patients %}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Paciente</th>
              <th>Fecha informe</th>
              <th>Mediciones</th>
              <th>Primera medicion</th>
              <th>Ultima medicion</th>
              <th>Informe</th>
            </tr>
          </thead>
          <tbody>
            {% for patient in patients %}
              <tr>
                <td>{{ patient.name }}</td>
                <td>{{ patient.report_date or "-" }}</td>
                <td>{{ patient.count }}</td>
                <td>{{ patient.first_observation or "-" }}</td>
                <td>{{ patient.last_observation or "-" }}</td>
                <td><a class="link" href="{{ url_for('report', bundle_id=patient.bundle_id) }}">Ver informe</a></td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    {% else %}
      <div class="empty">No hay Bundles documentales disponibles en el servidor.</div>
    {% endif %}
  </main>
</body>
</html>
"""


ERROR_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Error FHIR</title>
  <style>
    body { margin: 0; font-family: Arial, Helvetica, sans-serif; background: #f7f8fa; color: #18212f; }
    main { width: min(880px, calc(100% - 32px)); margin: 36px auto; }
    pre { white-space: pre-wrap; background: #fff; border: 1px solid #dce3ea; border-radius: 8px; padding: 16px; }
    a { color: #0f766e; font-weight: 700; }
  </style>
</head>
<body>
  <main>
    <h1>No se pudo consultar el servidor FHIR</h1>
    <p><a href="{{ url_for('index') }}">Volver</a></p>
    <pre>{{ error }}</pre>
  </main>
</body>
</html>
"""


def summarize_bundle(bundle):
    composition = first_resource(bundle, "Composition")
    patient = first_resource(bundle, "Patient")
    rows = observations(bundle)

    return {
        "bundle_id": bundle.get("id", ""),
        "name": patient_name(patient),
        "report_date": composition.get("date", ""),
        "count": len(rows),
        "first_observation": rows[0]["date"] if rows else "",
        "last_observation": rows[-1]["date"] if rows else "",
    }


@app.route("/")
def index():
    try:
        bundles = fhir_client.search_document_bundles()
        patients = [summarize_bundle(bundle) for bundle in bundles if bundle.get("id")]
    except Exception as exc:
        return render_template_string(ERROR_TEMPLATE, error=str(exc)), 502

    return render_template_string(
        INDEX_TEMPLATE,
        base_url=fhir_client.fhir_base_url(),
        patients=patients,
    )


@app.route("/bundle/<bundle_id>/report")
def report(bundle_id):
    try:
        bundle = fhir_client.get_bundle(bundle_id)
    except Exception as exc:
        return render_template_string(ERROR_TEMPLATE, error=str(exc)), 502

    if bundle.get("resourceType") != "Bundle" or bundle.get("type") != "document":
        abort(404)

    return build_html(bundle, f"{fhir_client.fhir_base_url()}/Bundle/{bundle_id}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
