from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from stores.models import Store
from accounts.models import StoreMembership

User = get_user_model()


class StoreModelTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='dono@teste.com',
            password='Password123!',
            full_name='Dono Teste'
        )

    def test_store_auto_slug_generation(self):
        """Testa geração automática de slug limpo a partir do nome."""
        store = Store.objects.create(
            owner=self.owner,
            name="Hamburgueria Artesanal & Grill",
            whatsapp="11999990000"
        )
        self.assertEqual(store.slug, "hamburgueria-artesanal-grill")

    def test_store_slug_collision_resolution(self):
        """Testa que duas lojas com o mesmo nome recebem slugs únicos distintos."""
        store1 = Store.objects.create(
            owner=self.owner,
            name="Pizzaria Bella",
            whatsapp="11999990001"
        )
        store2 = Store.objects.create(
            owner=self.owner,
            name="Pizzaria Bella",
            whatsapp="11999990002"
        )
        self.assertEqual(store1.slug, "pizzaria-bella")
        self.assertEqual(store2.slug, "pizzaria-bella-2")


class StoreMultiTenancyIsolationTest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Cria Lojista A e sua Loja A
        self.user_a = User.objects.create_user(
            email='lojista_a@email.com',
            password='Password123!',
            full_name='Lojista A'
        )
        self.store_a = Store.objects.create(
            owner=self.user_a,
            name="Restaurante Alfa",
            whatsapp="11900000001"
        )
        StoreMembership.objects.create(
            user=self.user_a,
            store=self.store_a,
            role=StoreMembership.ROLE_OWNER
        )

        # Cria Lojista B e sua Loja B
        self.user_b = User.objects.create_user(
            email='lojista_b@email.com',
            password='Password123!',
            full_name='Lojista B'
        )
        self.store_b = Store.objects.create(
            owner=self.user_b,
            name="Restaurante Beta",
            whatsapp="11900000002"
        )
        StoreMembership.objects.create(
            user=self.user_b,
            store=self.store_b,
            role=StoreMembership.ROLE_OWNER
        )

    def test_merchant_cannot_list_another_store(self):
        """
        O Lojista A autenticado NÃO pode ver a Loja B na listagem de suas lojas.
        """
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get('/api/v1/stores/merchant/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        store_ids = [item['id'] for item in response.data['results'] if 'results' in response.data] or [item['id'] for item in response.data]
        self.assertIn(self.store_a.id, store_ids)
        self.assertNotIn(self.store_b.id, store_ids)

    def test_merchant_cannot_access_or_edit_another_store_detail(self):
        """
        O Lojista A autenticado NÃO consegue acessar ou editar os detalhes da Loja B (retorna 403 Forbidden).
        """
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(f'/api/v1/stores/merchant/{self.store_b.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Tentativa de edição maliciosa
        edit_response = self.client.patch(
            f'/api/v1/stores/merchant/{self.store_b.id}/',
            {'name': 'Tentativa de Invasão'},
            format='json'
        )
        self.assertEqual(edit_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_public_store_detail_by_slug(self):
        """
        Qualquer cliente pode acessar dados públicos da loja pelo slug sem autenticação.
        """
        response = self.client.get(f'/api/v1/stores/public/{self.store_a.slug}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], "Restaurante Alfa")
        self.assertEqual(response.data['slug'], "restaurante-alfa")
        # Documento fiscal não deve ser exposto na API pública
        self.assertNotIn('document', response.data)


class StoreBusinessHoursAndStatusTest(TestCase):
    def setUp(self):
        import datetime
        from stores.models import BusinessHour

        self.client = APIClient()
        self.owner = User.objects.create_user(
            email='hora_dono@teste.com',
            password='Password123!',
            full_name='Hora Dono'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name="Hamburgueria Noturna",
            whatsapp="11988887777",
            is_active=True,
            is_open=False,
            is_paused=False
        )
        StoreMembership.objects.create(
            user=self.owner,
            store=self.store,
            role=StoreMembership.ROLE_OWNER
        )

        # Configura horário de Quarta-feira das 18:00 às 23:00
        BusinessHour.objects.create(
            store=self.store,
            weekday=2,  # 2 = Quarta-feira
            opening_time=datetime.time(18, 0),
            closing_time=datetime.time(23, 0),
            is_closed=False
        )

    def test_store_open_within_schedule(self):
        """Dentro do horário configurado, a loja é calculada como aberta."""
        import datetime
        # Simula Quarta-feira às 20h
        wednesday_20h = datetime.datetime(2026, 9, 23, 20, 0)
        self.assertTrue(self.store.is_currently_open(at_datetime=wednesday_20h))

    def test_store_closed_outside_schedule(self):
        """Fora do horário configurado, a loja é calculada como fechada."""
        import datetime
        # Simula Quarta-feira às 15h
        wednesday_15h = datetime.datetime(2026, 9, 23, 15, 0)
        self.assertFalse(self.store.is_currently_open(at_datetime=wednesday_15h))

    def test_store_closed_when_paused_even_in_schedule(self):
        """Quando o lojista aciona o botão de pausa, a loja fecha imediatamente."""
        import datetime
        self.store.is_paused = True
        self.store.save()

        wednesday_20h = datetime.datetime(2026, 9, 23, 20, 0)
        self.assertFalse(self.store.is_currently_open(at_datetime=wednesday_20h))

    def test_merchant_toggle_status_endpoint(self):
        """Lojista altera status manual e pausa via API."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(
            f'/api/v1/stores/merchant/{self.store.id}/toggle-status/',
            {"is_paused": True},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_paused'])
        self.assertEqual(response.data['status_label'], "Pausada")


class PublicMenuPageViewTest(TestCase):
    def setUp(self):
        from catalog.models import Category, Product, OptionGroup, OptionItem
        from decimal import Decimal

        self.owner = User.objects.create_user(
            email='public_dono@lanches.com',
            password='Password123!',
            full_name='Public Dono'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name="Lanchonete Central",
            whatsapp="11988889999",
            is_active=True,
            is_open=True
        )
        self.cat = Category.objects.create(store=self.store, name="Burgers Clássicos")
        self.prod = Product.objects.create(
            store=self.store,
            category=self.cat,
            name="Super X-Burger",
            price=Decimal("26.00"),
            description="Blend 160g e queijo cheddar"
        )
        self.opt_group = OptionGroup.objects.create(
            product=self.prod,
            name="Adicionais Especiais",
            min_options=0,
            max_options=2
        )
        OptionItem.objects.create(
            option_group=self.opt_group,
            name="Bacon Extra",
            price=Decimal("4.50")
        )

        self.inactive_store = Store.objects.create(
            owner=self.owner,
            name="Loja Desativada",
            whatsapp="11900001111",
            is_active=False
        )

    def test_render_public_store_menu_page_success(self):
        """
        Consumidor acessa a URL pública /{store_slug}/:
        - Retorna status 200
        - Carrega o template stores/public_menu.html
        - Exibe o nome da loja, status, categoria e produtos
        """
        response = self.client.get(f'/{self.store.slug}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(response, 'stores/public_menu.html')
        self.assertContains(response, "Lanchonete Central")
        self.assertContains(response, "Burgers Clássicos")
        self.assertContains(response, "Super X-Burger")
        self.assertContains(response, "store-catalog-data")
        self.assertContains(response, "cart.js")

    def test_render_public_store_menu_page_inactive_store_returns_404(self):
        """Loja desativada retorna 404."""
        response = self.client.get(f'/{self.inactive_store.slug}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_render_public_store_menu_page_unknown_slug_returns_404(self):
        """Slug inexistente retorna 404."""
        response = self.client.get('/slug-inexistente-12345/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
