from rest_framework import serializers
from decimal import Decimal
from .models import Order, OrderItem, OrderItemOption
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
    formatted_delivery_address = serializers.ReadOnlyField()
    display_number = serializers.ReadOnlyField()
    customer_whatsapp_link = serializers.SerializerMethodField()
    store_whatsapp_link = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'public_id', 'store', 'order_number', 'display_number',
            'customer', 'status', 'status_display', 'delivery_type',
            'delivery_type_display', 'payment_method', 'payment_method_display',
            'change_for', 'delivery_fee', 'subtotal', 'total',
            'formatted_delivery_address', 'street', 'number', 'complement',
            'neighborhood', 'city', 'state', 'postal_code', 'reference',
            'notes', 'items', 'customer_whatsapp_link', 'store_whatsapp_link',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'public_id', 'order_number', 'display_number',
            'subtotal', 'delivery_fee', 'total', 'created_at', 'updated_at'
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


class UpdateOrderStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.STATUS_CHOICES)
