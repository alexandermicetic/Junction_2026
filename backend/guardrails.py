"""Explicit purchasing guardrail evaluation."""

from schemas import GuardrailsConfig, QuotedProduct


def evaluate_order(items: list[QuotedProduct], total_eur: float, config: GuardrailsConfig) -> tuple[bool, list[str]]:
    """Return whether an order is autonomous, plus clear English blocking reasons."""
    reasons: list[str] = []
    if total_eur > config.max_autonomous_spend_eur:
        reasons.append(f"Total spend of EUR {total_eur:.2f} exceeds the autonomous limit of EUR {config.max_autonomous_spend_eur:.2f}.")
    forbidden = {allergen.lower() for allergen in config.forbidden_allergens}
    for item in items:
        item_allergens = {allergen.lower() for allergen in item.allergens}
        labels = {label.lower().replace("-", "_") for label in item.sustainability_labels}
        product_name = item.name.lower()
        lactose_free = bool({"lactose_free", "free_from_lactose", "low_lactose"}.intersection(labels)) or "laktoositon" in product_name or "lactose-free" in product_name or "lactose free" in product_name
        normalized_allergens = set(item_allergens)
        # GS1 code AM means milk/dairy. It is relevant to a lactose rule unless the product is explicitly lactose-free.
        if "am" in item_allergens and not lactose_free:
            normalized_allergens.add("lactose")
            normalized_allergens.add("milk")
        matches = forbidden.intersection(normalized_allergens)
        if matches:
            reasons.append(f"Product {item.sku} contains forbidden allergen(s): {', '.join(sorted(matches))}.")
        if item.is_substitution and not config.allow_substitutions:
            reasons.append(f"Product {item.sku} is a substitution, but substitutions are disabled by the guardrails.")
    return not reasons, reasons
