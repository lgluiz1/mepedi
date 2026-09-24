from rest_framework import serializers
from .models import Customer, CustomerAddress, clean_phone_number


class CustomerAddressSerializer(serializers.ModelSerializer):
    formatted_address = serializers.ReadOnlyField()

    class Meta:
        model = CustomerAddress
        fields = [
            'id', 'customer', 'street', 'number', 'complement',
            'neighborhood', 'city', 'state', 'postal_code',
            'reference', 'is_default', 'formatted_address', 'created_at'
        ]
        read_only_fields = ['id', 'customer', 'created_at']


class CustomerSerializer(serializers.ModelSerializer):
    addresses = CustomerAddressSerializer(many=True, read_only=True)

    class Meta:
        model = Customer
        fields = [
            'id', 'store', 'name', 'phone', 'document', 'email',
            'notes', 'orders_count', 'total_spent', 'addresses',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'store', 'orders_count', 'total_spent', 'created_at', 'updated_at']

    def validate_phone(self, value):
        cleaned = clean_phone_number(value)
        if len(cleaned) < 10 or len(cleaned) > 11:
            raise serializers.ValidationError("O telefone deve conter DDD e entre 10 e 11 dígitos numéricos.")
        return cleaned


class CustomerIdentifyRequestSerializer(serializers.Serializer):
    """
    Serializer para o fluxo de identificação no checkout pelo telefone.
    Conforme requisito 9:
    - Telefone é obrigatório (identificador principal).
    - Nome é obrigatório.
    - CPF é opcional.
    """
    phone = serializers.CharField(max_length=20)
    name = serializers.CharField(max_length=150)
    document = serializers.CharField(max_length=20, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate_phone(self, value):
        cleaned = clean_phone_number(value)
        if len(cleaned) < 10 or len(cleaned) > 11:
            raise serializers.ValidationError("Informe um número de telefone celular válido com DDD.")
        return cleaned
