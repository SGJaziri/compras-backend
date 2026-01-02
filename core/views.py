import logging
logger = logging.getLogger(__name__)

from django.utils import timezone
from django.template.loader import render_to_string
from django.http import HttpResponse

from django.db.models import Max
from django.db.models.deletion import ProtectedError
from django.db import IntegrityError

from rest_framework import viewsets, permissions, status, renderers
from rest_framework.negotiation import BaseContentNegotiation
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny

from datetime import date as date_cls
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError

from rest_framework.exceptions import PermissionDenied

from .models import (
    Category, Product, Restaurant, Purchase,
    PurchaseList, PurchaseListItem, Unit
)
from .serializers import (
    CategorySerializer, ProductSerializer, RestaurantSerializer, PurchaseSerializer,
    PurchaseListSerializer, PurchaseListItemSerializer, UnitSerializer,
    ChangePasswordSerializer, PurchaseListItemPatchSerializer
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
        # Si el modelo tiene 'owner', filtra por ahí
        if hasattr(self.Meta, "model") and hasattr(self.Meta.model, self.owner_field):
            return qs.filter(**{self.owner_field: user})
        # Si no, probar con 'created_by'
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


# ---------------- Permisos base ----------------
class DefaultPerm(permissions.IsAuthenticated):
    """Permiso por defecto para panel/admin."""
    pass


# --------------- Config (autenticado y por usuario) ---------------
class AuthConfigView(APIView):
    """
    Config/ catálogo del usuario autenticado.
    """
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
    """
    Config pública (sin autenticación) usada por el módulo de reportes/PDF.
    NO devuelve datos de usuario, sólo endpoints/base flags.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        return Response({
            "app": "control-compras",
            "version": "v2.x",
            "pdf": {
                # JSON y PDF que tu frontend usa (con slash final)
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


class UnitViewSet(OwnedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Unit.objects.all().order_by("name")
    serializer_class = UnitSerializer
    permission_classes = [IsAuthenticated]
    class Meta:
        model = Unit

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ProtectedError:
            # Cuenta usos típicos de Unit
            count_products = Product.objects.filter(default_unit=instance).count()
            count_list_items = PurchaseListItem.objects.filter(unit=instance).count()
            total = count_products + count_list_items
            detail = (
                f"No se puede eliminar. La unidad está en uso por {total} registro(s)"
                f"{' (productos: ' + str(count_products) + ')' if count_products else ''}."
            )
            return Response({"detail": detail}, status=status.HTTP_409_CONFLICT)
        except IntegrityError:
            # Si el FK quedó con NO ACTION en la BD, cae aquí
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

    def _is_kg_unit(self, unit) -> bool:
        if not unit:
            return False
        name = (getattr(unit, "name", "") or "").strip().lower()
        symbol = (getattr(unit, "symbol", "") or "").strip().lower()
        # acepta "kg", "kilogramo", etc.
        return symbol == "kg" or "kg" in name or "kilogram" in name

    def _fmt_qty_human(self, qty: Decimal, is_kg: bool) -> str:
        if qty is None:
            return ""
        if not is_kg:
            # normal: 3 decimales como string
            q = qty.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
            return str(q)

        # KG: convertir 2.500 -> "2,5" (o si quieres "2 1/2", lo ajustamos luego)
        q = qty.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        s = format(q, "f").rstrip("0").rstrip(".")
        return s.replace(".", ",")


# ====================== NUEVOS HELPERS PARA FILTROS ======================

def _ensure_list_editable(pl):
    if pl.status == "final":
        raise PermissionDenied("La lista está cerrada y no puede modificarse.")

def _is_valid_price(p):
    try:
        p = Decimal(str(p))
    except Exception:
        return False
    return p > 0

def _autolock_if_all_priced(pl):
    # Si NO hay items, no bloquea
    items = pl.items.all()
    if not items.exists():
        return False

    all_priced = True
    for it in items:
        if not _is_valid_price(it.price_soles   ):
            all_priced = False
            break

    if all_priced and pl.status != "final":
        pl.status = "final"
        pl.locked_at = timezone.now()  # si ya existe en tu modelo; si no, lo omitimos
        # Si locked_at no existe, comenta esa línea o ajustamos luego.
        pl.save(update_fields=[f for f in ["status", "locked_at"] if hasattr(pl, f)])
        return True

    return False

def _csv_to_list(s: str):
    return [x.strip() for x in s.split(",") if x and str(x).strip()]

def _collect_multi(request, *keys: str):
    """
    Lee valores de múltiples nombres de parámetro.
    - Soporta ?k=1,2 y ?k=1&k=2
    - Devuelve lista de strings única (sin vacíos)
    """
    out = []
    for k in keys:
        out += request.query_params.getlist(k)  # repetidos: ?k=1&k=2
        val = request.query_params.get(k)       # CSV: ?k=1,2
        if val:
            out += _csv_to_list(val)
    # normalizar
    dedup = []
    seen = set()
    for v in out:
        s = str(v).strip()
        if s and s not in seen:
            seen.add(s)
            dedup.append(s)
    return dedup
# ====================== HELPERS DISPLAY (KG HUMANO) ======================
def _norm_unit_name(u: Unit) -> str:
    s = ((getattr(u, "symbol", None) or "") + " " + (getattr(u, "name", None) or "")).strip()
    s = s.lower()
    # sin tildes
    s = (s.replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u"))
    return " ".join(s.split())

def _is_kg_unit(u: Unit) -> bool:
    if not u:
        return False
    n = _norm_unit_name(u)
    return (n == "kg") or (" kg " in f" {n} ") or ("kilogram" in n) or ("kilo" == n) or ("kilos" in n)

def _fmt_qty_human(qty: Decimal) -> str:
    """
    Muestra sin ceros sobrantes, con hasta 3 decimales.
    Ej: 5.000 -> '5', 0.125 -> '0.125'
    """
    if qty is None:
        return "0"
    q = qty.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    s = format(q, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"

def _fmt_kg_human(qty: Decimal) -> str:
    """
    Convierte 5.25 -> '5 1/4', 0.125 -> '1/8', 2.5 -> '2 1/2'
    Mantiene fallback si no calza exacto.
    """
    if qty is None:
        return "0"
    q = qty.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    whole = int(q // 1)
    frac = (q - Decimal(whole)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    frac_map = {
        Decimal("0.500"): "1/2",
        Decimal("0.250"): "1/4",
        Decimal("0.125"): "1/8",
        Decimal("0.000"): "",
    }
    frac_label = frac_map.get(frac)

    # si no calza exacto a 0.125/0.25/0.5, fallback
    if frac_label is None:
        return _fmt_qty_human(q)

    if whole == 0 and frac_label:
        return frac_label
    if whole != 0 and frac_label:
        return f"{whole} {frac_label}"
    return str(whole)
# ========================================================================
# core/views.py
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import PurchaseListItem
from .serializers import PurchaseListItemSerializer, PurchaseListItemPatchSerializer

from rest_framework.exceptions import PermissionDenied

class PurchaseListItemViewSet(viewsets.ModelViewSet):
    queryset = PurchaseListItem.objects.select_related(
        "product__category", "unit", "purchase_list"
    )
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()

        # ✅ aislamiento por usuario (ajusta el campo si tu modelo usa otro nombre)
        qs = qs.filter(purchase_list__created_by=self.request.user)

        pl = self.request.query_params.get("purchase_list")
        if pl:
            qs = qs.filter(purchase_list_id=pl)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pl = serializer.validated_data["purchase_list"]
        if pl.created_by_id != request.user.id:
            raise PermissionDenied("No tienes permiso para modificar esta lista.")
        self._ensure_open(pl)

        self.perform_create(serializer)

        full = PurchaseListItemSerializer(
            serializer.instance,
            context=self.get_serializer_context()
        )
        return Response(full.data, status=201)

    def get_serializer_class(self):
        if self.action == 'create':
            return PurchaseListItemCreateSerializer
        if self.action in ('update', 'partial_update'):
            return PurchaseListItemPatchSerializer
        return PurchaseListItemSerializer

    def _ensure_editable(self, pl):
        if pl.status == "final":
            raise PermissionDenied("La lista está cerrada y no puede modificarse.")

    def _ensure_open(self, pl):
        if pl.status == 'final':
            raise PermissionDenied("La lista está cerrada y no puede modificarse.")

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        instance = self.get_object()
        pl = instance.purchase_list

        # ✅ bloqueo si ya está final
        self._ensure_editable(pl)

        # 1) actualizar el ítem con el serializer de PATCH
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        # 2) auto-cierre si ya todos tienen precio válido (>0) en ítems NO monetarios
        if pl.status != "final":
            items = pl.items.filter(unit__is_currency=False)

            falta = False
            for it in items:
                try:
                    v = Decimal(str(it.price_soles)) if it.price_soles is not None else None
                    if v is None or v <= 0:
                        falta = True
                        break
                except Exception:
                    falta = True
                    break

            if not falta:
                # también validar <= 0 (por si guardan 0)
                for it in pl.items.filter(unit__is_currency=False):
                    try:
                        if it.price_soles is None or Decimal(str(it.price_soles)) <= 0:
                            falta = True
                            break
                    except Exception:
                        falta = True
                        break

            if not falta:
                # asignar serie si falta
                if not pl.series_code:
                    rest_code = (pl.restaurant.code or "SIN").upper() if pl.restaurant else "SIN"
                    year = pl.created_at.year if pl.created_at else timezone.now().year
                    prefix = f"{year}-{rest_code}-"
                    last = (
                        PurchaseList.objects.filter(series_code__startswith=prefix)
                        .aggregate(m=Max("series_code"))["m"]
                    )
                    if last:
                        try:
                            last_n = int(last.rsplit("-", 1)[-1])
                        except Exception:
                            last_n = 0
                    else:
                        last_n = 0
                    pl.series_code = f"{prefix}{last_n + 1:04d}"

                pl.status = "final"
                pl.finalized_at = timezone.now()
                pl.save(update_fields=["series_code", "status", "finalized_at"])

        # 3) responder con el serializer completo
        full = PurchaseListItemSerializer(instance, context=self.get_serializer_context())
        return Response(full.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        pl = instance.purchase_list

        # ✅ bloqueo si ya está final
        self._ensure_editable(pl)

        return super().destroy(request, *args, **kwargs)

class PDFRenderer(renderers.BaseRenderer):
    media_type = "application/pdf"
    format = "pdf"
    charset = None
    render_style = "binary"
    def render(self, data, accepted_media_type=None, renderer_context=None):
        # Normalmente devolvemos HttpResponse con bytes PDF;
        # DRF no usa esto, pero su presencia satisface la negociación.
        return data

class PassthroughNegotiation(BaseContentNegotiation):
    """
    Ignora el header Accept del cliente y usa el primer renderer declarado.
    Equivalente práctico a IgnoreClientContentNegotiation para esta acción.
    """
    def select_renderer(self, request, renderers, format_suffix=None):
        renderer = renderers[0]
        return (renderer, renderer.media_type)

# --------------- Listas (aisladas por usuario) ---------------
class PurchaseListViewSet(viewsets.ModelViewSet):
    queryset = PurchaseList.objects.all()
    serializer_class = PurchaseListSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        """Crea lista; si hay una lista *draft* vacía reciente para el mismo restaurante, la reutiliza."""
        user = request.user
        rest_id = request.data.get("restaurant")
        try:
            rest_id_int = int(rest_id)
        except Exception:
            rest_id_int = None
        if rest_id_int:
            from django.utils import timezone
            from datetime import timedelta
            now = timezone.now()
            qs = (PurchaseList.objects
                  .filter(created_by=user, restaurant_id=rest_id_int, status='draft')
                  .order_by('-id'))
            for existing in qs[:5]:
                # sin items y creada hace <= 2 minutos
                if existing.items.count() == 0 and (now - existing.created_at) <= timedelta(minutes=2):
                    ser = self.get_serializer(existing)
                    return Response(ser.data, status=200)
        return super().create(request, *args, **kwargs)

    def _ensure_series_code(self, pl: PurchaseList):
        """Asigna series_code si está vacío."""
        if pl.series_code:
            return
        prefix = (pl.restaurant.code or (pl.restaurant.name or "SIN")[:3]).upper()
        # EJ: 2025-ALP-0069  (a partir del id)
        pl.series_code = f"{timezone.now().date().year}-{prefix}-{pl.id:04d}"

    @action(detail=True, methods=["delete"], url_path=r"items/(?P<item_id>\d+)")
    def delete_item(self, request, pk=None, item_id=None):
        pl = self.get_object()

        # Ajusta este check a tu lógica real (status/locked/etc.)
        if getattr(pl, "status", "") == "final":
            return Response({"detail": "No se pueden editar listas finalizadas."}, status=400)

        try:
            it = pl.items.get(id=int(item_id))  # si tu related_name es distinto, lo ajustamos
        except Exception:
            return Response({"detail": "Ítem no encontrado."}, status=404)

        it.delete()
        return Response(status=204)    

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        pl = self.get_object()

        if pl.created_by_id != request.user.id:
            return Response({'detail': 'No permitido'}, status=status.HTTP_403_FORBIDDEN)
        if pl.status == 'final':
            return Response({'ok': True, 'status': 'final'}, status=status.HTTP_200_OK)

        items = pl.items.select_related('unit').all()
        if not items.exists():
            return Response({'detail': 'La lista no tiene ítems.'}, status=status.HTTP_400_BAD_REQUEST)

        faltantes = [it.id for it in items
                    if not getattr(it.unit, 'is_currency', False) and it.price_soles is None]
        if faltantes:
            return Response({'detail': 'Hay ítems sin precio.', 'missing_item_ids': faltantes},
                            status=status.HTTP_400_BAD_REQUEST)

        # ── NUEVO: auto-series si falta ───────────────────────────────────────────
        def _ensure_series_code(pl_obj):
            if pl_obj.series_code:
                return
            # código de restaurante; ajusta el atributo si tu modelo usa otro nombre
            rest_code = (pl_obj.restaurant.code or 'SIN').upper() if pl_obj.restaurant else 'SIN'
            year = pl_obj.created_at.year if pl_obj.created_at else timezone.now().year
            prefix = f"{year}-{rest_code}-"
            # Busca el máximo existente con ese prefijo y suma 1
            last = (PurchaseList.objects
                    .filter(series_code__startswith=prefix)
                    .aggregate(m=Max('series_code'))['m'])
            if last:
                # último segmento numérico
                try:
                    last_n = int(last.rsplit('-', 1)[-1])
                except Exception:
                    last_n = 0
            else:
                last_n = 0
            pl_obj.series_code = f"{prefix}{last_n + 1:04d}"

        _ensure_series_code(pl)

        pl.status = 'final'
        pl.finalized_at = timezone.now()
        pl.save(update_fields=['status', 'finalized_at', 'series_code'])

        return Response({'ok': True, 'status': pl.status, 'series_code': pl.series_code},
                        status=status.HTTP_200_OK)

    """
    Requiere autenticación.
    El queryset siempre se filtra por created_by=request.user.
    """
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

    # ---------- Helpers internos (NO @action) ----------
    def _ensure_complete_prices(self, pl: PurchaseList):
        """Verifica que todos los ítems no monetarios tengan price_soles."""
        missing = []
        for it in pl.items.select_related("unit", "product").all():
            if it.unit and not it.unit.is_currency:
                if it.price_soles in (None,):
                    missing.append(it.product.name)
        if missing:
            msg = "Faltan precios en: " + ", ".join(missing[:10])
            raise ValidationError(msg if len(missing) <= 10 else msg + f" y {len(missing)-10} más")

    def _render_pdf_html(self, request, pl: PurchaseList, show_prices: bool = True, category_ids=None, category_names=None):
        """Construye el HTML del PDF agrupando por categoría con display humano para KG."""
        items_qs = pl.items.select_related("product__category", "unit").all()

        # Filtrar por categorías si se enviaron
        if category_ids:
            try:
                ids = [int(x) for x in category_ids if str(x).strip().isdigit()]
            except Exception:
                ids = []
            if ids:
                items_qs = items_qs.filter(product__category_id__in=ids)

        if category_names:
            names = [str(x).strip() for x in category_names if str(x).strip()]
            if names:
                items_qs = items_qs.filter(product__category__name__in=names)

        groups_map = {}  # {category_name: [line, ...]}
        grand_total = Decimal("0.00")

        for it in items_qs:
            cat = getattr(getattr(it.product, "category", None), "name", "Sin categoría")

            qty = Decimal(str(getattr(it, "qty", None) or "0"))
            price = (it.price_soles or Decimal("0"))

            is_curr = bool(getattr(it.unit, "is_currency", False)) if it.unit else False
            ulabel = (getattr(it.unit, "symbol", None) or getattr(it.unit, "name", "")) if it.unit else "-"
            ulabel = ulabel or "-"

            # display humano:
            if it.unit and _is_kg_unit(it.unit):
                qty_display = _fmt_kg_human(qty)   # 2.5 => "2 1/2"
            else:
                qty_display = _fmt_qty_human(qty)  # 5.000 => "5"

            raw_subtotal = qty if is_curr else (qty * price)
            subtotal = raw_subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            grand_total += subtotal

            line = {
                "product": it.product.name,
                "unit": ulabel,
                "qty": float(qty),                  # numérico (cálculos)
                "qty_display": qty_display,         # texto (mostrar)
                "price": None if (is_curr or not show_prices) else float(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "subtotal": float(subtotal),
                "unit_is_currency": is_curr,
            }

            groups_map.setdefault(cat, []).append(line)

        # construir groups ordenados
        groups = []
        for cat_name in sorted(groups_map.keys(), key=lambda s: (s is None, s)):
            lines = groups_map[cat_name]
            group_total_dec = sum(Decimal(str(l["subtotal"])) for l in lines)
            group_total = float(group_total_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            groups.append({"category": cat_name, "lines": lines, "group_total": group_total})

        ctx = {
            "pl": pl,
            "groups": groups,
            "grand_total": format(grand_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f"),
            "show_prices": show_prices,
            "observation": (pl.observation or ""),
        }
        return render_to_string("purchase_list.html", ctx)

    def _render_pdf_bytes(
        self,
        request,
        pl: PurchaseList,
        show_prices: bool = True,
        category_ids=None,
        category_names=None,
    ):
        html = self._render_pdf_html(
            request,
            pl,
            show_prices=show_prices,
            category_ids=category_ids,
            category_names=category_names,
        )

        from xhtml2pdf import pisa
        from io import BytesIO

        buf = BytesIO()
        result = pisa.CreatePDF(
            src=html,
            dest=buf,
            encoding="utf-8"
        )

        if result.err:
            # logging opcional
            print("[PDF Error] xhtml2pdf failed in _render_pdf_bytes", flush=True)
            return None  # 👈 importante: no devolver PDF dummy

        return buf.getvalue()


    def _next_series_code(self, restaurant):
        # Usa code si existe; si no, deriva 3 letras del nombre; si no, GEN
        base = (getattr(restaurant, "code", None) or getattr(restaurant, "name", None) or "GEN").strip()
        code = "".join(ch for ch in base.upper() if ch.isalnum())[:3] or "GEN"

        today = timezone.localdate()
        prefix = f"{today.strftime('%Y%m')}-{code}-"   # p. ej. 202510-ALP-

        last = (
            PurchaseList.objects
            .filter(restaurant=restaurant, series_code__startswith=prefix)
            .order_by("series_code")
            .last()
        )
        last_n = 0
        if last and last.series_code:
            try:
                last_n = int(str(last.series_code).rsplit("-", 1)[-1])
            except Exception:
                last_n = 0

        return f"{prefix}{last_n + 1:04d}"

    # ---------- Acciones ----------
    @action(detail=True, methods=['post'], url_path='finalize')
    def finalize(self, request, pk=None):
        pl = self.get_object()

        if not pl.series_code:
            pl.series_code = self._next_series_code(pl.restaurant)

        pl.status = "final"
        pl.finalized_at = timezone.now()
        pl.save(update_fields=["series_code", "status", "finalized_at", "updated_at"])

        ser = PurchaseListSerializer(pl, context={"request": request})
        return Response(ser.data)

    @action(detail=True, methods=['get'], url_path='items')
    def list_items(self, request, pk=None):
        """Listar ítems de la lista (para completar precios)."""
        pl = self.get_object()  # ya scoping por usuario
        qs = pl.items.select_related('product__category', 'unit').all()
        data = PurchaseListItemSerializer(qs, many=True, context={'request': request}).data
        return Response(data)


    @action(detail=True, methods=['post'], url_path='items')
    def add_item(self, request, pk=None):
        """Agregar ítem a la lista (builder)."""
        pl = self.get_object()
        if pl.status == "final":
            return Response({"detail": "No se pueden editar listas finalizadas."},
                            status=status.HTTP_400_BAD_REQUEST)

        data = request.data.copy()
        # No confíes en purchase_list del body
        data.pop('purchase_list', None)

        # ⬇⬇⬇ **cambio clave**: pasamos request y la instancia de la lista en el contexto
        ser = PurchaseListItemSerializer(
            data=data,
            context={"request": request, "purchase_list": pl}
        )

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
        """
        Completa una lista en borrador: actualiza precios de ítems y guarda una observación.
        Si después de actualizar todo queda completo, finaliza automáticamente.
        """
        pl = self.get_object()
        if pl.status == "final":
            return Response({"detail": "La lista ya está finalizada."}, status=400)

        items_payload = request.data.get("items", [])
        obs = request.data.get("observation")

        # Observación
        if obs is not None:
            pl.observation = str(obs).strip() or None
            pl.save(update_fields=["observation"])

        # Actualizar precios
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
                # qty representa el importe; no modifica price_soles
                pass
            else:
                it.price_soles = Decimal(str(price)) if price not in (None, "") else None
                it.save(update_fields=["price_soles"])
                updated += 1

        # Finalizar si está completo
        try:
            self._ensure_complete_prices(pl)
        except ValidationError:
            return Response({"detail": f"Guardado: {updated} precio(s). Aún faltan precios."}, status=200)

        pl.status = "final"
        pl.finalized_at = timezone.now()
        if not pl.series_code:
            pl.series_code = self._next_series_code(pl.restaurant)

        pl.save(update_fields=["status", "finalized_at", "series_code"])
        return Response(
            {"detail": f"Lista completada y finalizada. ({updated} ítems actualizados)",
             "id": pl.id, "series_code": pl.series_code},
            status=200
        )

    # ---------- PDF por lista ----------
    @action(
    detail=True,
    methods=["get"],
    url_path="pdf",
    renderer_classes=[PDFRenderer],
    content_negotiation_class=PassthroughNegotiation,
)
    def pdf(self, request, pk=None):
        pl = self.get_object()

        # --- asegurar series_code si está final ---
        if pl.status == "final" and not pl.series_code:
            rest_code = (pl.restaurant.code or "SIN").upper() if pl.restaurant else "SIN"
            year = pl.created_at.year if pl.created_at else timezone.now().year
            prefix = f"{year}-{rest_code}-"
            last = (
                PurchaseList.objects.filter(series_code__startswith=prefix)
                .aggregate(m=Max("series_code"))["m"]
            )
            if last:
                try:
                    last_n = int(last.rsplit("-", 1)[-1])
                except Exception:
                    last_n = 0
            else:
                last_n = 0

            pl.series_code = f"{prefix}{last_n + 1:04d}"
            pl.save(update_fields=["series_code", "updated_at"])

        # --- show/hide prices ---
        hide_param = (request.query_params.get("hide_prices") or "").strip().lower()
        show_prices = hide_param not in ("1", "true", "yes")

        # --- filtros de categoría ---
        cat_ids = request.query_params.get("category_ids") or request.query_params.get("categories") or ""
        cat_names = request.query_params.get("category_names") or ""
        cat_ids = [x.strip() for x in str(cat_ids).split(",") if x.strip()]
        cat_names = [x.strip() for x in str(cat_names).split(",") if x.strip()]

        # --- render PDF bytes ---
        try:
            pdf_bytes = self._render_pdf_bytes(
                request,
                pl,
                show_prices=show_prices,
                category_ids=cat_ids or None,
                category_names=cat_names or None,
            )
        except Exception as e:
            logger.exception("Error en _render_pdf_bytes (PurchaseList.pdf) pl_id=%s: %s", pl.pk, e)
            pdf_bytes = None

        # ✅ Mantén dummy SOLO para este endpoint si lo necesitas por el 406/renderer.
        #    Pero deja un mensaje claro en logs si ocurre.
        if not pdf_bytes:
            logger.error("PDF vacío o fallido, devolviendo dummy PDF (PurchaseList.pdf) pl_id=%s", pl.pk)
            pdf_bytes = b"%PDF-1.4\n%"

        # --- nombre seguro ---
        serie = pl.series_code or f"lista-{pl.pk}"
        safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in f"{serie}.pdf")

        # --- respuesta (descarga directa) ---
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{safe_name}"'
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "no-store"
        resp["Content-Length"] = str(len(pdf_bytes))
        return resp


    # ---------- Índice por fecha (1 PDF por restaurante) ----------
    @action(detail=False, methods=['get'], url_path='export/by-date')
    def export_by_date(self, request):
        try:
            date_str = request.query_params.get("date")
            if date_str:
                d = date_cls.fromisoformat(date_str)
            else:
                d = timezone.localdate()
        except ValueError:
            return Response({"detail": "Formato de fecha inválido. Use YYYY-MM-DD."}, status=400)

        only_final = request.query_params.get("only_final", "true").lower() != "false"

        qs = (PurchaseList.objects
              .select_related("restaurant")
              .prefetch_related("items__product__category", "items__unit")
              .filter(created_by=request.user, created_at__date=d))
        if only_final:
            qs = qs.filter(status="final")

        if not qs.exists():
            return Response([], status=200)

        # Tomamos la lista más reciente por restaurante (si hay varias)
        latest_by_rest = {}
        for pl in qs.order_by("restaurant__name", "id"):
            rid = pl.restaurant_id
            if rid not in latest_by_rest or pl.id > latest_by_rest[rid].id:
                latest_by_rest[rid] = pl

        rows = []
        base = request.build_absolute_uri("/")[:-1]  # quita la última '/'
        for rid, pl in latest_by_rest.items():
            rows.append({
                "restaurant_id": rid,
                "restaurant_name": pl.restaurant.name,
                "list_id": pl.id,
                "series_code": pl.series_code,
                "status": pl.status,
                "created_at": pl.created_at,
                "pdf_url": f"{base}/api/purchase-lists/{pl.id}/pdf/",
            })

        rows.sort(key=lambda r: r["restaurant_name"] or "")
        return Response(rows, status=200)

    def _build_range_payload(self, sdate, edate, only_final=True, mode="detail", *, filters=None):
        qs = PurchaseListItem.objects.select_related(
            "purchase_list",
            "purchase_list__restaurant",
            "product",
            "product__category",
            "unit",
        )

        qs = qs.filter(
            purchase_list__created_at__date__gte=sdate,
            purchase_list__created_at__date__lte=edate,
        )

        if only_final:
            qs = qs.filter(purchase_list__status="final")

        if filters:
            if filters.get("restaurant_ids"):
                qs = qs.filter(purchase_list__restaurant_id__in=filters["restaurant_ids"])
            if filters.get("category_ids"):
                qs = qs.filter(product__category_id__in=filters["category_ids"])
            if filters.get("product_ids"):
                qs = qs.filter(product_id__in=filters["product_ids"])

        rest_map = {}
        date_map = defaultdict(lambda: {"lists": set(), "total": Decimal("0.00")})
        grand_total = Decimal("0.00")

        for it in qs:
            rest = it.purchase_list.restaurant.name if it.purchase_list.restaurant else "Sin restaurante"
            cat = it.product.category.name if it.product.category else "Sin categoría"

            qty = Decimal(str(it.qty or 0))
            price = it.price_soles or Decimal("0")

            is_curr = bool(getattr(it.unit, "is_currency", False)) if it.unit else False
            ulabel = (getattr(it.unit, "symbol", None) or getattr(it.unit, "name", "")) if it.unit else "-"
            ulabel = ulabel or "-"

            raw_subtotal = qty if is_curr else qty * price
            subtotal = raw_subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            r = rest_map.setdefault(rest, {"categories": {}, "total": Decimal("0.00")})
            c = r["categories"].setdefault(cat, {"lines": [], "total": Decimal("0.00")})

            if mode == "detail":
                if it.unit and _is_kg_unit(it.unit):
                    qty_display = _fmt_kg_human(qty)
                else:
                    qty_display = _fmt_qty_human(qty)

                c["lines"].append({
                    "date": it.purchase_list.created_at.date().isoformat(),
                    "product": it.product.name,
                    "unit": ulabel,
                    "qty": float(qty),
                    "qty_display": qty_display,
                    "price": None if is_curr else float(price),
                    "subtotal": float(subtotal),
                    "unit_is_currency": bool(getattr(it.unit, "is_currency", False)),
                })

            c["total"] += subtotal
            r["total"] += subtotal
            grand_total += subtotal

            d = it.purchase_list.created_at.date().isoformat()
            date_map[d]["lists"].add(it.purchase_list_id)
            date_map[d]["total"] += subtotal

        payload = {
            "restaurants": [],
            "dates": [],
            "grand_total": float(grand_total),
        }

        for rest_name, rdata in rest_map.items():
            cats = []
            for cname, cdata in rdata["categories"].items():
                cats.append({
                    "category": cname,
                    "lines": cdata["lines"] if mode == "detail" else None,
                    "total": float(cdata["total"]),
                })
            payload["restaurants"].append({
                "restaurant": rest_name,
                "categories": cats,
                "total": float(rdata["total"]),
            })

        for d, v in sorted(date_map.items()):
            payload["dates"].append({
                "date": d,
                "lists": len(v["lists"]),
                "total": float(v["total"]),
            })

        return payload


    @action(detail=False, methods=['get'], url_path='export/range')
    def export_range(self, request):
        """
        Devuelve JSON del rango (solo del usuario).
        Query: start, end, only_final=true|false, mode=detail|summary (detail por defecto)
        + filtros opcionales: category_id(s)/category_ids/categories/category_names,
                              product_id(s)/product_ids/products/product_names
        """
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        only_final = request.query_params.get("only_final", "true").lower() != "false"
        mode = request.query_params.get("mode", "detail").lower()
        if mode not in ("detail", "summary"):
            mode = "detail"

        if not start or not end:
            return Response({"detail": "Parámetros 'start' y 'end' son requeridos (YYYY-MM-DD)."}, status=400)
        try:
            sdate = date_cls.fromisoformat(start)
            edate = date_cls.fromisoformat(end)
        except ValueError:
            return Response({"detail": "Fechas inválidas. Use YYYY-MM-DD."}, status=400)
        if sdate > edate:
            sdate, edate = edate, sdate

        # --- filtros opcionales ---
        filters = {
            "category_ids": _collect_multi(request, "category_id", "category_ids", "categories", "category_ids[]"),
            "category_names": _collect_multi(request, "category_names", "categories_names", "category", "category[]"),
            "product_ids": _collect_multi(request, "product_id", "product_ids", "products", "product_ids[]"),
            "product_names": _collect_multi(request, "product_names", "products_names", "product", "product[]"),
        }

        payload = self._build_range_payload(sdate, edate, only_final, mode, filters=filters)
        return Response(payload, status=200)

    @action(detail=False, methods=['get'], url_path='export/range/pdf')
    def export_range_pdf(self, request):
        """
        PDF del rango (solo del usuario).
        Query: start, end, only_final=true|false, mode=detail|summary
        + filtros opcionales (mismos alias que export_range)
        """
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        only_final = request.query_params.get("only_final", "true").lower() != "false"
        mode = request.query_params.get("mode", "detail").lower()
        if mode not in ("detail", "summary"):
            mode = "detail"

        if not start or not end:
            return Response(
                {"detail": "Parámetros 'start' y 'end' son requeridos (YYYY-MM-DD)."},
                status=400
            )
        try:
            sdate = date_cls.fromisoformat(start)
            edate = date_cls.fromisoformat(end)
        except ValueError:
            return Response({"detail": "Fechas inválidas. Use YYYY-MM-DD."}, status=400)

        if sdate > edate:
            sdate, edate = edate, sdate

        # --- filtros opcionales ---
        filters = {
            "category_ids": _collect_multi(request, "category_id", "category_ids", "categories", "category_ids[]"),
            "category_names": _collect_multi(request, "category_names", "categories_names", "category", "category[]"),
            "product_ids": _collect_multi(request, "product_id", "product_ids", "products", "product_ids[]"),
            "product_names": _collect_multi(request, "product_names", "products_names", "product", "product[]"),
        }

        payload = self._build_range_payload(sdate, edate, only_final, mode, filters=filters)

        # Render plantilla
        html = render_to_string("purchase_report.html", payload)

        # Generar PDF con xhtml2pdf (Railway-friendly)
        from io import BytesIO
        from xhtml2pdf import pisa

        buf = BytesIO()
        result = pisa.CreatePDF(
            src=html,
            dest=buf,
            encoding="utf-8"
        )

        if result.err:
            # Si quieres log: logger.error(...)
            return Response({"detail": "Error al generar el PDF del reporte."}, status=500)

        pdf_bytes = buf.getvalue()

        # ✅ Respuesta PDF (descarga directa)
        filename = f"reporte_compras_{sdate.isoformat()}_{edate.isoformat()}_{mode}.pdf"
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "no-store"
        resp["Content-Length"] = str(len(pdf_bytes))
        return resp