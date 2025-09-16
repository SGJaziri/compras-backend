# seed.py
from core.models import Unit, Category, Product, Restaurant

# Unidades básicas
Unit.objects.get_or_create(name="Soles", defaults={"kind": "currency", "symbol": "S/", "is_currency": True})
Unit.objects.get_or_create(name="Kilogramo", defaults={"kind": "mass", "symbol": "kg"})
Unit.objects.get_or_create(name="Gramo", defaults={"kind": "mass", "symbol": "g"})
Unit.objects.get_or_create(name="Unidad", defaults={"kind": "count", "symbol": "uni"})
Unit.objects.get_or_create(name="Paquete", defaults={"kind": "package", "symbol": "paq"})

# Restaurantes de prueba
Restaurant.objects.get_or_create(name="Al Punto", code="ALP")
Restaurant.objects.get_or_create(name="Mil Delicias", code="MIL")
Restaurant.objects.get_or_create(name="Chimu", code="CHI")

print("Datos iniciales creados ✅")
