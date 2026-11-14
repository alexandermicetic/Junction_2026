"""Read mock datasets and call the synthetic FastAPI purchasing API."""
from __future__ import annotations

import csv
import json
import os
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


def get_products(query: str = "", limit: int = 100) -> list[dict[str, Any]]:
    """Search local product records by name, brand, supplier, or product code."""
    needle = query.strip().casefold()
    results: list[dict[str, Any]] = []
    for product in _products():
        searchable = " ".join(
            [
                str(product.get("id", "")),
                str(product.get("vendorName", "")),
                str((product.get("synkkaData") or {}).get("brand", "")),
                _product_name(product),
            ]
        ).casefold()
        if needle and needle not in searchable:
            continue
        results.append({**product, "displayName": _product_name(product)})
        if len(results) >= max(1, limit):
            break
    return results


def create_quote(
    buyer_id: str,
    product_query: str,
    quantity: float,
    unit: str,
    max_delivery_date: str,
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
    """Join carbon footprint and delivery reliability records by productId."""
    carbon = _carbon_by_product()
    reliability = _reliability_by_product()
    product_names = {str(p.get("id")): _product_name(p) for p in _products()}
    return [
        {
            "productId": product_id,
            "productName": product_names.get(product_id, product_id),
            "carbonKgCo2EqPerKg": footprint,
            "deliveryReliability": reliability[product_id],
        }
        for product_id, footprint in carbon.items()
        if product_id in reliability
    ]


def get_data_status() -> dict[str, bool]:
    """Report which local datasets are available."""
    return {
        "Product records (JSON)": PRODUCTS_FILE.is_file(),
        "Carbon footprint (CSV)": CARBON_FILE.is_file(),
        "Delivery reliability (CSV)": DELIVERY_FILE.is_file(),
    }
