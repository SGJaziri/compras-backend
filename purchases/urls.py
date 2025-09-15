from rest_framework.routers import DefaultRouter
from .views import (
    CategoryViewSet, ProductViewSet, RestaurantViewSet, UnitViewSet,
    PurchaseViewSet, PurchaseListViewSet, PublicConfigView
)
from django.urls import path

router = DefaultRouter()
router.register('categories', CategoryViewSet)
router.register('products', ProductViewSet)
router.register('restaurants', RestaurantViewSet)
router.register('units', UnitViewSet)
router.register('purchases', PurchaseViewSet)
router.register('purchase-lists', PurchaseListViewSet)

urlpatterns = router.urls + [
    path('public/config/', PublicConfigView.as_view(), name='public-config'),
]
