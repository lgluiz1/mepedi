from rest_framework import serializers
from decimal import Decimal
from .models import Order, OrderItem, OrderItemOption, Table, TableSession
from customers.serializers import CustomerSerializer, CustomerIdentifyRequestSerializer


class OrderItemOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItemOption
        fields = ['id', 'name', 'price', 'group_name']


class OrderItemSerializer(serializers.ModelSerializer):
    selected_options = OrderItemOptionSerializer(many=True, read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            'id', 'product', 'product_name', 'unit_price',
            'quantity', 'subtotal', 'total', 'notes', 'selected_options'
        ]


class OrderDetailSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    delivery_type_display = serializers.CharField(source='get_delivery_type_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    origin_display = serializers.CharField(source='get_origin_display', read_only=True)
    table_number = serializers.CharField(source='table.number', read_only=True, default=None)
    table_id = serializers.IntegerField(source='table.id', read_only=True, default=None)
    table_session_id = serializers.UUIDField(source='table_session.public_id', read_only=True, default=None)
    formatted_delivery_address = serializers.ReadOnlyField()
    display_number = serializers.ReadOnlyField()
    customer_whatsapp_link = serializers.SerializerMethodField()
    store_whatsapp_link = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'public_id', 'store', 'order_number', 'display_number',
            'origin', 'origin_display', 'table', 'table_number', 'table_id', 'table_session_id',
            'customer', 'status', 'status_display', 'delivery_type',
            'delivery_type_display', 'payment_method', 'payment_method_display',
            'change_for', 'delivery_fee', 'subtotal', 'discount', 'coupon_code', 'total',
            'formatted_delivery_address', 'street', 'number', 'complement',
            'neighborhood', 'city', 'state', 'postal_code', 'reference',
            'notes', 'items', 'customer_whatsapp_link', 'store_whatsapp_link',
            'accepted_at', 'preparing_at', 'ready_at',
            'seconds_remaining_to_accept', 'preparation_seconds_remaining', 'is_preparation_delayed',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'public_id', 'order_number', 'display_number',
            'subtotal', 'delivery_fee', 'discount', 'total', 'created_at', 'updated_at',
            'accepted_at', 'preparing_at', 'ready_at',
            'seconds_remaining_to_accept', 'preparation_seconds_remaining', 'is_preparation_delayed',
        ]

    def get_customer_whatsapp_link(self, obj):
        from whatsapp.services import get_customer_whatsapp_link
        return get_customer_whatsapp_link(obj)

    def get_store_whatsapp_link(self, obj):
        from whatsapp.services import get_store_order_whatsapp_link
        request = self.context.get('request')
        return get_store_order_whatsapp_link(obj, request=request)


class OrderItemInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(default=1, min_value=1)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True)
    options = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list
    )


class AddressInputSerializer(serializers.Serializer):
    street = serializers.CharField(max_length=150)
    number = serializers.CharField(max_length=20)
    complement = serializers.CharField(max_length=100, required=False, allow_blank=True)
    neighborhood = serializers.CharField(max_length=100)
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=2)
    postal_code = serializers.CharField(max_length=10, required=False, allow_blank=True)
    reference = serializers.CharField(max_length=150, required=False, allow_blank=True)


class CreateOrderRequestSerializer(serializers.Serializer):
    """
    Serializer de entrada para submissão do pedido pelo cliente.
    """
    customer = CustomerIdentifyRequestSerializer()
    delivery_type = serializers.ChoiceField(choices=Order.TYPE_CHOICES, default=Order.TYPE_DELIVERY)
    address = AddressInputSerializer(required=False, allow_null=True)
    payment_method = serializers.ChoiceField(choices=Order.PAYMENT_CHOICES, default=Order.PAY_PIX)
    change_for = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    items = serializers.ListField(child=OrderItemInputSerializer(), min_length=1)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    coupon_code = serializers.CharField(max_length=30, required=False, allow_blank=True, allow_null=True)


class UpdateOrderStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.STATUS_CHOICES)


class TableSerializer(serializers.ModelSerializer):
    is_occupied = serializers.BooleanField(read_only=True)
    current_session_id = serializers.SerializerMethodField()
    current_session_total = serializers.SerializerMethodField()
    current_session_status = serializers.SerializerMethodField()

    class Meta:
        model = Table
        fields = [
            'id', 'number', 'name', 'qr_token', 'is_active',
            'is_occupied', 'current_session_id', 'current_session_total', 'current_session_status'
        ]

    def get_current_session_id(self, obj):
        sess = obj.current_session
        return str(sess.public_id) if sess else None

    def get_current_session_total(self, obj):
        sess = obj.current_session
        return float(sess.calculate_total()) if sess else 0.0

    def get_current_session_status(self, obj):
        sess = obj.current_session
        return sess.status if sess else None


class TableSessionDetailSerializer(serializers.ModelSerializer):
    table_number = serializers.CharField(source='table.number', read_only=True)
    table_name = serializers.CharField(source='table.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    orders = OrderDetailSerializer(source='get_valid_orders', many=True, read_only=True)
    items_breakdown = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()

    class Meta:
        model = TableSession
        fields = [
            'id', 'public_id', 'table', 'table_number', 'table_name', 'status',
            'status_display', 'opened_at', 'closed_at', 'payment_method',
            'discount', 'total_paid', 'subtotal', 'total', 'notes',
            'orders', 'items_breakdown'
        ]

    def get_subtotal(self, obj):
        return float(obj.calculate_subtotal())

    def get_total(self, obj):
        return float(obj.calculate_total())

    def get_items_breakdown(self, obj):
        return obj.get_items_breakdown()


class CreateTableOrderRequestSerializer(serializers.Serializer):
    customer_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    customer_phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    items = serializers.ListField(child=OrderItemInputSerializer(), min_length=1)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')


class CloseTableSessionRequestSerializer(serializers.Serializer):
    payment_method = serializers.ChoiceField(choices=Order.PAYMENT_CHOICES, default=Order.PAY_PIX)
    discount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=Decimal('0.00'))
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')


