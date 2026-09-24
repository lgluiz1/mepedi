from rest_framework import serializers
from .models import Category, Product, OptionGroup, OptionItem
from stores.models import Store


# --- Serializers para Gestão pelo Lojista ---

class CategorySerializer(serializers.ModelSerializer):
    products_count = serializers.IntegerField(source='products.count', read_only=True)

    class Meta:
        model = Category
        fields = ['id', 'store', 'name', 'description', 'order', 'is_active', 'products_count', 'created_at']
        read_only_fields = ['id', 'store', 'created_at']

    def validate(self, attrs):
        # Garante unicidade por loja no nível do serializer
        store = self.context.get('store') or attrs.get('store') or getattr(self.instance, 'store', None)
        name = attrs.get('name')
        if store and name:
            qs = Category.objects.filter(store=store, name__iexact=name)
            if self.instance:
                qs = qs.exclude(id=self.instance.id)
            if qs.exists():
                raise serializers.ValidationError({"name": "Já existe uma categoria com este nome nesta loja."})
        return attrs


class OptionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OptionItem
        fields = ['id', 'option_group', 'name', 'price', 'is_available', 'order', 'created_at']
        read_only_fields = ['id', 'created_at']


class OptionGroupSerializer(serializers.ModelSerializer):
    items = OptionItemSerializer(many=True, read_only=True)

    class Meta:
        model = OptionGroup
        fields = [
            'id', 'store', 'product', 'name', 'description',
            'min_options', 'max_options', 'is_required', 'order',
            'items', 'created_at'
        ]
        read_only_fields = ['id', 'store', 'created_at']


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    option_groups = OptionGroupSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'store', 'category', 'category_name', 'name',
            'description', 'price', 'image', 'is_active', 'order',
            'option_groups', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'store', 'created_at', 'updated_at']

    def validate(self, attrs):
        category = attrs.get('category') or getattr(self.instance, 'category', None)
        store = attrs.get('store') or getattr(self.instance, 'store', None)

        if category and store and category.store_id != store.id:
            raise serializers.ValidationError({
                "category": "A categoria selecionada não pertence à loja especificada."
            })
        return attrs


# --- Serializers para o Cardápio Público Mobile-First ---

class PublicOptionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OptionItem
        fields = ['id', 'name', 'price', 'is_available', 'order']


class PublicOptionGroupSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = OptionGroup
        fields = ['id', 'name', 'description', 'min_options', 'max_options', 'is_required', 'order', 'items']

    def get_items(self, obj):
        # Apenas opções ativas/disponíveis no cardápio
        active_items = obj.items.filter(is_available=True)
        return PublicOptionItemSerializer(active_items, many=True).data


class PublicProductSerializer(serializers.ModelSerializer):
    option_groups = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['id', 'name', 'description', 'price', 'image', 'order', 'option_groups']

    def get_option_groups(self, obj):
        groups = obj.option_groups.all()
        return PublicOptionGroupSerializer(groups, many=True).data


class PublicCategoryMenuSerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'description', 'order', 'products']

    def get_products(self, obj):
        # Produtos ativos da categoria
        products = obj.products.filter(is_active=True).prefetch_related('option_groups__items')
        return PublicProductSerializer(products, many=True).data
