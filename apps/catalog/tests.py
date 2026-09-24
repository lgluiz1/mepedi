from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient
from rest_framework import status

from stores.models import Store
from accounts.models import StoreMembership
from catalog.models import Category, Product, OptionGroup, OptionItem

User = get_user_model()


class CategoryAndProductModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='lojista@lanches.com',
            password='Password123!',
            full_name='Lojista Lanches'
        )
        self.store_a = Store.objects.create(
            owner=self.user,
            name="Hamburgueria Alpha",
            whatsapp="11911111111"
        )
        self.store_b = Store.objects.create(
            owner=self.user,
            name="Hamburgueria Beta",
            whatsapp="11922222222"
        )

    def test_category_creation_and_uniqueness_per_store(self):
        """Testa criação de categorias e unicidade por loja."""
        cat1 = Category.objects.create(
            store=self.store_a,
            name="Hambúrgueres",
            order=1
        )
        self.assertEqual(cat1.name, "Hambúrgueres")

        # Não permite categoria com mesmo nome na MESMA loja
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Category.objects.create(
                    store=self.store_a,
                    name="Hambúrgueres"
                )

        # Permite categoria com mesmo nome em OUTRA loja
        cat2 = Category.objects.create(
            store=self.store_b,
            name="Hambúrgueres"
        )
        self.assertEqual(cat2.store, self.store_b)

    def test_product_validation_against_category_from_another_store(self):
        """
        Garante que um produto NÃO pode ser associado a uma categoria de outra loja.
        """
        cat_b = Category.objects.create(store=self.store_b, name="Combos")

        product = Product(
            store=self.store_a,
            category=cat_b,  # Categoria da loja B para produto da loja A!
            name="X-Salada",
            price=Decimal("25.00")
        )
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_product_creation_success(self):
        """Testa criação bem sucedida de produto."""
        cat_a = Category.objects.create(store=self.store_a, name="Lanches")
        product = Product.objects.create(
            store=self.store_a,
            category=cat_a,
            name="X-Bacon Supremo",
            price=Decimal("32.50"),
            description="Pão brioche, blend 180g e muito bacon"
        )
        self.assertEqual(product.name, "X-Bacon Supremo")
        self.assertEqual(product.price, Decimal("32.50"))
        self.assertTrue(product.is_active)


class OptionGroupAndItemModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='chef@lanches.com',
            password='Password123!',
            full_name='Chef Lanches'
        )
        self.store = Store.objects.create(
            owner=self.user,
            name="Burger House",
            whatsapp="11933333333"
        )
        self.category = Category.objects.create(store=self.store, name="Burgers")
        self.product = Product.objects.create(
            store=self.store,
            category=self.category,
            name="X-Bacon",
            price=Decimal("28.00")
        )

    def test_create_additionals_and_removals_groups(self):
        """
        Testa a criação de grupos de adicionais (pagos) e de remoções (R$ 0,00),
        conforme requisito 11 do projeto.
        """
        # 1. Grupo de Adicionais
        group_adds = OptionGroup.objects.create(
            product=self.product,
            name="ADICIONAIS",
            description="Escolha até 3 adicionais",
            min_options=0,
            max_options=3
        )
        opt_bacon = OptionItem.objects.create(
            option_group=group_adds,
            name="Bacon",
            price=Decimal("5.00")
        )
        opt_queijo = OptionItem.objects.create(
            option_group=group_adds,
            name="Queijo",
            price=Decimal("3.00")
        )
        opt_ovo = OptionItem.objects.create(
            option_group=group_adds,
            name="Ovo",
            price=Decimal("2.00")
        )

        self.assertEqual(group_adds.items.count(), 3)
        self.assertEqual(opt_bacon.price, Decimal("5.00"))
        self.assertEqual(opt_queijo.price, Decimal("3.00"))
        self.assertEqual(opt_ovo.price, Decimal("2.00"))

        # 2. Grupo de Remoção de Ingredientes
        group_removals = OptionGroup.objects.create(
            product=self.product,
            name="REMOVER INGREDIENTES",
            description="Selecione o que deseja retirar",
            min_options=0,
            max_options=5
        )
        opt_sem_cebola = OptionItem.objects.create(
            option_group=group_removals,
            name="Sem cebola",
            price=Decimal("0.00")
        )
        opt_sem_tomate = OptionItem.objects.create(
            option_group=group_removals,
            name="Sem tomate",
            price=Decimal("0.00")
        )

        self.assertEqual(group_removals.items.count(), 2)
        self.assertEqual(opt_sem_cebola.price, Decimal("0.00"))
        self.assertEqual(opt_sem_tomate.price, Decimal("0.00"))


class CatalogMultiTenancyAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Lojista A
        self.user_a = User.objects.create_user(
            email='lojista_a@lanches.com',
            password='Password123!',
            full_name='Lojista A'
        )
        self.store_a = Store.objects.create(
            owner=self.user_a,
            name="Loja Alfa",
            whatsapp="11911110000"
        )
        StoreMembership.objects.create(
            user=self.user_a,
            store=self.store_a,
            role=StoreMembership.ROLE_OWNER
        )

        # Lojista B
        self.user_b = User.objects.create_user(
            email='lojista_b@lanches.com',
            password='Password123!',
            full_name='Lojista B'
        )
        self.store_b = Store.objects.create(
            owner=self.user_b,
            name="Loja Beta",
            whatsapp="11922220000"
        )
        StoreMembership.objects.create(
            user=self.user_b,
            store=self.store_b,
            role=StoreMembership.ROLE_OWNER
        )

    def test_merchant_can_create_category_and_product_in_own_store(self):
        """Lojista A consegue criar categorias e produtos na Loja A."""
        self.client.force_authenticate(user=self.user_a)

        # Cria Categoria
        cat_resp = self.client.post(
            f'/api/v1/catalog/merchant/{self.store_a.id}/categories/',
            {"name": "Sobremesas", "order": 1},
            format='json'
        )
        self.assertEqual(cat_resp.status_code, status.HTTP_201_CREATED)
        cat_id = cat_resp.data['id']

        # Cria Produto
        prod_resp = self.client.post(
            f'/api/v1/catalog/merchant/{self.store_a.id}/products/',
            {
                "category": cat_id,
                "name": "Pudim de Leite",
                "price": "12.00",
                "description": "Fatia generosa",
                "is_active": True
            },
            format='json'
        )
        self.assertEqual(prod_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(prod_resp.data['name'], "Pudim de Leite")

    def test_merchant_cannot_manage_catalog_of_another_store(self):
        """
        Lojista A NÃO pode criar ou listar categorias/produtos na Loja B (retorna 403 Forbidden).
        """
        self.client.force_authenticate(user=self.user_a)

        # Tenta listar categorias da Loja B
        list_resp = self.client.get(f'/api/v1/catalog/merchant/{self.store_b.id}/categories/')
        self.assertEqual(list_resp.status_code, status.HTTP_403_FORBIDDEN)

        # Tenta cadastrar categoria na Loja B
        create_resp = self.client.post(
            f'/api/v1/catalog/merchant/{self.store_b.id}/categories/',
            {"name": "Hacker Cat"},
            format='json'
        )
        self.assertEqual(create_resp.status_code, status.HTTP_403_FORBIDDEN)


class PublicStoreMenuAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email='dono@cardapio.com',
            password='Password123!',
            full_name='Dono Cardapio'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name="Lanchonete do Luiz",
            whatsapp="11999998888",
            is_active=True,
            is_open=True
        )

        # Categorias
        self.cat1 = Category.objects.create(store=self.store, name="Hambúrgueres", order=1)
        self.cat_inactive = Category.objects.create(store=self.store, name="Sazonais", order=2, is_active=False)

        # Produtos
        self.prod1 = Product.objects.create(
            store=self.store,
            category=self.cat1,
            name="X-Bacon",
            price=Decimal("28.00"),
            order=1,
            is_active=True
        )
        self.prod_inactive = Product.objects.create(
            store=self.store,
            category=self.cat1,
            name="Produto Esgotado",
            price=Decimal("20.00"),
            order=2,
            is_active=False
        )

        # Grupo de Adicionais
        self.group_adds = OptionGroup.objects.create(
            product=self.prod1,
            name="ADICIONAIS",
            min_options=0,
            max_options=3
        )
        OptionItem.objects.create(option_group=self.group_adds, name="Bacon Extra", price=Decimal("5.00"), is_available=True)
        OptionItem.objects.create(option_group=self.group_adds, name="Trufas (Esgotado)", price=Decimal("15.00"), is_available=False)

    def test_public_menu_endpoint_returns_nested_active_items_only(self):
        """
        Testa o endpoint público do cardápio digital por slug:
        - Acesso livre sem autenticação
        - Retorna dados da loja
        - Apenas categorias ativas
        - Apenas produtos ativos
        - Apenas opções disponíveis
        """
        response = self.client.get(f'/api/v1/catalog/public/{self.store.slug}/menu/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data
        self.assertEqual(data['store']['name'], "Lanchonete do Luiz")
        self.assertEqual(data['store']['slug'], "lanchonete-do-luiz")

        # Deve conter apenas 1 categoria ativa (ignora a inativa)
        categories = data['categories']
        self.assertEqual(len(categories), 1)
        self.assertEqual(categories[0]['name'], "Hambúrgueres")

        # Deve conter apenas 1 produto ativo (ignora o produto esgotado)
        products = categories[0]['products']
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]['name'], "X-Bacon")
        self.assertEqual(Decimal(str(products[0]['price'])), Decimal("28.00"))

        # Grupo de opções
        groups = products[0]['option_groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['name'], "ADICIONAIS")

        # Deve conter apenas o item disponível (ignora o indisponível)
        items = groups[0]['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['name'], "Bacon Extra")
        self.assertEqual(Decimal(str(items[0]['price'])), Decimal("5.00"))
