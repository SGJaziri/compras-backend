# core/services.py
from django.db import transaction
from django.utils import timezone

from decimal import Decimal

def generate_series_code(restaurant_code: str, model_cls, year=None):
    """
    Genera un código de serie único tipo YYYY-XXX-####.
    - restaurant_code: código de 3 letras del restaurante (ej. ALP, MIL).
    - model_cls: clase del modelo (ej. PurchaseList).
    - year: por defecto el año actual.
    """
    year = year or timezone.now().year
    with transaction.atomic():
        base_qs = model_cls.objects.select_for_update().filter(
            restaurant__code=restaurant_code,
            created_at__year=year
        )
        seq = base_qs.count() + 1
        return f"{year}-{restaurant_code}-{seq:04d}"

def next_serial_for(model_cls, restaurant_code, year=None):
    # Alias simple para mantener compatibilidad con serializers
    return generate_series_code(restaurant_code=restaurant_code, model_cls=model_cls, year=year)

def format_qty_human(qty: Decimal, unit_name: str) -> str:
    """
    Si la unidad es kg/kilogramo => devuelve formato humano:
    5.5 -> "5 kg 1/2", 0.25 -> "1/4 kg"
    Caso contrario => devuelve string normal (sin alterar).
    """
    name = (unit_name or "").strip().lower()
    is_kg = ("kg" == name) or ("kilogram" in name) or ("kilogramo" in name)

    if not is_kg:
        return str(qty)

    q = Decimal(qty or 0).quantize(Decimal("0.001"))
    whole = int(q // 1)
    frac = (q - Decimal(whole)).quantize(Decimal("0.001"))

    frac_map = {
        Decimal("0.500"): "1/2",
        Decimal("0.250"): "1/4",
        Decimal("0.125"): "1/8",
        Decimal("0.000"): "",
    }
    frac_label = frac_map.get(frac)

    if frac_label is None:
        return str(qty)  # fallback si no es exacto

    if frac_label == "":
        return f"{whole} kg"

    if whole > 0:
        return f"{whole} kg {frac_label}"
    return f"{frac_label} kg"    