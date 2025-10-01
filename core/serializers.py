class PurchaseListItemSerializer(serializers.ModelSerializer):
    """
    V2:
    - product y unit deben pertenecer al usuario.
    - purchase_list la trae la instancia (read_only).
    - Si unit.is_currency=True: qty es importe y price_soles se fuerza a None.
    """
    # Ayudas para el frontend (solo lectura)
    product_name     = serializers.SerializerMethodField(read_only=True)
    unit_name        = serializers.SerializerMethodField(read_only=True)
    unit_symbol      = serializers.SerializerMethodField(read_only=True)
    unit_is_currency = serializers.SerializerMethodField(read_only=True)
    subtotal_soles   = serializers.SerializerMethodField(read_only=True)
    # Si necesitas conocer el restaurante asociado al ítem (opcional):
    # restaurant_id = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PurchaseListItem
        fields = (
            "id",
            "purchase_list",              # FK a PurchaseList (solo lectura)
            "product", "product_name",
            "unit", "unit_name", "unit_symbol", "unit_is_currency",
            "qty",
            "price_soles",
            "subtotal_soles",
            # "restaurant_id",            # <-- descomenta si usas el campo opcional
        )
        read_only_fields = ("purchase_list","series_code", "created_by", "created_at", "finalized_at")
        extra_kwargs = {
            "price_soles": {"required": False, "allow_null": True},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Si vas a crear/editar ítems con product por POST/PUT, ajusta el queryset según user.
        if "product" in self.fields:
            from .models import Product
            self.fields["product"].queryset = Product.objects.none()

    # ------- Getters de solo lectura -------
    def get_product_name(self, obj):
        return getattr(obj.product, "name", None)

    def get_unit_name(self, obj):
        return getattr(obj.unit, "name", None)

    def get_unit_symbol(self, obj):
        return getattr(obj.unit, "symbol", None)

    def get_unit_is_currency(self, obj):
        return bool(getattr(obj.unit, "is_currency", False))

    def get_subtotal_soles(self, obj):
        if obj.price_soles is None or obj.qty is None:
            return None
        try:
            return float(obj.price_soles) * float(obj.qty)
        except Exception:
            return None

    # Opcional:
    # def get_restaurant_id(self, obj):
        # return getattr(getattr(obj, "purchase_list", None), "restaurant_id", None)

    # ------- Validación V2 -------
    def validate(self, attrs):
        from .models import Unit as UnitModel, PurchaseList as PurchaseListModel, Product as ProductModel

        user = _get_request_user(self)
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("No autenticado.")

        # purchase_list llega por la instancia (read_only) o por contexto si lo inyectas
        pl = (
            getattr(self.instance, "purchase_list", None)
            or (self.context.get("purchase_list") if self.context else None)
        )

        unit    = attrs.get("unit") or getattr(self.instance, "unit", None)
        product = attrs.get("product") or getattr(self.instance, "product", None)
        qty     = attrs.get("qty") if "qty" in attrs else getattr(self.instance, "qty", None)
        price   = attrs.get("price_soles") if "price_soles" in attrs else getattr(self.instance, "price_soles", None)

        # Existencia y tipos
        if not isinstance(unit, UnitModel):
            raise serializers.ValidationError({"unit": "Unidad inválida."})
        if not isinstance(product, ProductModel):
            raise serializers.ValidationError({"product": "Producto inválido."})
        if pl is None or not isinstance(pl, PurchaseListModel):
            raise serializers.ValidationError({"purchase_list": "Lista inválida o ausente."})
        if qty is None:
            raise serializers.ValidationError({"qty": "Cantidad requerida."})

        # Pertenencia al usuario
        if getattr(unit, "owner_id", None) != user.id:
            raise serializers.ValidationError({"unit": "No pertenece al usuario."})
        if getattr(product, "owner_id", None) != user.id:
            raise serializers.ValidationError({"product": "No pertenece al usuario."})
        if getattr(pl, "created_by_id", None) != user.id:
            raise serializers.ValidationError({"purchase_list": "No pertenece al usuario."})

        # Estado de la lista: no modificar si está final
        if pl.status == "final":
            raise serializers.ValidationError({"purchase_list": "No se pueden modificar listas finalizadas."})

        # Reglas de precio/importe
        if unit.is_currency:
            # qty = importe; normalizamos price_soles a None
            attrs["price_soles"] = None
        else:
            if qty < 0:
                raise serializers.ValidationError({"qty": "Debe ser mayor o igual a cero."})
            if price is not None:
                try:
                    Decimal(str(price))
                except Exception:
                    raise serializers.ValidationError({"price_soles": "Formato inválido."})

        return attrs
