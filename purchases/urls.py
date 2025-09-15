from rest_framework.routers import DefaultRouter
from .views import (
    CategoryViewSet, ProductViewSet, RestaurantViewSet, UnitViewSet,
    PurchaseViewSet, PurchaseListViewSet, PublicConfigView
)
from django.urls import path, include
from django.contrib import admin


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('core.urls')),   # ← asegura el include correcto
]

router = DefaultRouter()
router.register('categories', CategoryViewSet)
router.register('products', ProductViewSet)
router.register('restaurants', RestaurantViewSet)
router.register('units', UnitViewSet)
router.register('purchases', PurchaseViewSet)
router.register('purchase-lists', PurchaseListViewSet)