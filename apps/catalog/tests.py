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
        self.assertEqual(cat1.name, "🍔 Hambúrgueres")

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
        self.assertEqual(categories[0]['name'], "🍔 Hambúrgueres")

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

    def test_auto_category_icons_and_seed_catalog(self):
        """
        Testa o sistema inteligente de ícones automáticos de categorias:
        - Detecta palavras-chave e insere ícone apropriado
        - Preserva ícone customizado fornecido pelo lojista
        - Seeding em massa de categorias completas
        """
        from catalog.category_catalog import format_category_name_with_icon, seed_store_categories

        # Palavras-chave automáticas
        self.assertEqual(format_category_name_with_icon("Bolos Caseiros"), "🎂 Bolos Caseiros")
        self.assertEqual(format_category_name_with_icon("Bebidas Geladas"), "🥤 Bebidas Geladas")
        self.assertEqual(format_category_name_with_icon("Pizzas Especiais"), "🍕 Pizzas Especiais")
        self.assertEqual(format_category_name_with_icon("Marmitex"), "🍱 Marmitex")
        self.assertEqual(format_category_name_with_icon("Vinhos Finos"), "🍷 Vinhos Finos")
        self.assertEqual(format_category_name_with_icon("Pastel de Feira"), "🥟 Pastel de Feira")

        # Preserva emoji se já fornecido
        self.assertEqual(format_category_name_with_icon("⭐ Criações do Chef"), "⭐ Criações do Chef")

        # Teste de persistência no modelo
        cat_bolo = Category.objects.create(store=self.store, name="Bolos")
        self.assertEqual(cat_bolo.name, "🎂 Bolos")

        # Teste de seeding para a loja
        new_count = seed_store_categories(self.store)
        self.assertGreater(new_count, 30)
        # Verifica que o total de categorias na loja agora inclui os presets
        total_cats = Category.objects.filter(store=self.store).count()
        self.assertGreater(total_cats, 35)


class OptionCloningAndReuseTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='pizzaiolo@teste.com',
            password='Password123!',
            full_name='Pizzaiolo Mestre'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name="Pizzaria Napolitana",
            whatsapp="11977778888",
            is_active=True,
            is_open=True
        )
        self.category_pizzas = Category.objects.create(
            store=self.store,
            name="Pizzas"
        )
        # Pizza Família com 4 sabores e bordas
        self.pizza_familia = Product.objects.create(
            store=self.store,
            category=self.category_pizzas,
            name="Pizza Família 40cm",
            price=Decimal("70.00")
        )
        self.group_sabores = OptionGroup.objects.create(
            store=self.store,
            product=self.pizza_familia,
            name="Escolha 4 Sabores",
            min_options=4,
            max_options=4,
            is_required=True
        )
        self.item_calabresa = OptionItem.objects.create(
            option_group=self.group_sabores,
            name="Calabresa Especial",
            price=Decimal("0.00")
        )
        self.item_quatro_queijos = OptionItem.objects.create(
            option_group=self.group_sabores,
            name="Quatro Queijos",
            price=Decimal("0.00")
        )
        self.item_camarao = OptionItem.objects.create(
            option_group=self.group_sabores,
            name="Camarão Especial",
            price=Decimal("12.00")
        )

        self.group_borda = OptionGroup.objects.create(
            store=self.store,
            product=self.pizza_familia,
            name="Borda Recheada",
            min_options=0,
            max_options=1,
            is_required=False
        )
        self.item_catupiry = OptionItem.objects.create(
            option_group=self.group_borda,
            name="Catupiry Original",
            price=Decimal("9.00")
        )

        # Pizza Média que receberá a cópia
        self.pizza_media = Product.objects.create(
            store=self.store,
            category=self.category_pizzas,
            name="Pizza Média 30cm",
            price=Decimal("45.00")
        )

    def test_clone_single_group_with_custom_limits_and_item_filter(self):
        """
        Testa clonagem de grupo de opções permitindo:
        - Ajustar nome e limites (de 4 para 2 sabores)
        - Desmarcar itens indesejados (excluir Camarão)
        """
        from catalog.options_service import clone_option_group_to_product

        cloned_group = clone_option_group_to_product(
            source_group=self.group_sabores,
            target_product=self.pizza_media,
            new_name="Escolha até 2 Sabores",
            description="Selecione 2 sabores para sua pizza média",
            min_options=1,
            max_options=2,
            is_required=True,
            selected_item_ids=[self.item_calabresa.id, self.item_quatro_queijos.id]
        )

        self.assertEqual(cloned_group.product, self.pizza_media)
        self.assertEqual(cloned_group.name, "Escolha até 2 Sabores")
        self.assertEqual(cloned_group.min_options, 1)
        self.assertEqual(cloned_group.max_options, 2)
        self.assertTrue(cloned_group.is_required)

        # Apenas os 2 itens selecionados foram copiados (Camarão excluído)
        items = list(cloned_group.items.values_list('name', flat=True))
        self.assertEqual(len(items), 2)
        self.assertIn("Calabresa Especial", items)
        self.assertIn("Quatro Queijos", items)
        self.assertNotIn("Camarão Especial", items)

    def test_clone_all_product_groups(self):
        """
        Testa clonagem de TODOS os grupos e itens de uma pizza para outra.
        """
        from catalog.options_service import clone_all_product_groups

        grps_cnt, items_cnt = clone_all_product_groups(self.pizza_familia, self.pizza_media)
        self.assertEqual(grps_cnt, 2)
        self.assertEqual(items_cnt, 4)

        media_groups = self.pizza_media.option_groups.all()
        self.assertEqual(media_groups.count(), 2)

    def test_bulk_create_option_items_parsing(self):
        """
        Testa criação de itens em massa a partir de lista colada de texto,
        reconhecendo nomes e preços opcionais.
        """
        from catalog.options_service import bulk_create_option_items

        text_input = """
        Marguerita Clássica
        Portuguesa Suprema
        Frango com Catupiry (+ R$ 4,50)
        Nutella com Morango (+8.00)
        """
        added = bulk_create_option_items(self.group_sabores, text_input)
        self.assertEqual(added, 4)

        marguerita = OptionItem.objects.get(option_group=self.group_sabores, name="Marguerita Clássica")
        self.assertEqual(marguerita.price, Decimal("0.00"))

        frango = OptionItem.objects.get(option_group=self.group_sabores, name="Frango com Catupiry")
        self.assertEqual(frango.price, Decimal("4.50"))

        nutella = OptionItem.objects.get(option_group=self.group_sabores, name="Nutella com Morango")
        self.assertEqual(nutella.price, Decimal("8.00"))
