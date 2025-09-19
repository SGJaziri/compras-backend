# core/views.py
from django.utils import timezone
from django.template.loader import render_to_string
from django.http import HttpResponse

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from datetime import date as date_cls
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from .models import (
    Category, Product, Restaurant, Purchase,
    PurchaseList, PurchaseListItem, Unit
)
from .serializers import (
    CategorySerializer, ProductSerializer, RestaurantSerializer, PurchaseSerializer,
    PurchaseListSerializer, PurchaseListItemSerializer, UnitSerializer
)
from .services import generate_series_code


# --- (opcional) Mixin de lectura pública
class PublicReadMixin:
    authentication_classes = []  # sin SessionAuth/CSRF para GETs del frontend
    permission_classes = [permissions.IsAuthenticated]
    public_actions = {"list", "retrieve"}

    def get_permissions(self):
        if getattr(self, "action", None) in self.public_actions:
            return [permissions.AllowAny()]
        return super().get_permissions()


# ---------------- Permisos base ----------------
class DefaultPerm(permissions.IsAuthenticated):
    """Permiso por defecto para panel/admin."""
    pass


# --------------- Público: config mínima ---------------
class PublicConfigView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # sin CSRF para público

    def get(self, request):
        restaurants = Restaurant.objects.all().order_by("name")
        categories = Category.objects.all().order_by("name")
        products = Product.objects.select_related("category").all().order_by("name")
        units = Unit.objects.all().order_by("name")

        return Response({
            "restaurants": RestaurantSerializer(restaurants, many=True).data,
            "categories": CategorySerializer(categories, many=True).data,
            "products": ProductSerializer(products, many=True).data,
            "units": UnitSerializer(units, many=True).data,
        })


# --------- Catálogo (todo público) ----------
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all().order_by("name")
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.select_related("category").all().order_by("name")
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []


class UnitViewSet(viewsets.ModelViewSet):
    queryset = Unit.objects.all().order_by("name")
    serializer_class = UnitSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []


class RestaurantViewSet(viewsets.ModelViewSet):
    queryset = Restaurant.objects.all().order_by("name")
    serializer_class = RestaurantSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []


# --------------- Compras formales (futuro) ---------------
class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.prefetch_related('items').all()
    serializer_class = PurchaseSerializer
    permission_classes = [DefaultPerm]

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        return Response({'detail': 'PDF no implementado aún'}, status=200)


# --------------- Listas (flujo público) ---------------
class PurchaseListViewSet(viewsets.ModelViewSet):
    """
    Público temporal: list, retrieve, create, add_item, finalize,
    pdf, export_by_date, export_range, export_range_pdf
    Admin: update/partial_update/destroy
    """
    queryset = PurchaseList.objects.prefetch_related('items', 'restaurant').all()
    serializer_class = PurchaseListSerializer

    # Desactivar SessionAuth/CSRF en todo el ViewSet para el flujo público.
    authentication_classes = []
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        public_actions = [
            'list', 'retrieve', 'create', 'add_item', 'finalize',
            'pdf', 'export_by_date', 'export_range', 'export_range_pdf'
        ]
        if self.action in public_actions:
            return [permissions.AllowAny()]
        return super().get_permissions()

    @action(
        detail=True, methods=['post'], url_path='finalize',
        permission_classes=[permissions.AllowAny], authentication_classes=[]
    )
    def finalize(self, request, pk=None):
        pl = self.get_object()
        if pl.status == "final":
            return Response(
                {"detail": "La lista ya está finalizada."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not pl.series_code:
            pl.series_code = generate_series_code(pl.restaurant.code, PurchaseList)
        pl.status = "final"
        pl.finalized_at = timezone.now()
        pl.save()
        return Response(PurchaseListSerializer(pl).data, status=200)

    @action(
        detail=True, methods=['post'], url_path='items',
        permission_classes=[permissions.AllowAny], authentication_classes=[]
    )
    def add_item(self, request, pk=None):
        """Agregar ítem a la lista (builder público)."""
        pl = self.get_object()
        if pl.status == "final":
            return Response(
                {"detail": "No se pueden editar listas finalizadas."},
                status=status.HTTP_400_BAD_REQUEST
            )
        data = request.data.copy()
        data['purchase_list'] = pl.id
        ser = PurchaseListItemSerializer(data=data)
        if ser.is_valid():
            ser.save()
            return Response(ser.data, status=201)
        return Response(ser.errors, status=400)

    # ---------- Helpers internos (NO @action) ----------
    def _render_pdf_html(self, request, pl):
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

            line = {
                "product": it.product.name,
                "unit": it.unit.name,
                "qty": float(qty),
                "price": None if getattr(it.unit, "is_currency", False)
                         else float(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "subtotal": float(subtotal),
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
        }
        html = render_to_string("purchase_list.html", ctx)
        return html

    def _render_pdf_bytes(self, request, pl):
        html = self._render_pdf_html(request, pl)
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

    # ---------- Acción PDF por lista ----------
    @action(
        detail=True, methods=['get'], url_path='pdf',
        permission_classes=[permissions.AllowAny], authentication_classes=[]
    )
    def pdf(self, request, pk=None):
        """Genera el PDF de UNA lista (agrupado por categoría)."""
        pl = self.get_object()
        pdf_bytes = self._render_pdf_bytes(request, pl)
        if not pdf_bytes:
            return Response({"detail": "No se pudo generar el PDF en este entorno."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp['Content-Disposition'] = f'inline; filename="{pl.series_code or pl.id}.pdf"'
        return resp

    # ---------- Índice por fecha (1 PDF por restaurante) ----------
    @action(
        detail=False, methods=['get'], url_path='export/by-date',
        permission_classes=[permissions.AllowAny], authentication_classes=[]
    )
    def export_by_date(self, request):
        """
        Devuelve JSON con 1 entrada por restaurante para la fecha indicada.
        Cada entrada incluye el URL directo del PDF de su lista más reciente ese día.
        Query params:
          - date=YYYY-MM-DD  (opcional; por defecto hoy)
          - only_final=true|false (opcional; default true)
        """
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
              .filter(created_at__date=d))
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

    # ---------- Reporte consolidado por rango ----------
    def _build_range_payload(self, sdate, edate, only_final=True):
        """
        Arma el payload del reporte por rango: restaurants[], grand_total y dates[].
        Calcula con Decimal y redondea a 2 decimales.
        """
        qs_lists = (PurchaseList.objects
                    .select_related("restaurant")
                    .filter(created_at__date__gte=sdate, created_at__date__lte=edate))
        if only_final:
            qs_lists = qs_lists.filter(status="final")

        items = (PurchaseListItem.objects
                 .select_related("purchase_list__restaurant", "product__category", "unit")
                 .filter(purchase_list__in=qs_lists))

        rest_map = {}    # {rest: {"categories": {cat: {"lines":[...], "total":Decimal}}, "total":Decimal}}
        date_map = defaultdict(lambda: {"lists": set(), "total": Decimal("0.00")})
        grand_total = Decimal("0.00")

        for it in items:
            rest = getattr(it.purchase_list.restaurant, "name", "Sin restaurante")
            cat  = getattr(getattr(it.product, "category", None), "name", "Sin categoría")

            price = (it.price_soles or Decimal("0"))
            qty   = (it.qty or Decimal("0"))
            raw_subtotal = qty if getattr(it.unit, "is_currency", False) else (qty * price)
            subtotal = raw_subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            r = rest_map.setdefault(rest, {"categories": {}, "total": Decimal("0.00")})
            c = r["categories"].setdefault(cat, {"lines": [], "total": Decimal("0.00")})
            c["lines"].append({
                "date": it.purchase_list.created_at.date().isoformat(),
                "product": it.product.name,
                "unit": it.unit.name,
                "qty": float(qty),
                "price": None if getattr(it.unit, "is_currency", False)
                         else float(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "subtotal": float(subtotal),
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
                cat_list.append({
                    "category": cname,
                    "total": float(Decimal(cdata["total"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                    "lines": cdata["lines"],
                })
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
            "start": sdate.isoformat(),
            "end": edate.isoformat(),
            "only_final": only_final,
            "grand_total": float(grand_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "restaurants": restaurants,
            "dates": date_breakdown,
        }

    @action(detail=False, methods=['get'], url_path='export/range',
            permission_classes=[permissions.AllowAny], authentication_classes=[])
    def export_range(self, request):
        """Devuelve JSON del rango con totales en 2 decimales."""
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        only_final = request.query_params.get("only_final", "true").lower() != "false"

        if not start or not end:
            return Response({"detail": "Parámetros 'start' y 'end' son requeridos (YYYY-MM-DD)."}, status=400)
        try:
            sdate = date_cls.fromisoformat(start)
            edate = date_cls.fromisoformat(end)
        except ValueError:
            return Response({"detail": "Fechas inválidas. Use YYYY-MM-DD."}, status=400)
        if sdate > edate:
            sdate, edate = edate, sdate

        payload = self._build_range_payload(sdate, edate, only_final)
        return Response(payload, status=200)

    @action(detail=False, methods=['get'], url_path='export/range/pdf',
            permission_classes=[permissions.AllowAny], authentication_classes=[])
    def export_range_pdf(self, request):
        """
        PDF del rango (ruta directa con /pdf/).
        Query: start, end, only_final
        """
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        only_final = request.query_params.get("only_final", "true").lower() != "false"

        if not start or not end:
            return Response({"detail": "Parámetros 'start' y 'end' son requeridos (YYYY-MM-DD)."}, status=400)
        try:
            sdate = date_cls.fromisoformat(start)
            edate = date_cls.fromisoformat(end)
        except ValueError:
            return Response({"detail": "Fechas inválidas. Use YYYY-MM-DD."}, status=400)
        if sdate > edate:
            sdate, edate = edate, sdate

        payload = self._build_range_payload(sdate, edate, only_final)

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

        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp['Content-Disposition'] = f'inline; filename="reporte-{payload["start"]}_{payload["end"]}.pdf"'
        return resp
