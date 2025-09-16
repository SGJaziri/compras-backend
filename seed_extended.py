# seed_extended.py
from core.models import Category, Product, Unit

# Categorías
verduras, _ = Category.objects.get_or_create(name="Verduras")
pescados, _ = Category.objects.get_or_create(name="Pescados")
abarrotes, _ = Category.objects.get_or_create(name="Abarrotes")

# Unidades
kg = Unit.objects.get(name="Kilogramo")
uni = Unit.objects.get(name="Unidad")
soles = Unit.objects.get(name="Soles")

# Productos
Product.objects.get_or_create(
    name="Ají limo", category=verduras,
    defaults={"default_unit": soles}
)
Product.objects.get_or_create(
    name="Cebolla", category=verduras,
    defaults={"default_unit": kg}
)
Product.objects.get_or_create(
    name="Camotillo", category=pescados,
    defaults={"default_unit": kg}
)
Product.objects.get_or_create(
    name="Caballa", category=pescados,
    defaults={"default_unit": kg}
)
Product.objects.get_or_create(
    name="Azúcar", category=abarrotes,
    defaults={"default_unit": kg}
)

print("Categorías y productos iniciales creados ✅")
