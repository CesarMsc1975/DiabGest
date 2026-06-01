import json
import os
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_FHIR_SERVER_BASE_URL = "https://fhirserver.hl7chile.cl/fhir"


def fhir_base_url():
    return os.environ.get("FHIR_SERVER_BASE_URL", DEFAULT_FHIR_SERVER_BASE_URL).rstrip("/")


def fhir_request(path_or_url, method="GET", payload=None, headers=None, timeout=30):
    if path_or_url.startswith(("http://", "https://")):
        url = path_or_url
    else:
        url = f"{fhir_base_url()}/{path_or_url.lstrip('/')}"

    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Accept": "application/fhir+json",
            **(headers or {}),
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, response.headers.get("Location", ""), body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Servidor FHIR respondio {exc.code}:\n{body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar al servidor FHIR:\n{exc.reason}") from exc


def get_json(path_or_url):
    _, _, body = fhir_request(path_or_url)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("El servidor FHIR no respondio con JSON valido.") from exc


def post_bundle_file(bundle_path):
    with open(bundle_path, "rb") as file:
        payload = file.read()

    return fhir_request(
        "/Bundle",
        method="POST",
        payload=payload,
        headers={"Content-Type": "application/fhir+json"},
    )


def resource_url(resource_type, resource_id):
    return f"{fhir_base_url()}/{resource_type}/{urllib.parse.quote(resource_id, safe='')}"


def extract_resource_url_from_response(resource_type, location, body):
    if location:
        clean = location.split("/_history/", 1)[0]
        if clean.startswith(("http://", "https://")):
            return clean

        clean = clean.lstrip("/")
        if clean.startswith(f"{resource_type}/"):
            return f"{fhir_base_url()}/{clean}"

        return f"{fhir_base_url()}/{resource_type}/{clean}"

    if not body:
        return ""

    try:
        resource = json.loads(body)
    except json.JSONDecodeError:
        return ""

    if resource.get("resourceType") == resource_type and resource.get("id"):
        return resource_url(resource_type, resource["id"])

    return ""


def search_document_bundles(count=50):
    query = urllib.parse.urlencode({"_sort": "-_lastUpdated", "_count": str(count)})
    searchset = get_json(f"/Bundle?{query}")

    if searchset.get("resourceType") != "Bundle":
        raise RuntimeError("La busqueda FHIR no devolvio un Bundle de resultados.")

    bundles = []
    for entry in searchset.get("entry", []):
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == "Bundle" and resource.get("type") == "document":
            bundles.append(resource)

    return bundles


def get_bundle(bundle_id):
    return get_json(f"/Bundle/{urllib.parse.quote(bundle_id, safe='')}")
