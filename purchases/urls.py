# purchases/urls.py
from django.contrib import admin
from django.urls import path, include, re_path
from rest_framework.routers import DefaultRouter

from core.views import (
    PublicConfigView,
    CategoryViewSet, ProductViewSet, UnitViewSet, RestaurantViewSet,
    PurchaseViewSet, PurchaseListViewSet,
)

# Router DRF (usa slash final por defecto)
router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'units', UnitViewSet, basename='unit')
router.register(r'restaurants', RestaurantViewSet, basename='restaurant')
router.register(r'purchases', PurchaseViewSet, basename='purchase')
router.register(r'purchase-lists', PurchaseListViewSet, basename='purchase-list')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/public/config/', PublicConfigView.as_view(), name='public-config'),
    path('api/', include(router.urls)),
]

# ------- Opcional: aceptar endpoints sin barra final y redirigir -------
from django.views.generic import RedirectView

urlpatterns += [
    # /api/purchase-lists/export/range   →   /api/purchase-lists/export/range/
    re_path(
        r'^api/purchase-lists/export/range$',
        RedirectView.as_view(url='/api/purchase-lists/export/range/', permanent=True)
    ),
    # /api/purchase-lists/export/by-date →   /api/purchase-lists/export/by-date/
    re_path(
        r'^api/purchase-lists/export/by-date$',
        RedirectView.as_view(url='/api/purchase-lists/export/by-date/', permanent=True)
    ),
]
