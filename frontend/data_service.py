"""Read the Junction 2026 mock datasets from the repository.

The checked-in repository currently contains a product *schema*, but no product
records, price list, or availability feed. This module reports those missing
sources explicitly instead of fabricating commercial data.
"""
from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "backend" / "data"
PRODUCTS_FILE = DATA_DIR / "valio_aimo_junction26_product_data.json"
CARBON_FILE = DATA_DIR / "valio_aimo_junction26_carbon_footprint.csv"
DELIVERY_FILE = DATA_DIR / "valio_aimo_junction26_delivery_reliability.csv"
PRICE_FILE = DATA_DIR / "valio_aimo_junction26_prices.csv"
AVAILABILITY_FILE = DATA_DIR / "valio_aimo_junction26_availability.csv"


class DataSourceUnavailable(RuntimeError):
    """Raised when a requested mock-data source is not present."""


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
        product_id = row.get("productId")
        value = row.get("AVG kg CO2-eq/kg")
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
        product_id = row.get("productId")
        value = row.get("deliveryReliability")
        if product_id and value:
            try:
                result[product_id] = float(value)
            except ValueError:
                continue
    return result


def _product_name(product: dict[str, Any]) -> str:
    names = (product.get("synkkaData") or {}).get("names") or []
    preferred = sorted(names, key=lambda item: {"fi": 0, "en": 1, "sv": 2}.get(item.get("language"), 3))
    return next((item.get("value", "") for item in preferred if item.get("value")), product.get("id", "Tuntematon tuote"))


def get_products(query: str = "", limit: int = 100) -> list[dict[str, Any]]:
    """Search product records by name, brand, supplier or product code."""
    needle = query.strip().casefold()
    results: list[dict[str, Any]] = []
    for product in _products():
        searchable = " ".join(
            [str(product.get("id", "")), str(product.get("vendorName", "")),
             str((product.get("synkkaData") or {}).get("brand", "")), _product_name(product)]
        ).casefold()
        if needle and needle not in searchable:
            continue
        results.append({**product, "displayName": _product_name(product)})
        if len(results) >= max(1, limit):
            break
    return results


def get_product(product_id: str) -> dict[str, Any] | None:
    """Return one product record by its catalog id."""
    return next((product for product in get_products(limit=1_000_000) if str(product.get("id")) == str(product_id)), None)


def get_price(product_id: str, quantity: float = 1) -> dict[str, Any]:
    """Return the price record if a price feed is added; never estimate a price."""
    if not PRICE_FILE.is_file():
        return {"productId": product_id, "quantity": quantity, "price": None,
                "available": False, "source": None,
                "message": "Hintatietoa ei ole mukana nykyisessä mock-datassa."}
    raise DataSourceUnavailable(
        f"Hintatiedosto {PRICE_FILE.name} löytyi, mutta sille ei ole skeemaa tai API-määrittelyä."
    )


def get_availability(product_id: str, quantity: float = 1) -> dict[str, Any]:
    """Return availability if a stock feed is added; never infer stock from other data."""
    if not AVAILABILITY_FILE.is_file():
        return {"productId": product_id, "quantity": quantity, "available": None,
                "availableQuantity": None, "source": None,
                "message": "Varastosaatavuustietoa ei ole mukana nykyisessä mock-datassa."}
    raise DataSourceUnavailable(
        f"Saatavuustiedostolle {AVAILABILITY_FILE.name} ei ole skeemaa tai API-määrittelyä."
    )


def get_carbon_footprint(product_id: str) -> float | None:
    """Return the dataset's carbon intensity in kg CO2-eq per kg of product."""
    return _carbon_by_product().get(str(product_id))


def get_delivery_reliability(product_id: str) -> float | None:
    """Return the dataset's delivery reliability as a fraction from 0 to 1."""
    return _reliability_by_product().get(str(product_id))


def get_comparison_data() -> list[dict[str, Any]]:
    """Join carbon and delivery CSV rows by productId for comparison."""
    carbon = _carbon_by_product()
    reliability = _reliability_by_product()
    product_names = {str(p.get("id")): _product_name(p) for p in _products()}
    return [
        {"productId": product_id, "productName": product_names.get(product_id, product_id),
         "carbonKgCo2EqPerKg": footprint, "deliveryReliability": reliability[product_id]}
        for product_id, footprint in carbon.items()
        if product_id in reliability
    ]


def get_data_status() -> dict[str, bool]:
    """Report the availability of each input data file."""
    return {
        "Tuotetietueet (JSON)": PRODUCTS_FILE.is_file(),
        "Hintatiedot (CSV)": PRICE_FILE.is_file(),
        "Varastosaatavuus (CSV)": AVAILABILITY_FILE.is_file(),
        "Hiilijalanjälki (CSV)": CARBON_FILE.is_file(),
        "Toimitusvarmuus (CSV)": DELIVERY_FILE.is_file(),
    }
