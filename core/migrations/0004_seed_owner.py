from django.db import migrations
from django.conf import settings
from django.contrib.auth.hashers import make_password

def seed_owner(apps, schema_editor):
    # Obtener el modelo de usuario "histórico" (funciona con auth.User o usuario custom)
    app_label, model_name = settings.AUTH_USER_MODEL.split('.')
    UserModel = apps.get_model(app_label, model_name)

    username = 'josemaria'
    password = '123456'

    # Crear/actualizar usuario con password HASHEADA (sin set_password)
    user, created = UserModel.objects.get_or_create(
        username=username,
        defaults={
            'is_active': True,
            'password': make_password(password),
        }
    )
    if not created:
        # Forzar hash si ya existía con contraseña sin hash o vacía
        user.is_active = True
        user.password = make_password(password)
        try:
            user.save(update_fields=['is_active', 'password'])
        except Exception:
            user.save()

    # Asignar ownership a todo lo existente
    Category       = apps.get_model('core', 'Category')
    Unit           = apps.get_model('core', 'Unit')
    Restaurant     = apps.get_model('core', 'Restaurant')
    Product        = apps.get_model('core', 'Product')
    PurchaseList   = apps.get_model('core', 'PurchaseList')

    Category.objects.filter(owner__isnull=True).update(owner=user)
    Unit.objects.filter(owner__isnull=True).update(owner=user)
    Restaurant.objects.filter(owner__isnull=True).update(owner=user)
    Product.objects.filter(owner__isnull=True).update(owner=user)
    PurchaseList.objects.filter(created_by__isnull=True).update(created_by=user)

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_category_owner_product_owner_restaurant_owner_and_more'),  # tu migración previa
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),  # <-- importante
    ]

    operations = [
        migrations.RunPython(seed_owner, migrations.RunPython.noop),
    ]
