# core/services.py
from django.db import transaction
from django.utils import timezone

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