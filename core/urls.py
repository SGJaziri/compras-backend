from rest_framework.routers import DefaultRouter
from .views import CategoryViewSet, ProductViewSet, RestaurantViewSet, PurchaseViewSet

router = DefaultRouter()
router.register('categories', CategoryViewSet)
router.register('products', ProductViewSet)
router.register('restaurants', RestaurantViewSet)
router.register('purchases', PurchaseViewSet)
urlpatterns = router.urls