import argparse
import html
import json
from datetime import datetime
from pathlib import Path


def parse_datetime(value):
    if not value:
        return None

    for fmt in ("%d-%m-%Y %H:%M", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    return None


def first_resource(bundle, resource_type):
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == resource_type:
            return resource
    return {}


def patient_name(patient):
    names = patient.get("name") or []
    if not names:
        return "Sin paciente"

    name = names[0]
    parts = []
    parts.extend(name.get("given") or [])
    if name.get("family"):
        parts.append(name["family"])

    for extension in name.get("extension") or []:
        if extension.get("valueString"):
            parts.append(extension["valueString"])

    return " ".join(parts) or "Sin paciente"


def device_name(device):
    names = device.get("deviceName") or []
    if names and names[0].get("name"):
        return names[0]["name"]
    return device.get("id") or "Sin dispositivo"


def patient_identifier(patient):
    identifiers = patient.get("identifier") or []
    for identifier in identifiers:
        if identifier.get("value"):
            return identifier["value"]
    return "-"


def device_serial(device):
    return device.get("serialNumber") or "-"


def has_code(resource, system, code):
    for coding in (resource.get("code") or {}).get("coding") or []:
        if coding.get("system") == system and coding.get("code") == code:
            return True
    return False


def coded_observation(bundle, code):
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") != "Observation":
            continue
        if has_code(resource, "http://loinc.org", code):
            return resource
    return {}


def ranges_panel(bundle):
    return coded_observation(bundle, "106793-3")


def observation_value(observation):
    quantity = observation.get("valueQuantity") or {}
    value = quantity.get("value")
    if value is None:
        return None
    return float(value)


RANGE_COMPONENTS = [
    ("104639-0", "TAR >250"),
    ("104640-8", "TAR 181-250"),
    ("97510-2", "TIR 70-180"),
    ("104641-6", "TBR 54-69"),
    ("104642-4", "TBR <54"),
]


def component_by_code(panel, code):
    for component in panel.get("component") or []:
        if has_code(component, "http://loinc.org", code):
            return component
    return {}


def component_value(component):
    quantity = component.get("valueQuantity") or {}
    value = quantity.get("value")
    if value is None:
        return None
    return float(value)


def range_panel_rows(bundle):
    panel = ranges_panel(bundle)
    rows = []
    for code, label in RANGE_COMPONENTS:
        component = component_by_code(panel, code)
        value = component_value(component)
        rows.append(
            {
                "code": code,
                "label": label,
                "value": value,
                "display": f"{value:.1f}%" if value is not None else "-",
                "text": (component.get("code") or {}).get("text") or "",
            }
        )
    return rows


def observations(bundle):
    rows = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") != "Observation":
            continue
        if (
            has_code(resource, "http://loinc.org", "106793-3")
            or has_code(resource, "http://loinc.org", "97510-2")
            or has_code(resource, "http://loinc.org", "104640-8")
            or has_code(resource, "http://loinc.org", "104639-0")
            or has_code(resource, "http://loinc.org", "104641-6")
            or has_code(resource, "http://loinc.org", "104642-4")
        ):
            continue

        quantity = resource.get("valueQuantity") or {}
        value = quantity.get("value")
        unit = quantity.get("unit") or quantity.get("code") or ""
        when_raw = resource.get("effectiveDateTime")
        when = parse_datetime(when_raw)

        if value is None or unit.lower() != "mg/dl":
            continue

        rows.append(
            {
                "id": resource.get("id", ""),
                "date": when_raw or "",
                "sort": when.isoformat() if when else when_raw or "",
                "value": float(value),
                "unit": unit,
                "method": (((resource.get("category") or [{}])[0].get("coding") or [{}])[0].get("display") or ""),
            }
        )

    return sorted(rows, key=lambda item: item["sort"])


def pct(count, total):
    if not total:
        return "0.0%"
    return f"{count * 100 / total:.1f}%"


def build_html(bundle, source_name):
    composition = first_resource(bundle, "Composition")
    patient = first_resource(bundle, "Patient")
    device = first_resource(bundle, "Device")
    obs = observations(bundle)
    values = [row["value"] for row in obs]

    total = len(values)
    minimum = min(values) if values else 0
    maximum = max(values) if values else 0
    average = sum(values) / total if total else 0
    low = sum(1 for value in values if value < 70)
    in_range = sum(1 for value in values if 70 <= value <= 180)
    high = sum(1 for value in values if value > 180)
    first = obs[0]["date"] if obs else "-"
    last = obs[-1]["date"] if obs else "-"
    report_date = composition.get("date") or bundle.get("timestamp", "-")
    patient_birth_date = patient.get("birthDate") or "-"
    range_rows = range_panel_rows(bundle)
    range_stats_html = "\n".join(
        f'      <div class="stat"><div class="label">{html.escape(row["label"])}</div><div class="value">{html.escape(row["display"])}</div></div>'
        for row in range_rows
    )
    range_table_rows_html = "\n".join(
        f"""            <tr>
              <td>{html.escape(row["label"])}</td>
              <td>{html.escape(row["code"])}</td>
              <td>{html.escape(row["display"])}</td>
              <td>{html.escape(row["text"])}</td>
            </tr>"""
        for row in range_rows
    )

    data_json = json.dumps(obs, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(composition.get("title") or "Bundle FHIR")}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #5d6978;
      --line: #d9e1ea;
      --accent: #0f766e;
      --low: #2563eb;
      --ok: #15803d;
      --high: #b45309;
      --danger: #b91c1c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      background: #ffffff;
      border-bottom: 1px solid var(--line);
      padding: 24px clamp(16px, 4vw, 48px);
    }}
    main {{
      padding: 24px clamp(16px, 4vw, 48px) 40px;
      max-width: 1240px;
      margin: 0 auto;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: clamp(24px, 3vw, 36px);
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 18px;
      letter-spacing: 0;
    }}
    .meta {{
      color: var(--muted);
      display: flex;
      gap: 14px;
      flex-wrap: wrap;
      font-size: 14px;
    }}
    .grid {{
      display: grid;
      gap: 16px;
    }}
    .stats {{
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      margin-bottom: 16px;
    }}
    .info-grid {{
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      margin-bottom: 16px;
    }}
    .stat, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .stat .label {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }}
    .stat .value {{
      font-size: 24px;
      font-weight: 700;
    }}
    .stat.period {{
      min-width: 260px;
    }}
    .stat.period .value {{
      font-size: 15px;
      line-height: 1.35;
      white-space: nowrap;
    }}
    .split {{
      grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
      align-items: start;
    }}
    svg {{
      display: block;
      width: 100%;
      height: 360px;
      overflow: visible;
    }}
    .axis, .gridline {{
      stroke: #cbd5e1;
      stroke-width: 1;
    }}
    .range {{
      fill: #dcfce7;
    }}
    .line {{
      fill: none;
      stroke: var(--accent);
      stroke-width: 2;
    }}
    .point {{
      fill: var(--accent);
      stroke: #ffffff;
      stroke-width: 1;
    }}
    .low {{ fill: var(--low); }}
    .high {{ fill: var(--high); }}
    .tick {{
      fill: var(--muted);
      font-size: 12px;
    }}
    .range-list {{
      display: grid;
      gap: 10px;
      margin: 0;
    }}
    .range-row {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: center;
      color: var(--muted);
      font-size: 14px;
    }}
    .bar {{
      height: 8px;
      background: #e5e7eb;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 6px;
    }}
    .bar span {{
      display: block;
      height: 100%;
      background: var(--ok);
    }}
    .bar.low span {{ background: var(--low); }}
    .bar.high span {{ background: var(--high); }}
    .table-wrap {{
      overflow: auto;
      max-height: 520px;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #ffffff;
      min-width: 680px;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      font-size: 14px;
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #eef3f8;
      z-index: 1;
    }}
    .info-table {{
      min-width: 0;
    }}
    .info-table th {{
      position: static;
      width: 38%;
      color: var(--muted);
      font-weight: 700;
      background: #f8fafc;
    }}
    .info-table td {{
      white-space: normal;
      font-weight: 600;
    }}
    .tag {{
      display: inline-block;
      min-width: 76px;
      text-align: center;
      padding: 3px 8px;
      border-radius: 999px;
      background: #dcfce7;
      color: #166534;
      font-size: 12px;
      font-weight: 700;
    }}
    .tag.low {{
      background: #dbeafe;
      color: #1d4ed8;
    }}
    .tag.high {{
      background: #fef3c7;
      color: #92400e;
    }}
    @media (max-width: 820px) {{
      .split {{ grid-template-columns: 1fr; }}
      .info-grid {{ grid-template-columns: 1fr; }}
      svg {{ height: 280px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(composition.get("title") or "Bundle FHIR")}</h1>
    <div class="meta">
      <span>Archivo: {html.escape(source_name)}</span>
      <span>Generado: {html.escape(bundle.get("timestamp", "-"))}</span>
    </div>
  </header>
  <main>
    <section class="grid info-grid" aria-label="Datos del informe">
      <div class="panel">
        <h2>Datos del paciente</h2>
        <table class="info-table">
          <tbody>
            <tr>
              <th>Nombre</th>
              <td>{html.escape(patient_name(patient))}</td>
            </tr>
            <tr>
              <th>Identificacion</th>
              <td>{html.escape(patient_identifier(patient))}</td>
            </tr>
            <tr>
              <th>Fecha nacimiento</th>
              <td>{html.escape(patient_birth_date)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="panel">
        <h2>Datos del informe</h2>
        <table class="info-table">
          <tbody>
            <tr>
              <th>Fecha informe</th>
              <td>{html.escape(report_date)}</td>
            </tr>
            <tr>
              <th>Dispositivo</th>
              <td>{html.escape(device_name(device))}</td>
            </tr>
            <tr>
              <th>Serie</th>
              <td>{html.escape(device_serial(device))}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="grid stats" aria-label="Resumen">
      <div class="stat"><div class="label">Lecturas</div><div class="value">{total}</div></div>
      <div class="stat"><div class="label">Promedio</div><div class="value">{average:.1f} mg/dl</div></div>
      <div class="stat"><div class="label">Minimo</div><div class="value">{minimum:.0f} mg/dl</div></div>
      <div class="stat"><div class="label">Maximo</div><div class="value">{maximum:.0f} mg/dl</div></div>
{range_stats_html}
      <div class="stat period"><div class="label">Periodo</div><div class="value">{html.escape(first)}<br>{html.escape(last)}</div></div>
    </section>

    <section class="panel" style="margin-bottom:16px">
      <h2>Panel de tiempo en rangos</h2>
      <div class="table-wrap" style="max-height:none">
        <table>
          <thead>
            <tr>
              <th>Metrica</th>
              <th>LOINC</th>
              <th>Valor</th>
              <th>Texto</th>
            </tr>
          </thead>
          <tbody>
{range_table_rows_html}
          </tbody>
        </table>
      </div>
    </section>

    <section class="grid split">
      <div class="panel">
        <h2>Glucosa en el tiempo</h2>
        <svg id="chart" role="img" aria-label="Grafico de glucosa"></svg>
      </div>
      <aside class="panel">
        <h2>Rangos</h2>
        <div class="range-list">
          <div>
            <div class="range-row"><span>Bajo &lt; 70 mg/dl</span><strong>{low} ({pct(low, total)})</strong></div>
            <div class="bar low"><span style="width:{low * 100 / total if total else 0:.2f}%"></span></div>
          </div>
          <div>
            <div class="range-row"><span>En rango 70-180 mg/dl</span><strong>{in_range} ({pct(in_range, total)})</strong></div>
            <div class="bar"><span style="width:{in_range * 100 / total if total else 0:.2f}%"></span></div>
          </div>
          <div>
            <div class="range-row"><span>Alto &gt; 180 mg/dl</span><strong>{high} ({pct(high, total)})</strong></div>
            <div class="bar high"><span style="width:{high * 100 / total if total else 0:.2f}%"></span></div>
          </div>
        </div>
      </aside>
    </section>

    <section class="panel" style="margin-top:16px">
      <h2>Observaciones</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Fecha</th>
              <th>Valor</th>
              <th>Unidad</th>
              <th>Rango</th>
              <th>Metodo</th>
            </tr>
          </thead>
          <tbody id="rows"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    const observations = {data_json};

    function escapeText(value) {{
      return String(value ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    }}

    function rangeClass(value) {{
      if (value < 70) return 'low';
      if (value > 180) return 'high';
      return '';
    }}

    function rangeLabel(value) {{
      if (value < 70) return 'Bajo';
      if (value > 180) return 'Alto';
      return 'En rango';
    }}

    document.getElementById('rows').innerHTML = observations.map(row => `
      <tr>
        <td>${{escapeText(row.id)}}</td>
        <td>${{escapeText(row.date)}}</td>
        <td>${{Number(row.value).toFixed(0)}}</td>
        <td>${{escapeText(row.unit)}}</td>
        <td><span class="tag ${{rangeClass(row.value)}}">${{rangeLabel(row.value)}}</span></td>
        <td>${{escapeText(row.method)}}</td>
      </tr>
    `).join('');

    function drawChart() {{
      const svg = document.getElementById('chart');
      const width = svg.clientWidth || 900;
      const height = svg.clientHeight || 360;
      const margin = {{ top: 18, right: 18, bottom: 34, left: 48 }};
      const innerWidth = width - margin.left - margin.right;
      const innerHeight = height - margin.top - margin.bottom;
      const values = observations.map(row => row.value);
      const minY = Math.min(50, ...values);
      const maxY = Math.max(200, ...values);
      const x = index => margin.left + (observations.length <= 1 ? 0 : index * innerWidth / (observations.length - 1));
      const y = value => margin.top + (maxY - value) * innerHeight / (maxY - minY);
      const path = observations.map((row, index) => `${{index ? 'L' : 'M'}} ${{x(index).toFixed(2)}} ${{y(row.value).toFixed(2)}}`).join(' ');
      const ticks = [50, 70, 100, 140, 180, 200];
      const startLabel = observations[0]?.date ?? '';
      const endLabel = observations[observations.length - 1]?.date ?? '';

      svg.setAttribute('viewBox', `0 0 ${{width}} ${{height}}`);
      svg.innerHTML = `
        <rect class="range" x="${{margin.left}}" y="${{y(180)}}" width="${{innerWidth}}" height="${{Math.max(0, y(70) - y(180))}}"></rect>
        ${{ticks.map(tick => `
          <line class="gridline" x1="${{margin.left}}" y1="${{y(tick)}}" x2="${{width - margin.right}}" y2="${{y(tick)}}"></line>
          <text class="tick" x="8" y="${{y(tick) + 4}}">${{tick}}</text>
        `).join('')}}
        <line class="axis" x1="${{margin.left}}" y1="${{height - margin.bottom}}" x2="${{width - margin.right}}" y2="${{height - margin.bottom}}"></line>
        <line class="axis" x1="${{margin.left}}" y1="${{margin.top}}" x2="${{margin.left}}" y2="${{height - margin.bottom}}"></line>
        <path class="line" d="${{path}}"></path>
        ${{observations.map((row, index) => `<circle class="point ${{rangeClass(row.value)}}" cx="${{x(index)}}" cy="${{y(row.value)}}" r="3"><title>${{escapeText(row.date)}}: ${{row.value}} mg/dl</title></circle>`).join('')}}
        <text class="tick" x="${{margin.left}}" y="${{height - 8}}">${{escapeText(startLabel)}}</text>
        <text class="tick" text-anchor="end" x="${{width - margin.right}}" y="${{height - 8}}">${{escapeText(endLabel)}}</text>
      `;
    }}

    window.addEventListener('resize', drawChart);
    drawChart();
  </script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Render a FHIR document Bundle as a standalone HTML report.")
    parser.add_argument("bundle", type=Path, help="Path to the FHIR Bundle JSON file.")
    parser.add_argument("-o", "--output", type=Path, help="Output HTML path.")
    args = parser.parse_args()

    bundle_path = args.bundle
    output_path = args.output or bundle_path.with_suffix(".html")

    with bundle_path.open("r", encoding="utf-8-sig") as file:
        bundle = json.load(file)

    output_path.write_text(build_html(bundle, bundle_path.name), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
