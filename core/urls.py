# core/urls.py
from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token

from .views import (
    ChangePasswordView,
    AuthConfigView,
    PublicConfigAPIView,
    CategoryViewSet, ProductViewSet, RestaurantViewSet, UnitViewSet,
    PurchaseViewSet, PurchaseListViewSet,
)

# DRF Router (CRUDs)
router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'units', UnitViewSet, basename='unit')
router.register(r'restaurants', RestaurantViewSet, basename='restaurant')
router.register(r'purchases', PurchaseViewSet, basename='purchase')
router.register(r'purchase-lists', PurchaseListViewSet, basename='purchase-list')

urlpatterns = [
    # --- Auth ---
    path('auth/login/', obtain_auth_token, name='api_token_auth'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='change_password'),

    # --- Config autenticada (catálogo del usuario) ---
    path('config/', AuthConfigView.as_view(), name='auth_config'),

    # --- Config pública (sin autenticación) ---
    # Quedará como /api/public/config/ cuando incluyas core.urls bajo el prefijo /api/
    path('public/config/', PublicConfigAPIView.as_view(), name='public_config'),
]

# Endpoints del router (CRUDs)
urlpatterns += router.urls
