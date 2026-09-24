from rest_framework import serializers
from .models import Store, BusinessHour


class BusinessHourSerializer(serializers.ModelSerializer):
    weekday_display = serializers.CharField(source='get_weekday_display', read_only=True)

    class Meta:
        model = BusinessHour
        fields = ['id', 'weekday', 'weekday_display', 'opening_time', 'closing_time', 'is_closed']


class StorePublicSerializer(serializers.ModelSerializer):
    """
    Serializer de dados públicos da loja para a página do cardápio digital.
    """
    full_address = serializers.ReadOnlyField()

    class Meta:
        model = Store
        fields = [
            'id',
            'name',
            'slug',
            'description',
            'whatsapp',
            'phone',
            'full_address',
            'is_open',
            'is_paused',
            'minimum_order_value',
            'estimated_delivery_time_min',
            'estimated_delivery_time_max',
            'logo',
            'banner',
        ]


class StoreDetailSerializer(serializers.ModelSerializer):
    """
    Serializer completo da loja para o painel do lojista.
    """
    business_hours = BusinessHourSerializer(many=True, read_only=True)
    full_address = serializers.ReadOnlyField()

    class Meta:
        model = Store
        fields = [
            'id',
            'name',
            'slug',
            'document',
            'phone',
            'whatsapp',
            'description',
            'street',
            'number',
            'complement',
            'neighborhood',
            'city',
            'state',
            'postal_code',
            'full_address',
            'is_active',
            'is_open',
            'is_paused',
            'minimum_order_value',
            'estimated_delivery_time_min',
            'estimated_delivery_time_max',
            'logo',
            'banner',
            'business_hours',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'slug', 'created_at', 'updated_at']
