"""Read mock datasets and call the synthetic FastAPI purchasing API."""
from __future__ import annotations

import csv
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "backend" / "data"
PRODUCTS_FILE = DATA_DIR / "valio_aimo_junction26_product_data.json"
CARBON_FILE = DATA_DIR / "valio_aimo_junction26_carbon_footprint.csv"
DELIVERY_FILE = DATA_DIR / "valio_aimo_junction26_delivery_reliability.csv"
API_BASE_URL = os.getenv("VALIO_AIMO_API_URL", "http://127.0.0.1:8000").rstrip("/")


class DataServiceError(RuntimeError):
    """Raised when a mock data source or backend API cannot be used."""


def _request_json(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{API_BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
        except (ValueError, AttributeError):
            detail = str(exc)
        raise DataServiceError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DataServiceError(
            f"Could not reach the mock API at {API_BASE_URL}. Start the backend and try again. ({exc})"
        ) from exc


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def _products() -> tuple[dict[str, Any], ...]:
    if not PRODUCTS_FILE.is_file():
        return ()
    with PRODUCTS_FILE.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"Product data must be a JSON array: {PRODUCTS_FILE}")
    return tuple(item for item in data if isinstance(item, dict) and not item.get("deleted", False))


@lru_cache(maxsize=1)
def _carbon_by_product() -> dict[str, float]:
    result: dict[str, float] = {}
    for row in _read_csv(CARBON_FILE):
        product_id, value = row.get("productId"), row.get("AVG kg CO2-eq/kg")
        if product_id and value:
            try:
                result[product_id] = float(value)
            except ValueError:
                continue
    return result


@lru_cache(maxsize=1)
def _reliability_by_product() -> dict[str, float]:
    result: dict[str, float] = {}
    for row in _read_csv(DELIVERY_FILE):
        product_id, value = row.get("productId"), row.get("deliveryReliability")
        if product_id and value:
            try:
                result[product_id] = float(value)
            except ValueError:
                continue
    return result


def _product_name(product: dict[str, Any]) -> str:
    names = (product.get("synkkaData") or {}).get("names") or []
    preferred = sorted(names, key=lambda item: {"en": 0, "fi": 1, "sv": 2}.get(item.get("language"), 3))
    return next(
        (item.get("value", "") for item in preferred if item.get("value")),
        str(product.get("id", "Unknown product")),
    )


def _unit_dimension(unit: str) -> str | None:
    normalized = unit.casefold().strip()
    if normalized in {"l", "liter", "litre", "litres", "liters", "dl", "cl", "ml", "mlt", "ltr"}:
        return "volume"
    if normalized in {"kg", "kgm", "kilo", "kilogram", "g", "grm", "gram", "grams"}:
        return "weight"
    if normalized in {"pcs", "pc", "piece", "pieces", "unit", "units", "kpl"}:
        return "count"
    return None


def _product_search_text(product: dict[str, Any]) -> tuple[str, str]:
    synkka = product.get("synkkaData") or {}
    names = [str(item.get("value", "")) for item in synkka.get("names", []) if item.get("value")]
    primary_name = _product_name(product)
    identity = " ".join([str(product.get("id", "")), str(product.get("vendorName", "")), str(synkka.get("brand", "")), str(product.get("category", "")), *names]).casefold()
    return primary_name, identity


def _catalog_score(product: dict[str, Any], query: str, requested_unit: str | None, quantity: float | None) -> int | None:
    name, searchable = _product_search_text(product)
    tokens = [token for token in query.casefold().replace("-", " ").split() if token]
    if not tokens:
        return 0
    # Requiring every meaningful query term prevents broad substring hits such as
    # "milk" matching "milk chocolate" when the product is a derivative.
    searchable_words = set(searchable.replace("-", " ").replace("/", " ").split())
    if any(token not in searchable_words and token not in searchable for token in tokens):
        return None
    score = sum(100 if token in name.casefold().split() else 35 for token in tokens)
    if query.casefold() in name.casefold():
        score += 100
    modifiers = {"chocolate", "suklaa", "powder", "jauhe", "coconut", "kookos", "oat", "kaura", "soy", "soija", "almond", "manteli", "rice", "riisi"}
    extras = modifiers.intersection(searchable_words).difference(tokens)
    score -= 120 * len(extras)

    wanted = _unit_dimension(requested_unit or "")
    if wanted:
        synkka = product.get("synkkaData") or {}
        unit_text = " ".join([
            str(product.get("baseUnit", "")), str(product.get("salesUnit", "")),
            json.dumps(synkka.get("unitConversions", []), ensure_ascii=False),
            " ".join(str(item.get("value", "")) for item in synkka.get("names", [])),
        ]).casefold()
        has_volume = any(mark in unit_text for mark in ("litre", "liter", " l ", "ml", "cl", "dl", "ltr"))
        has_weight = any(mark in unit_text for mark in ("kg", "kilogram", "gram", " grm", " g "))
        has_count = any(mark in unit_text for mark in ("pcs", "piece", "unit", "kpl"))
        compatible = {"volume": has_volume, "weight": has_weight, "count": has_count}.get(wanted, False)
        score += 250 if compatible else -250
    if wanted == "weight" and quantity is not None and quantity >= 20:
        measurements = " ".join(str(item.get("value", "")) for item in (product.get("synkkaData") or {}).get("names", []))
        multi = re.search(r"(?<![\w.])(\d+)\s*[xX×]\s*(\d+(?:[.,]\d+)?)\s*(kgm|kg|g|grm|grams?)\b", measurements, re.IGNORECASE)
        single = multi or re.search(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(kg|g|grm|grams?)\b", measurements, re.IGNORECASE)
        if single:
            multiplier = int(multi.group(1)) if multi else 1
            amount = float((multi.group(2) if multi else single.group(1)).replace(",", "."))
            package_unit = multi.group(3) if multi else single.group(2)
            package_kg = amount * multiplier * (0.001 if package_unit.casefold() in {"g", "grm", "gram", "grams"} else 1)
            if 2 <= package_kg <= 10:
                score += 240 if multi else 320
            elif package_kg < 2:
                score -= 80
    return score


def get_products(query: str = "", limit: int = 100, requested_unit: str | None = None, quantity: float | None = None) -> list[dict[str, Any]]:
    """Search local records and rank lexical and unit-compatible matches first."""
    results: list[tuple[int, dict[str, Any]]] = []
    for product in _products():
        score = _catalog_score(product, query, requested_unit, quantity)
        if score is not None:
            results.append((score, {**product, "displayName": _product_name(product)}))
    results.sort(key=lambda item: item[0], reverse=True)
    return [product for _, product in results[:max(1, limit)]]


def create_quote(
    buyer_id: str,
    product_query: str,
    quantity: float,
    unit: str,
    max_delivery_date: str,
    product_id: str | None = None,
) -> dict[str, Any]:
    """Request a quote using backend/schemas.py request fields."""
    return _request_json(
        "/api/quote",
        method="POST",
        payload={
            "buyer_id": buyer_id,
            "items": [
                {
                    "product_query": product_query,
                    "product_id": product_id,
                    "quantity": quantity,
                    "unit": unit,
                    "max_delivery_date": max_delivery_date,
                }
            ],
        },
    )


def get_guardrails() -> dict[str, Any]:
    """Read the current backend purchasing limits."""
    return _request_json("/api/guardrails")


def update_guardrails(config: dict[str, Any]) -> dict[str, Any]:
    """Save purchasing limits using the backend GuardrailsConfig."""
    return _request_json("/api/guardrails", method="PUT", payload=config)


def create_order(buyer_id: str, signed_quote_token: str) -> dict[str, Any]:
    """Submit an order request; the backend decides whether approval is needed."""
    return _request_json(
        "/api/orders",
        method="POST",
        payload={"buyer_id": buyer_id, "signed_quote_token": signed_quote_token},
    )


def get_carbon_footprint(product_id: str) -> float | None:
    """Return kg CO2-eq per kg of product from the provided CSV."""
    return _carbon_by_product().get(str(product_id))


def get_delivery_reliability(product_id: str) -> float | None:
    """Return delivery reliability as a fraction from 0 to 1."""
    return _reliability_by_product().get(str(product_id))


def get_comparison_data() -> list[dict[str, Any]]:
    """Join carbon and delivery records without dropping products with missing metrics."""
    carbon = _carbon_by_product()
    reliability = _reliability_by_product()
    product_names = {str(p.get("id")): _product_name(p) for p in _products()}
    return [
        {
            "productId": product_id,
            "productName": product_names.get(product_id, product_id),
            "carbonKgCo2EqPerKg": carbon.get(product_id),
            "deliveryReliability": reliability.get(product_id),
        }
        for product_id in sorted(set(carbon) | set(reliability))
    ]


def get_data_status() -> dict[str, bool]:
    """Report which local datasets are available."""
    return {
        "Product records (JSON)": PRODUCTS_FILE.is_file(),
        "Carbon footprint (CSV)": CARBON_FILE.is_file(),
        "Delivery reliability (CSV)": DELIVERY_FILE.is_file(),
    }
