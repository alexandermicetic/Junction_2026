"""Async client for Valio's on-demand price and availability APIs."""

import json
import math
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from schemas import QuotedProduct, QuoteItemRequest

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")


def _api_url(base_url: str, path: str) -> str:
    """Join the API root and endpoint, accepting the health-check URL as config too."""
    base = base_url.rstrip("/")
    if base.endswith("/api/ping"):
        base = base[:-len("/ping")]
    elif base.endswith("/ping"):
        base = base[:-len("/ping")]
    normalized_path = "/" + path.lstrip("/")
    if base.endswith("/api") and normalized_path.startswith("/api/"):
        normalized_path = normalized_path[4:]
    return f"{base}{normalized_path}"


def _text_values(values: list[dict[str, Any]], keys: tuple[str, ...] = ("value", "id")) -> list[str]:
    return [str(next((entry.get(key) for key in keys if entry.get(key)), "")) for entry in values]


def _english_name(product: dict[str, Any]) -> str:
    names = product.get("synkkaData", {}).get("names", [])
    return next((item["value"] for item in names if item.get("language") == "en"), product.get("id", "Unknown product"))


UNIT_ALIASES = {
    "l": "volume", "liter": "volume", "litre": "volume", "litres": "volume", "liters": "volume",
    "dl": "volume", "cl": "volume", "ml": "volume", "mlt": "volume", "ltr": "volume",
    "kg": "weight", "kgm": "weight", "kilo": "weight", "kilogram": "weight", "g": "weight", "grm": "weight", "gram": "weight", "grams": "weight",
}
CANONICAL_UNITS = {"l": "L", "ltr": "L", "ml": "mlt", "mlt": "mlt", "cl": "cl", "dl": "dl", "kg": "kg", "g": "g", "grm": "g", "k gm": "kg", "kgm": "kg"}
QUERY_SYNONYMS = {
    "maito": {"maito", "milk"}, "milk": {"maito", "milk"},
    "laktoositon": {"laktoositon", "lactose-free", "lactose free"},
    "lactose-free": {"laktoositon", "lactose-free", "lactose free"},
}
DERIVATIVE_MODIFIERS = frozenset({
    "coconut", "kookos", "oat", "kaura", "soy", "soija", "almond", "manteli",
    "rice", "riisi", "chocolate", "suklaa", "powder", "jauhe", "condensed",
    "tiiviste", "sauce", "kastike", "ice cream", "jäätelö", "liqueur", "likööri",
})
CORE_DAIRY_PATTERN = re.compile(
    r"(?<![\w])(?:milk|maito|kevytmaito|rasvaton\s+maito|rasvatonmaito|täysmaito|luomumaito|maitojuoma)(?![\w])",
    re.IGNORECASE,
)
CORE_DAIRY_CATEGORY_PATTERN = re.compile(
    r"(?<![\w])(?:dairy|milk|milk products|maito|meijeri|meijerituotteet)(?![\w])",
    re.IGNORECASE,
)
FINNISH_MAITO_COMPOUND_PATTERN = re.compile(r"(?<![\w])maito[a-zäöå-]+(?![\w])", re.IGNORECASE)


def _base_quantity(value: float, unit: str, dimension: str) -> float:
    """Convert a volume to litres or a weight to kilograms for arithmetic."""
    normalized = unit.strip().lower()
    if dimension == "volume":
        return value / {"ml": 1000, "mlt": 1000, "cl": 100, "dl": 10}.get(normalized, 1)
    if dimension == "weight":
        return value / 1000 if normalized in {"g", "grm", "gram", "grams"} else value
    return value


def _measurement(text: str) -> tuple[float, str, str] | None:
    """Extract the first real package measurement, ignoring multipack counts."""
    match = re.search(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(ml|cl|dl|ltr|l|kg|g)\b", text.lower())
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2)
    display_unit = CANONICAL_UNITS.get(unit, unit)
    dimension = UNIT_ALIASES[unit]
    return value, display_unit, dimension


def _product_measurement(product: dict[str, Any], names: list[dict[str, Any]]) -> tuple[float, str, str] | None:
    """Read package size from product names/marketing and then unit-conversion fields."""
    searchable = " ".join(str(item.get("value", "")) for item in names)
    searchable += " " + " ".join(str(item.get("value", "")) for item in product.get("synkkaData", {}).get("marketingTexts", []))
    parsed = _measurement(searchable)
    if parsed:
        return parsed
    conversions = product.get("synkkaData", {}).get("unitConversions", [])
    for conversion in conversions:
        for field, unit in (("volume", "l"), ("netWeight", "g")):
            value = conversion.get(field, {}).get("value")
            if value:
                source_unit = str(conversion[field].get("unit", unit)).lower()
                if field == "volume" and source_unit not in {"kg", "kgm", "g", "grm"}:
                    numeric = float(value)
                    display_unit = "L" if source_unit in {"ltr", "l"} else CANONICAL_UNITS.get(source_unit, source_unit)
                    dimension = "volume"
                else:
                    numeric = float(value)
                    display_unit = "g" if source_unit in {"grm", "g"} else CANONICAL_UNITS.get(source_unit, source_unit)
                    dimension = "weight"
                return numeric, display_unit, dimension
    return None


def _catalog_product(product: dict[str, Any]) -> dict[str, Any]:
    synkka = product.get("synkkaData", {})
    names = synkka.get("names", [])
    classifications = {item.get("name"): item.get("values", []) for item in synkka.get("classifications", [])}
    labels = _text_values(classifications.get("nutritionalClaim", [])) + _text_values(classifications.get("packagingMarkedLabel", []))
    allergens = _text_values(classifications.get("allergen", []))
    measurement = _product_measurement(product, names)
    package_sizes = ([{"unit": measurement[1], "size": measurement[0], "base_size": _base_quantity(measurement[0], measurement[1], measurement[2]), "dimension": measurement[2]}] if measurement else [])
    names_text = " ".join(str(item.get("value", "")) for item in names)
    search_text = " ".join([
        str(item.get("value", "")) for item in names
    ] + [str(product.get("category", "")), str(product.get("id", "")), *allergens, *labels])
    return {
        "sku": str(product.get("id", "")),
        "name": _english_name(product),
        "name_variants": names_text,
        "category": str(product.get("category", "")),
        "brand": str(synkka.get("brand") or ""),
        "manufacturer": str(product.get("vendorName") or ""),
        "package_sizes": package_sizes or [{"unit": product.get("baseUnit", "unit"), "size": 1.0}],
        "allergens": allergens,
        "sustainability_labels": labels,
        "search_text": search_text + " " + str(synkka.get("brand", "")) + " " + str(product.get("vendorName", "")),
    }


def _load_catalog() -> list[dict[str, Any]]:
    """Load the static product catalog once at process startup."""
    catalog_path = BACKEND_DIR / "data" / "valio_aimo_junction26_product_data.json"
    with catalog_path.open("r", encoding="utf-8") as catalog_file:
        raw_catalog = json.load(catalog_file)
    return [_catalog_product(product) for product in raw_catalog if not product.get("deleted", False)]


CATALOG = _load_catalog()


def _search_catalog(query: str, quantity: float | None = None, requested_unit: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Rank local catalog matches before making any on-demand API calls."""
    query_lower = query.lower()
    tokens = {token.lower() for token in query.split() if token.strip()}
    normalized_unit = str(requested_unit or next((token for token in tokens if token in UNIT_ALIASES), "")).lower()
    requested_dimension = UNIT_ALIASES.get(normalized_unit)
    requested_volume = requested_dimension == "volume"
    generic_dairy_query = bool(CORE_DAIRY_PATTERN.search(query_lower)) and not any(
        modifier in query_lower for modifier in DERIVATIVE_MODIFIERS
    )

    def expanded_tokens(token: str) -> set[str]:
        return QUERY_SYNONYMS.get(token, {token})

    def compatible(product: dict[str, Any]) -> bool:
        return requested_dimension is None or any(item.get("dimension") == requested_dimension for item in product["package_sizes"])

    def is_powder(product: dict[str, Any]) -> bool:
        return bool(re.search(r"\b(powder|jauhe)\b", product["search_text"].lower()))

    def liquid_match(product: dict[str, Any]) -> bool:
        return any(item.get("dimension") == "volume" for item in product["package_sizes"]) and not is_powder(product)

    def eligible(product: dict[str, Any]) -> bool:
        # Apply the requested dimension (and liquid-only rule for volume) before scoring.
        return compatible(product) and (not requested_volume or liquid_match(product))

    def relevant_name(product: dict[str, Any]) -> bool:
        name = product["search_text"].lower()
        for token in tokens:
            if token in UNIT_ALIASES:
                continue
            variants = expanded_tokens(token)
            if not any(
                re.search(rf"(?<!\w){re.escape(variant)}(?!\w)", name)
                or re.search(rf"(?<!\w){re.escape(variant)}[\w-]+(?!\w)", name)
                or re.search(rf"(?<!\w)(?:[\w-]+)?{re.escape(variant)}(?:juoma|drink|free)?(?!\w)", name)
                for variant in variants
            ):
                return False
        return True

    def score(product: dict[str, Any]) -> int:
        name = product["name"].lower()
        product_name = f"{product['name']} {product.get('name_variants', '')}".casefold()
        product_text = f"{product_name} {product['search_text']}".casefold()
        score_value = 0
        for token in tokens:
            if token in UNIT_ALIASES:
                continue
            variants = expanded_tokens(token)
            if any(re.search(rf"\b{re.escape(variant)}\b", name) for variant in variants):
                score_value += 100
            elif any(re.search(rf"\b[\w-]*{re.escape(variant)}[\w-]*\b", name) for variant in variants):
                score_value += 60
            elif any(variant in product["search_text"].lower() for variant in variants):
                score_value += 10
        for modifier in DERIVATIVE_MODIFIERS:
            if modifier in product_name and modifier not in query_lower:
                score_value -= 120
        if re.search(r"(?<![\w])maito(?![\w])", query_lower) and any(
            compound.casefold() != "maitojuoma"
            for compound in FINNISH_MAITO_COMPOUND_PATTERN.findall(product_text)
        ):
            score_value -= 100
        if generic_dairy_query:
            if CORE_DAIRY_PATTERN.search(product_text):
                score_value += 60
            identity = f"{product.get('brand', '')} {product.get('manufacturer', '')}"
            if (
                re.search(r"(?<![\w])valio(?![\w])", identity, re.IGNORECASE)
                or CORE_DAIRY_CATEGORY_PATTERN.search(product["category"])
            ):
                score_value += 35
        return score_value

    # Apply requested dimensions before scoring so incompatible products never compete.
    matches = [product for product in CATALOG if eligible(product) and relevant_name(product) and score(product) > 0]
    ranked = sorted(matches, key=score, reverse=True)
    results = [dict(product) for product in ranked[:limit]]
    if quantity is not None:
        for product in results:
            requested_base_qty = _base_quantity(quantity, normalized_unit, requested_dimension or "")
            package = min(product["package_sizes"], key=lambda item: abs(item.get("base_size", item["size"]) - max(requested_base_qty, 1)))
            product["package_size"] = f"{package['size']:g} {package['unit']}"
            product["package_quantity"] = max(1, math.ceil(requested_base_qty / package.get("base_size", package["size"])))
    return results


def search_catalog(query: str, quantity: float, requested_unit: str) -> list[dict[str, Any]]:
    """Return ranked catalog matches with a real package label and required package count."""
    return _search_catalog(query, quantity, requested_unit)


class ValioClient:
    """Client that performs at most two on-demand requests for shortlisted products."""

    def __init__(self) -> None:
        self.base_url = os.getenv("VALIO_BASE_URL", "").strip().rstrip("/")
        self.api_key = os.getenv("VALIO_API_KEY", "")
        if not self.base_url or not self.api_key:
            raise RuntimeError("VALIO_BASE_URL and VALIO_API_KEY must be configured in backend/.env")

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"X-API-Key": self.api_key}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(_api_url(self.base_url, path), json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

    async def build_quote(self, request_items: list[QuoteItemRequest], buyer_id: str) -> list[QuotedProduct]:
        """Search locally, then query price and availability only for the top matches."""
        candidates_by_request: list[list[dict[str, Any]]] = []
        for request_item in request_items:
            if request_item.product_id:
                # An explicit selection must resolve to that exact SKU; search the
                # complete locally eligible result set so ranking cannot displace it.
                candidates = _search_catalog(
                    request_item.product_query, request_item.quantity, request_item.unit,
                    limit=len(CATALOG),
                )
                candidates = [item for item in candidates if item["sku"] == request_item.product_id]
                if not candidates:
                    raise ValueError("The selected product ID does not match the requested product or unit")
            else:
                candidates = _search_catalog(request_item.product_query, request_item.quantity, request_item.unit)
            candidates_by_request.append(candidates)
        selected = [candidate for candidates in candidates_by_request for candidate in candidates]
        unique = {item["sku"]: item for item in selected}
        shortlisted = list(unique.values())[:10]
        if not shortlisted:
            raise ValueError("No matching products were found in the static catalog")
        requested_date = request_items[0].max_delivery_date
        codes = [item["sku"] for item in shortlisted]
        payload = {"customer": buyer_id, "requestedDate": requested_date, "products": codes}
        price_data, availability_data = await self._on_demand(payload)
        prices = {str(item["productId"]): item for item in price_data.get("products", [])}
        availability = {str(item["productId"]): item for item in availability_data.get("products", [])}
        result: list[QuotedProduct] = []
        shortlisted_by_sku = {item["sku"]: item for item in shortlisted}
        for request_item, request_candidates in zip(request_items, candidates_by_request):
            # Work only with results from this request's own lexical/unit-compatible shortlist.
            candidates = [shortlisted_by_sku[item["sku"]] for item in request_candidates if item["sku"] in shortlisted_by_sku]
            requested_dimension = UNIT_ALIASES.get(request_item.unit.lower())
            remaining = _base_quantity(request_item.quantity, request_item.unit, requested_dimension or "")
            for candidate in candidates:
                price = prices.get(candidate["sku"], {})
                availability_item = availability.get(candidate["sku"], {})
                price_object = price.get("catalogPrice") or price.get("priceWithTax") or {}
                unit_price = float(price_object.get("value", 0.0))
                schedule = availability_item.get("scheduleLines", [])
                available = float(schedule[0].get("availableAmount", 0.0)) if schedule else 0.0
                requested_base_qty = _base_quantity(request_item.quantity, request_item.unit, requested_dimension or "")
                package = min(candidate["package_sizes"], key=lambda item: abs(item.get("base_size", item["size"]) - max(requested_base_qty, 1)))
                package_base_qty = package.get("base_size", package["size"])
                package_quantity = min(max(1, math.ceil(remaining / package_base_qty)), int(available))
                if package_quantity <= 0:
                    continue
                total = round(package_quantity * unit_price, 2)
                result.append(QuotedProduct(sku=candidate["sku"], name=candidate["name"], package_size=f"{package['size']:g} {package['unit']}", quantity=package_quantity, unit_price_eur=unit_price, total_price_eur=total, in_stock=not availability_item.get("salesBlock", False) and available > 0, allergens=candidate["allergens"], sustainability_labels=candidate["sustainability_labels"], is_substitution=False, substitution_reason=None))
                remaining -= package_quantity * package_base_qty
                if remaining <= 0:
                    break
            if remaining > 0 and result:
                result[-1].is_substitution = True
                result[-1].substitution_reason = "The preferred package sizes did not fully cover the requested quantity; an available shortlisted product was used."
        if not result:
            raise ValueError("No shortlisted product is available for the requested delivery date")
        return result

    async def _on_demand(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Query price and availability for the same shortlist."""
        return await self._post("/api/price", payload), await self._post("/api/availability", payload)
