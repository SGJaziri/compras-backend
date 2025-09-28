from django.utils import timezone
from django.template.loader import render_to_string
from django.http import HttpResponse

from django.db.models.deletion import ProtectedError
from django.db import IntegrityError

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny

from datetime import date as date_cls
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError

from .models import (
    Category, Product, Restaurant, Purchase,
    PurchaseList, PurchaseListItem, Unit
)
from .serializers import (
    CategorySerializer, ProductSerializer, RestaurantSerializer, PurchaseSerializer,
    PurchaseListSerializer, PurchaseListItemSerializer, UnitSerializer,
    ChangePasswordSerializer,
)

# ---------------- Cambio de contraseña ----------------
class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = ChangePasswordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(ser.validated_data['current_password']):
            return Response({"detail": "Contraseña actual incorrecta."}, status=400)
        user.set_password(ser.validated_data['new_password'])
        user.save()
        return Response({"detail": "Contraseña actualizada correctamente."}, status=200)


# ---------------- Scoped mixin (aislar por usuario) ----------------
class OwnedQuerysetMixin:
    """Filtra por owner/created_by = request.user."""
    owner_field = 'owner'  # override donde sea necesario

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if hasattr(self.Meta, "model") and hasattr(self.Meta.model, self.owner_field):
            return qs.filter(**{self.owner_field: user})
        if hasattr(self.Meta, "model") and hasattr(self.Meta.model, 'created_by'):
            return qs.filter(created_by=user)
        return qs.none()

    def perform_create(self, serializer):
        user = self.request.user
        extra = {}
        if hasattr(self.Meta, "model"):
            field_names = [f.name for f in self.Meta.model._meta.fields]
            if 'owner' in field_names:
                extra['owner'] = user
            if 'created_by' in field_names:
                extra['created_by'] = user
        serializer.save(**extra)


class DefaultPerm(permissions.IsAuthenticated):
    """Permiso por defecto para panel/admin."""
    pass


# --------------- Config (autenticado y por usuario) ---------------
class AuthConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        restaurants = Restaurant.objects.filter(owner=user).order_by("name")
        categories  = Category.objects.filter(owner=user).order_by("name")
        products    = Product.objects.select_related("category").filter(owner=user).order_by("name")
        units       = Unit.objects.filter(owner=user).order_by("name")

        return Response({
            "restaurants": RestaurantSerializer(restaurants, many=True).data,
            "categories":  CategorySerializer(categories, many=True).data,
            "products":    ProductSerializer(products, many=True).data,
            "units":       UnitSerializer(units, many=True).data,
        })


class PublicConfigAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        return Response({
            "app": "control-compras",
            "version": "v2.x",
            "pdf": {
                "export_range_json": "/api/purchase-lists/export/range/",
                "export_range_pdf": "/api/purchase-lists/export/range/pdf/"
            }
        }, status=200)

# --------- Catálogo (aislado por usuario) ----------
class CategoryViewSet(OwnedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Category.objects.all().order_by("name")
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]
    class Meta:
        model = Category

class ProductViewSet(OwnedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Product.objects.select_related("category").all().order_by("name")
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]
    class Meta:
        model = Product


class UnitViewSet(viewsets.ModelViewSet):
    queryset = Unit.objects.all().order_by("name")
    serializer_class = UnitSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ProtectedError:
            count_products = Product.objects.filter(default_unit=instance).count()
            count_list_items = PurchaseListItem.objects.filter(unit=instance).count()
            total = count_products + count_list_items
            detail = (
                f"No se puede eliminar. La unidad está en uso por {total} registro(s)"
                f"{' (productos: ' + str(count_products) + ')' if count_products else ''}."
            )
            return Response({"detail": detail}, status=status.HTTP_409_CONFLICT)
        except IntegrityError:
            count_products = Product.objects.filter(default_unit=instance).count()
            count_list_items = PurchaseListItem.objects.filter(unit=instance).count()
            total = count_products + count_list_items
            detail = (
                f"No se puede eliminar por integridad referencial. En uso por {total} registro(s)"
                f"{' (productos: ' + str(count_products) + ')' if count_products else ''}."
            )
            return Response({"detail": detail}, status=status.HTTP_409_CONFLICT)

class RestaurantViewSet(OwnedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Restaurant.objects.all().order_by("name")
    serializer_class = RestaurantSerializer
    permission_classes = [IsAuthenticated]
    class Meta:
        model = Restaurant


# --------------- Compras formales (futuro) ---------------
class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.prefetch_related('items').all()
    serializer_class = PurchaseSerializer
    permission_classes = [DefaultPerm]

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        return Response({'detail': 'PDF no implementado aún'}, status=200)


# ====================== HELPERS ======================
def _csv_to_list(s: str):
    return [x.strip() for x in s.split(",") if x and str(x).strip()]

def _collect_multi(request, *keys: str):
    out = []
    for k in keys:
        out += request.query_params.getlist(k)
        val = request.query_params.get(k)
        if val:
            out += _csv_to_list(val)
    dedup, seen = [], set()
    for v in out:
        s = str(v).strip()
        if s and s not in seen:
            seen.add(s)
            dedup.append(s)
    return dedup


# --------------- Listas (aisladas por usuario) ---------------
class PurchaseListViewSet(viewsets.ModelViewSet):
    serializer_class = PurchaseListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return (PurchaseList.objects
                .filter(created_by=user)
                .prefetch_related('items__product__category', 'items__unit', 'restaurant')
                .order_by('-id'))

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    # ---------- Helpers internos ----------
    def _ensure_complete_prices(self, pl: PurchaseList):
        missing = []
        for it in pl.items.select_related("unit", "product").all():
            if it.unit and not it.unit.is_currency:
                if it.price_soles in (None,):
                    missing.append(it.product.name)
        if missing:
            msg = "Faltan precios en: " + ", ".join(missing[:10])
            raise ValidationError(msg if len(missing) <= 10 else msg + f" y {len(missing)-10} más")

    def _render_pdf_html(self, request, pl: PurchaseList, show_prices: bool = True):
        items_qs = pl.items.select_related("product__category", "unit").all()
        groups_map, grand_total = {}, Decimal("0.00")
        for it in items_qs:
            cat = getattr(getattr(it.product, "category", None), "name", "Sin categoría")
            price = (it.price_soles or Decimal("0"))
            qty   = (it.qty or Decimal("0"))
            raw_subtotal = qty if (getattr(it.unit, "is_currency", False)) else (qty * price)
            subtotal = raw_subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            grand_total += subtotal
            ulabel = (getattr(it.unit, "symbol", None) or getattr(it.unit, "name", "")) or "-"
            line = {
                "product": it.product.name,
                "unit": ulabel,
                "qty": float(qty),
                "price": None if (getattr(it.unit, "is_currency", False) or not show_prices)
                         else float(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "subtotal": float(subtotal),
                "unit_is_currency": bool(getattr(it.unit, "is_currency", False)),
            }
            groups_map.setdefault(cat, []).append(line)

        groups, flat_lines = [], []
        for cat_name in sorted(groups_map.keys(), key=lambda s: (s is None, s)):
            lines = groups_map[cat_name]
            flat_lines.extend(lines)
            group_total_dec = sum(Decimal(str(l["subtotal"])) for l in lines)
            group_total = float(group_total_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            groups.append({"category": cat_name, "lines": lines, "group_total": group_total})

        ctx = {
            "pl": pl,
            "groups": groups,
            "grand_total": format(grand_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f"),
            "lines": flat_lines,
            "total": format(grand_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f"),
            "show_prices": show_prices,
            "observation": (pl.observation or ""),
        }
        return render_to_string("purchase_list.html", ctx)

    def _render_pdf_bytes(self, request, pl: PurchaseList, show_prices: bool = True):
        html = self._render_pdf_html(request, pl, show_prices=show_prices)
        try:
            from weasyprint import HTML
            return HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        except Exception:
            try:
                from xhtml2pdf import pisa
                from io import BytesIO
                buf = BytesIO()
                result = pisa.CreatePDF(html, dest=buf, encoding='utf-8')
                if not result.err:
                    return buf.getvalue()
            except Exception:
                pass
        return None

    # ---------- Acciones ----------
    @action(detail=True, methods=['get', 'post'], url_path='items')
    def items(self, request, pk=None):
        """GET: lista de ítems para el modal. POST: agrega un ítem."""
        pl = self.get_object()

        if request.method.lower() == 'get':
            qs = pl.items.select_related('product__category', 'unit').order_by('id')
            ser = PurchaseListItemSerializer(qs, many=True, context={'request': request})
            return Response(ser.data, status=200)

        if pl.status == "final":
            return Response({"detail": "No se pueden editar listas finalizadas."},
                            status=status.HTTP_400_BAD_REQUEST)

        data = request.data.copy()
        data['purchase_list'] = pl.id
        ser = PurchaseListItemSerializer(data=data, context={'request': request})
        if not ser.is_valid():
            return Response(ser.errors, status=400)
        try:
            obj = ser.save()
        except ValidationError as e:
            return Response({"detail": str(e)}, status=400)
        except Exception as e:
            return Response({"detail": f"No se pudo guardar el ítem: {e}"}, status=400)
        return Response(PurchaseListItemSerializer(obj, context={'request': request}).data, status=201)

    @action(detail=True, methods=['post'], url_path='add_items')
    def add_item(self, request, pk=None):
        pl = self.get_object()
        if pl.status == "final":
            return Response({"detail": "No se pueden editar listas finalizadas."},
                            status=status.HTTP_400_BAD_REQUEST)
        data = request.data.copy()
        data.pop('purchase_list', None)
        ser = PurchaseListItemSerializer(data=data, context={"request": request, "purchase_list": pl})
        if not ser.is_valid():
            return Response(ser.errors, status=400)
        try:
            obj = ser.save(purchase_list=pl)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=400)
        except Exception as e:
            return Response({"detail": f"No se pudo guardar el ítem: {e}"}, status=400)
        return Response(PurchaseListItemSerializer(obj).data, status=201)

    @action(detail=True, methods=['post'], url_path='complete')
    def complete(self, request, pk=None):
        pl = self.get_object()
        if pl.status == "final":
            return Response({"detail": "La lista ya está finalizada."}, status=400)

        items_payload = request.data.get("items", [])
        obs = request.data.get("observation")

        if obs is not None:
            pl.observation = str(obs).strip() or None
            pl.save(update_fields=["observation"])

        updated = 0
        for row in items_payload:
            try:
                iid = int(row.get("id"))
            except Exception:
                continue
            price = row.get("price_soles", None)
            try:
                it = pl.items.get(id=iid)
            except PurchaseListItem.DoesNotExist:
                continue
            if it.unit and it.unit.is_currency:
                pass
            else:
                it.price_soles = Decimal(str(price)) if price not in (None, "") else None
                it.save(update_fields=["price_soles"])
                updated += 1

        try:
            self._ensure_complete_prices(pl)
        except ValidationError:
            return Response({"detail": f"Guardado: {updated} precio(s). Aún faltan precios."}, status=200)

        pl.status = "final"
        pl.finalized_at = timezone.now()
        if not pl.series_code:
            try:
                from .services.serials import next_series_code
                pl.series_code = next_series_code(pl.restaurant)
            except Exception:
                try:
                    from .services import generate_series_code
                    pl.series_code = generate_series_code(pl.restaurant)
                except Exception:
                    pl.series_code = f"{timezone.now().year}-{pl.restaurant.code}-{pl.id:04d}"
        pl.save(update_fields=["status", "finalized_at", "series_code"])

        return Response({"detail": f"Lista completada y finalizada. ({updated} ítems actualizados)",
                         "id": pl.id, "series_code": pl.series_code}, status=200)

    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, pk=None):
        pl = self.get_object()
        hide_param = request.query_params.get("hide_prices", "").lower()
        show_prices = hide_param not in ("1", "true", "yes")
        pdf_bytes = self._render_pdf_bytes(request, pl, show_prices=show_prices)
        if not pdf_bytes:
            return Response({"detail": "No se pudo generar el PDF en este entorno."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        def _series_like(p: PurchaseList) -> str:
            base = p.series_code
            if not base:
                year = timezone.localdate().year
                rcode = getattr(p.restaurant, "code", None) or getattr(p.restaurant, "name", "R")
                base = f"{year}-{rcode}-{p.id:04d}"
            if not show_prices:
                parts = base.split("-")
                base = f"{'-'.join(parts[:-1])}-Sn-{parts[-1]}" if len(parts) >= 3 else f"{base}-Sn"
            return base

        filename = f"{_series_like(pl)}.pdf"
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp['Content-Disposition'] = f'inline; filename="{filename}"'
        return resp


class PurchaseListItemsListApi(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        pl_id = request.query_params.get("purchase_list")
        qs = (PurchaseListItem.objects
              .select_related("purchase_list__restaurant", "product__category", "unit")
              .filter(purchase_list__created_by=request.user))
        if pl_id:
            try:
                qs = qs.filter(purchase_list_id=int(pl_id))
            except Exception:
                return Response({"detail": "purchase_list inválido."}, status=400)
        data = PurchaseListItemSerializer(qs, many=True, context={"request": request}).data
        return Response(data, status=200)
