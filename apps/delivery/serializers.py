from rest_framework import serializers
from .models import DeliveryZone


class DeliveryZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryZone
        fields = [
            'id', 'store', 'name', 'neighborhoods', 'fee',
            'estimated_time_min', 'estimated_time_max', 'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'store', 'created_at']


class CalculateFeeRequestSerializer(serializers.Serializer):
    neighborhood = serializers.CharField(max_length=150, required=False, allow_blank=True)
    postal_code = serializers.CharField(max_length=10, required=False, allow_blank=True)
