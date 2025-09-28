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


class UnitViewSet(viewsets.ModelViewSet):
    queryset = Unit.objects.all().order_by("name")
    serializer_class = UnitSerializer

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


# ====================== NUEVOS HELPERS PARA FILTROS ======================
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
# ========================================================================


# --------------- Listas (aisladas por usuario) ---------------
class PurchaseListViewSet(viewsets.ModelViewSet):
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

    def _render_pdf_html(self, request, pl: PurchaseList, show_prices: bool = True):
        """Construye el HTML del PDF agrupando por categoría con decimales correctos."""
        items_qs = pl.items.select_related("product__category", "unit").all()

        groups_map = {}   # {category_name: [line, ...]}
        grand_total = Decimal("0.00")

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

        # Normalizar a lista ordenada
        groups = []
        flat_lines = []
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
        html = render_to_string("purchase_list.html", ctx)
        return html

    def _render_pdf_bytes(self, request, pl: PurchaseList, show_prices: bool = True):
        html = self._render_pdf_html(request, pl, show_prices=show_prices)
        # 1) WeasyPrint
        try:
            from weasyprint import HTML  # import perezoso
            return HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        except Exception:
            # 2) Fallback xhtml2pdf
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
    @action(detail=True, methods=['post'], url_path='finalize')
    def finalize(self, request, pk=None):
        """Finaliza una lista solo si todos los ítems no monetarios tienen precio."""
        pl = self.get_object()
        if pl.status == "final":
            return Response({"detail": "La lista ya está finalizada."}, status=400)
        try:
            self._ensure_complete_prices(pl)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=400)

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
        return Response({"detail": "Lista finalizada.", "id": pl.id, "series_code": pl.series_code}, status=200)

    @action(detail=True, methods=['get', 'post'], url_path='items')
    def items(self, request, pk=None):
        """
        GET  -> lista los ítems de la purchase_list (para 'Completar precios').
        POST -> agrega un ítem (comportamiento actual).
        """
        pl = self.get_object()

        if request.method.lower() == 'get':
            qs = pl.items.select_related("product", "unit").all()
            ser = PurchaseListItemSerializer(qs, many=True, context={"request": request})
            return Response(ser.data, status=200)

        # --- POST (agregar) ---
        if pl.status == "final":
            return Response({"detail": "No se pueden editar listas finalizadas."},
                            status=status.HTTP_400_BAD_REQUEST)

        data = request.data.copy()
        data['purchase_list'] = pl.id
        ser = PurchaseListItemSerializer(data=data, context={"request": request})

        if not ser.is_valid():
            return Response(ser.errors, status=400)

        try:
            obj = ser.save()
        except ValidationError as e:
            return Response({"detail": str(e)}, status=400)
        except Exception as e:
            return Response({"detail": f"No se pudo guardar el ítem: {e}"}, status=400)

        return Response(PurchaseListItemSerializer(obj, context={"request": request}).data, status=201)

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
        return Response(
            {"detail": f"Lista completada y finalizada. ({updated} ítems actualizados)",
             "id": pl.id, "series_code": pl.series_code},
            status=200
        )

    # ---------- PDF por lista ----------
    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, pk=None):
        pl = self.get_object()
        hide_param = request.query_params.get("hide_prices", "").lower()
        show_prices = hide_param not in ("1", "true", "yes")
        pdf_bytes = self._render_pdf_bytes(request, pl, show_prices=show_prices)
        if not pdf_bytes:
            return Response({"detail": "No se pudo generar el PDF en este entorno."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # --- nombre de archivo ---
        def _series_like(p: PurchaseList) -> str:
            base = p.series_code
            if not base:
                # sin serie: estilo historial (año-código-id)
                year = timezone.localdate().year
                rcode = getattr(p.restaurant, "code", None) or getattr(p.restaurant, "name", "R")
                base = f"{year}-{rcode}-{p.id:04d}"
            if not show_prices:
                parts = base.split("-")
                if len(parts) >= 3:
                    base = f"{'-'.join(parts[:-1])}-Sn-{parts[-1]}"
                else:
                    base = f"{base}-Sn"
            return base

        filename = f"{_series_like(pl)}.pdf"

        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp['Content-Disposition'] = f'inline; filename="{filename}"'
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

    # ---------- Reporte consolidado por rango (con filtros opcionales) ----------
    def _build_range_payload(self, sdate, edate, only_final=True, mode="detail", *, filters=None):
        """
        mode:
          - 'detail': incluye lines (producto, unidad, qty, precio, subtotal)
          - 'summary': omite lines y deja solo totales por categoría/restaurante

        filters (opcional):
          {
            "category_ids": [str...],
            "category_names": [str...],
            "product_ids": [str...],
            "product_names": [str...],
          }
        """
        qs_lists = (PurchaseList.objects
                    .select_related("restaurant")
                    .filter(created_by=self.request.user,
                            created_at__date__gte=sdate, created_at__date__lte=edate))
        if only_final:
            qs_lists = qs_lists.filter(status="final")

        items = (PurchaseListItem.objects
                 .select_related("purchase_list__restaurant", "product__category", "unit")
                 .filter(purchase_list__in=qs_lists))

        # ---- aplicar filtros si llegan ----
        filters = filters or {}
        cat_ids   = filters.get("category_ids") or []
        cat_names = filters.get("category_names") or []
        prod_ids  = filters.get("product_ids") or []
        prod_names= filters.get("product_names") or []

        def _to_int_list(xs):
            out = []
            for x in xs:
                try:
                    out.append(int(x))
                except Exception:
                    pass
            return out

        if cat_ids:
            ids = _to_int_list(cat_ids)
            if ids:
                items = items.filter(product__category_id__in=ids)
        elif cat_names:
            items = items.filter(product__category__name__in=cat_names)

        if prod_ids:
            ids = _to_int_list(prod_ids)
            if ids:
                items = items.filter(product_id__in=ids)
        elif prod_names:
            items = items.filter(product__name__in=prod_names)

        # ---- resto igual que antes ----
        rest_map = {}
        date_map = defaultdict(lambda: {"lists": set(), "total": Decimal("0.00")})
        grand_total = Decimal("0.00")

        for it in items:
            rest = getattr(it.purchase_list.restaurant, "name", "Sin restaurante")
            cat  = getattr(getattr(it.product, "category", None), "name", "Sin categoría")

            price = (it.price_soles or Decimal("0"))
            qty   = (it.qty or Decimal("0"))
            is_curr = bool(getattr(it.unit, "is_currency", False))
            ulabel  = (getattr(it.unit, "symbol", None) or getattr(it.unit, "name", "")) or "-"

            raw_subtotal = qty if is_curr else (qty * price)
            subtotal = raw_subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            r = rest_map.setdefault(rest, {"categories": {}, "total": Decimal("0.00")})
            c = r["categories"].setdefault(cat, {"lines": [] if mode == "detail" else None, "total": Decimal("0.00")})

            if mode == "detail":
                c["lines"].append({
                    "date": it.purchase_list.created_at.date().isoformat(),
                    "product": it.product.name,
                    "unit": ulabel,
                    "qty": float(qty),
                    "price": None if is_curr else float(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                    "subtotal": float(subtotal),
                    "unit_is_currency": is_curr,
                })

            c["total"] = (c["total"] + subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            r["total"] = (r["total"] + subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            grand_total = (grand_total + subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            d = it.purchase_list.created_at.date().isoformat()
            date_map[d]["lists"].add(it.purchase_list_id)
            date_map[d]["total"] = (date_map[d]["total"] + subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        restaurants = []
        for rname in sorted(rest_map.keys()):
            cat_list = []
            for cname in sorted(rest_map[rname]["categories"].keys()):
                cdata = rest_map[rname]["categories"][cname]
                entry = {
                    "category": cname,
                    "total": float(Decimal(cdata["total"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                }
                if mode == "detail":
                    entry["lines"] = cdata["lines"]
                cat_list.append(entry)

            restaurants.append({
                "restaurant": rname,
                "total": float(Decimal(rest_map[rname]["total"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "categories": cat_list,
            })

        date_breakdown = []
        for d in sorted(date_map.keys()):
            date_breakdown.append({
                "date": d,
                "lists": len(date_map[d]["lists"]),
                "total": float(Decimal(date_map[d]["total"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            })

        return {
            "mode": mode,
            "start": sdate.isoformat(),
            "end": edate.isoformat(),
            "only_final": only_final,
            "grand_total": float(grand_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "restaurants": restaurants,
            "dates": date_breakdown,
        }

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

        # Render plantilla
        html = render_to_string("purchase_report.html", payload)

        pdf_bytes = None
        try:
            from weasyprint import HTML
            pdf_bytes = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        except Exception:
            try:
                from xhtml2pdf import pisa
                from io import BytesIO
                buf = BytesIO()
                result = pisa.CreatePDF(html, dest=buf, encoding='utf-8')
                if not result.err:
                    pdf_bytes = buf.getvalue()
            except Exception:
                pdf_bytes = None

        if not pdf_bytes:
            return Response({"detail": "No se pudo generar el PDF del reporte."}, status=500)

        # Forzar descarga directa (attachment)
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp['Content-Disposition'] = f'attachment; filename="reporte-{payload["start"]}_{payload["end"]}.pdf"'
        return resp
