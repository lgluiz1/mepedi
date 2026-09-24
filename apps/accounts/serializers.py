from rest_framework import serializers
from django.db import transaction
from django.contrib.auth.password_validation import validate_password
from .models import User, StoreMembership
from stores.models import Store


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer de dados cadastrais do usuário.
    """
    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'phone', 'is_merchant', 'date_joined']
        read_only_fields = ['id', 'date_joined']


class RegisterMerchantSerializer(serializers.Serializer):
    """
    Serializer para cadastro inicial do Lojista + Criação da Loja.
    Conforme requisito 8:
    - nome da loja;
    - nome do responsável;
    - CPF ou CNPJ;
    - e-mail;
    - telefone;
    - WhatsApp;
    - senha;
    - endereço (rua, número, bairro, cidade, uf, cep).
    """
    # Dados do Lojista
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)

    # Dados da Loja
    store_name = serializers.CharField(max_length=150)
    document = serializers.CharField(max_length=20, required=False, allow_blank=True)
    whatsapp = serializers.CharField(max_length=20)
    
    # Endereço da Loja
    street = serializers.CharField(max_length=150, required=False, allow_blank=True)
    number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    complement = serializers.CharField(max_length=100, required=False, allow_blank=True)
    neighborhood = serializers.CharField(max_length=100, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state = serializers.CharField(max_length=2, required=False, allow_blank=True)
    postal_code = serializers.CharField(max_length=10, required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Este e-mail já está em uso por outro usuário.")
        return value.lower()

    @transaction.atomic
    def create(self, validated_data):
        # 1. Cria o usuário lojista
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            full_name=validated_data['full_name'],
            phone=validated_data.get('phone', ''),
            is_merchant=True
        )

        # 2. Cria a loja pertencente ao lojista com slug automático único
        store = Store.objects.create(
            owner=user,
            name=validated_data['store_name'],
            document=validated_data.get('document', ''),
            phone=validated_data.get('phone', ''),
            whatsapp=validated_data['whatsapp'],
            street=validated_data.get('street', ''),
            number=validated_data.get('number', ''),
            complement=validated_data.get('complement', ''),
            neighborhood=validated_data.get('neighborhood', ''),
            city=validated_data.get('city', ''),
            state=validated_data.get('state', '').upper(),
            postal_code=validated_data.get('postal_code', ''),
            is_active=True,
            is_open=True
        )

        # 3. Registra o vínculo do lojista como PROPRIETÁRIO (owner)
        StoreMembership.objects.create(
            user=user,
            store=store,
            role=StoreMembership.ROLE_OWNER,
            is_active=True
        )

        return {
            'user': user,
            'store': store
        }
