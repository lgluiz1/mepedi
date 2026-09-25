from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User, StoreMembership
from stores.models import Store
from catalog.models import Category, Product, OptionGroup, OptionItem
from delivery.models import DeliveryZone
from customers.models import Customer
from orders.models import Order
from orders.services import OrderService


class PlatformEndToEndLifecycleTests(TestCase):
    """
    Teste de integração ponta a ponta (E2E) simulando o ciclo completo do SaaS:
    1. Cadastro do lojista e da loja.
    2. Configuração de catálogo, adicionais, zonas de frete e abertura.
    3. Experiência do cliente: navegação no cardápio, cálculo de frete e checkout.
    4. Geração de comanda para WhatsApp e acompanhamento.
    5. Gestão de pedidos no painel do lojista e avanço de status.
    """
    def setUp(self):
        self.client = Client()
        self.api_client = APIClient()

        # 1. Onboarding de dois lojistas distintos para validação simultânea
        self.owner_a = User.objects.create_user(
            email='mario@pizzaria.com',
            password='Password123!',
            full_name='Mario Rossi'
        )
        self.store_a = Store.objects.create(
            owner=self.owner_a,
            name='Pizzaria Bella',
            slug='pizzaria-bella',
            whatsapp='(11) 98765-4321',
            is_active=True,
            is_open=True,
            minimum_order_value=Decimal('30.00')
        )
        StoreMembership.objects.create(
            user=self.owner_a,
            store=self.store_a,
            role='owner',
            is_active=True
        )

        self.owner_b = User.objects.create_user(
            email='bob@burgers.com',
            password='Password123!',
            full_name='Bob Burger'
        )
        self.store_b = Store.objects.create(
            owner=self.owner_b,
            name='Burger House',
            slug='burger-house',
            whatsapp='(11) 91111-2222',
            is_active=True,
            is_open=True,
            minimum_order_value=Decimal('20.00')
        )
        StoreMembership.objects.create(
            user=self.owner_b,
            store=self.store_b,
            role='owner',
            is_active=True
        )

        # 2. Configuração do catálogo da Loja A
        self.cat_a = Category.objects.create(
            store=self.store_a,
            name='Pizzas Especiais',
            order=1
        )
        self.prod_a = Product.objects.create(
            store=self.store_a,
            category=self.cat_a,
            name='Calabresa Premium',
            price=Decimal('50.00'),
            is_active=True
        )
        self.group_bordas = OptionGroup.objects.create(
            product=self.prod_a,
            name='Bordas Especiais',
            min_options=0,
            max_options=1
        )
        self.opt_catupiry = OptionItem.objects.create(
            option_group=self.group_bordas,
            name='Catupiry Original',
            price=Decimal('10.00'),
            is_available=True
        )
        self.group_remocoes = OptionGroup.objects.create(
            product=self.prod_a,
            name='Ingredientes',
            min_options=0,
            max_options=2
        )
        self.opt_sem_cebola = OptionItem.objects.create(
            option_group=self.group_remocoes,
            name='Sem Cebola',
            price=Decimal('0.00'),
            is_available=True
        )

        # Configuração de entrega da Loja A
        self.zone_a = DeliveryZone.objects.create(
            store=self.store_a,
            name='Zona Sul',
            fee=Decimal('8.00'),
            neighborhoods='Centro, Jardins, Bela Vista',
            is_active=True
        )

    def test_complete_saas_lifecycle_e2e(self):
        # Passo 1: Cliente acessa o cardápio público da Loja A via SSR
        menu_response = self.client.get(f'/{self.store_a.slug}/')
        self.assertEqual(menu_response.status_code, 200)
        self.assertContains(menu_response, 'Pizzaria Bella')
        self.assertContains(menu_response, 'Calabresa Premium')

        # Passo 2: Cliente consulta endpoint REST do cardápio
        api_menu = self.api_client.get(f'/api/v1/catalog/public/{self.store_a.slug}/menu/')
        self.assertEqual(api_menu.status_code, 200)
        self.assertEqual(len(api_menu.data['categories']), 1)
        self.assertEqual(api_menu.data['categories'][0]['products'][0]['name'], 'Calabresa Premium')

        # Passo 3: Cliente calcula taxa de frete para seu bairro
        fee_resp = self.api_client.post(
            f'/api/v1/delivery/public/{self.store_a.slug}/calculate-fee/',
            {'neighborhood': 'Jardins'},
            format='json'
        )
        self.assertEqual(fee_resp.status_code, 200)
        self.assertTrue(fee_resp.data['matched'])
        self.assertEqual(Decimal(str(fee_resp.data['delivery_fee'])), Decimal('8.00'))

        # Passo 4: Cliente identifica-se e finaliza o pedido (Checkout)
        order_payload = {
            'customer': {
                'name': 'Ana Silva',
                'phone': '(11) 99887-7665'
            },
            'delivery_type': 'DELIVERY',
            'payment_method': 'MONEY',
            'change_for': '100.00',
            'address': {
                'street': 'Av. Paulista',
                'number': '1000',
                'neighborhood': 'Jardins',
                'city': 'São Paulo',
                'state': 'SP',
                'reference': 'Apto 42'
            },
            'items': [
                {
                    'product_id': self.prod_a.id,
                    'quantity': 1,
                    'notes': 'Bem assada',
                    'options': [
                        {'id': self.opt_catupiry.id},
                        {'id': self.opt_sem_cebola.id}
                    ]
                }
            ],
            'notes': 'Portão branco'
        }

        checkout_resp = self.api_client.post(
            f'/api/v1/orders/public/{self.store_a.slug}/',
            order_payload,
            format='json'
        )
        self.assertEqual(checkout_resp.status_code, 201)
        created_order = checkout_resp.data
        self.assertEqual(created_order['order_number'], 1001)
        # Recálculo Server-Side: 50.00 (produto) + 10.00 (adicional) + 8.00 (frete) = 68.00
        self.assertEqual(Decimal(str(created_order['total'])), Decimal('68.00'))
        public_id = created_order['public_id']
        order_id = created_order['id']

        # Passo 5: Cliente consulta página de status e link do WhatsApp
        status_page = self.client.get(f'/{self.store_a.slug}/pedidos/{public_id}/')
        self.assertEqual(status_page.status_code, 200)
        self.assertContains(status_page, '#1001')
        self.assertContains(status_page, 'Novo')

        wa_redirect = self.client.get(f'/{self.store_a.slug}/pedidos/{public_id}/whatsapp/')
        self.assertEqual(wa_redirect.status_code, 302)
        self.assertTrue(wa_redirect['Location'].startswith('https://wa.me/5511987654321?text='))

        # Passo 6: Lojista faz login no painel e acompanha o pedido
        self.client.login(username='mario@pizzaria.com', password='Password123!')
        dash_resp = self.client.get(f'/painel/{self.store_a.slug}/')
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, '#1001')
        self.assertContains(dash_resp, 'Ana Silva')

        # Passo 7: Lojista avança status do pedido na API do painel
        self.api_client.force_authenticate(user=self.owner_a)

        # Transição: NOVO -> ACEITO
        step1 = self.api_client.patch(
            f'/api/v1/orders/merchant/{self.store_a.id}/{order_id}/status/',
            {'status': 'ACEITO'},
            format='json'
        )
        self.assertEqual(step1.status_code, 200)
        self.assertEqual(step1.data['status'], 'ACEITO')

        # Transição: ACEITO -> EM_PREPARACAO
        step2 = self.api_client.patch(
            f'/api/v1/orders/merchant/{self.store_a.id}/{order_id}/status/',
            {'status': 'EM_PREPARACAO'},
            format='json'
        )
        self.assertEqual(step2.status_code, 200)
        self.assertEqual(step2.data['status'], 'EM_PREPARACAO')

        # Transição: EM_PREPARACAO -> PRONTO
        step3 = self.api_client.patch(
            f'/api/v1/orders/merchant/{self.store_a.id}/{order_id}/status/',
            {'status': 'PRONTO'},
            format='json'
        )
        self.assertEqual(step3.status_code, 200)
        self.assertEqual(step3.data['status'], 'PRONTO')

        # Transição: PRONTO -> SAIU_PARA_ENTREGA
        step4 = self.api_client.patch(
            f'/api/v1/orders/merchant/{self.store_a.id}/{order_id}/status/',
            {'status': 'SAIU_PARA_ENTREGA'},
            format='json'
        )
        self.assertEqual(step4.status_code, 200)
        self.assertEqual(step4.data['status'], 'SAIU_PARA_ENTREGA')

        # Transição: SAIU_PARA_ENTREGA -> CONCLUIDO
        step5 = self.api_client.patch(
            f'/api/v1/orders/merchant/{self.store_a.id}/{order_id}/status/',
            {'status': 'CONCLUIDO'},
            format='json'
        )
        self.assertEqual(step5.status_code, 200)
        self.assertEqual(step5.data['status'], 'CONCLUIDO')

        # Valida que o status final está gravado no banco de dados
        order_in_db = Order.objects.get(id=order_id)
        self.assertEqual(order_in_db.status, Order.STATUS_COMPLETED)


class MultiTenantSecurityAuditTests(TestCase):
    """
    Auditoria e testes de segurança rigorosos para isolamento multi-loja:
    Garante que a Loja A JAMAIS pode visualizar, editar ou manipular dados da Loja B.
    """
    def setUp(self):
        self.client = Client()
        self.api_client = APIClient()

        # Loja A
        self.owner_a = User.objects.create_user(
            email='loja_a@teste.com',
            password='Password123!',
            full_name='Proprietário A'
        )
        self.store_a = Store.objects.create(
            owner=self.owner_a,
            name='Loja A',
            slug='loja-a',
            whatsapp='11999990001',
            is_active=True,
            is_open=True,
            minimum_order_value=Decimal('25.00')
        )
        StoreMembership.objects.create(user=self.owner_a, store=self.store_a, role='owner', is_active=True)

        self.cat_a = Category.objects.create(store=self.store_a, name='Categoria Loja A')
        self.prod_a = Product.objects.create(store=self.store_a, category=self.cat_a, name='Produto Loja A', price=Decimal('30.00'))

        self.customer_a = Customer.objects.create(store=self.store_a, name='Cliente A', phone='11911111111')
        self.order_a = Order.objects.create(
            store=self.store_a,
            customer=self.customer_a,
            order_number=1001,
            total=Decimal('30.00')
        )

        # Loja B
        self.owner_b = User.objects.create_user(
            email='loja_b@teste.com',
            password='Password123!',
            full_name='Proprietário B'
        )
        self.store_b = Store.objects.create(
            owner=self.owner_b,
            name='Loja B',
            slug='loja-b',
            whatsapp='11999990002',
            is_active=True,
            is_open=True,
            minimum_order_value=Decimal('20.00')
        )
        StoreMembership.objects.create(user=self.owner_b, store=self.store_b, role='owner', is_active=True)

        self.cat_b = Category.objects.create(store=self.store_b, name='Categoria Loja B')

    def test_merchant_b_cannot_view_merchant_a_dashboard(self):
        """Lojista B autenticado não pode acessar o painel web da Loja A (403 Forbidden)."""
        self.client.login(username='loja_b@teste.com', password='Password123!')
        response = self.client.get(f'/painel/{self.store_a.slug}/')
        self.assertEqual(response.status_code, 403)

    def test_merchant_b_cannot_list_merchant_a_orders_via_api(self):
        """Lojista B não pode listar pedidos da Loja A via API REST (403 Forbidden)."""
        self.api_client.force_authenticate(user=self.owner_b)
        response = self.api_client.get(f'/api/v1/orders/merchant/{self.store_a.id}/')
        self.assertEqual(response.status_code, 403)

    def test_merchant_b_cannot_modify_merchant_a_order_status(self):
        """Lojista B não pode alterar o status de um pedido da Loja A (403 Forbidden)."""
        self.api_client.force_authenticate(user=self.owner_b)
        response = self.api_client.patch(
            f'/api/v1/orders/merchant/{self.store_a.id}/{self.order_a.id}/status/',
            {'status': 'CONCLUIDO'},
            format='json'
        )
        self.assertEqual(response.status_code, 403)
        self.order_a.refresh_from_db()
        self.assertNotEqual(self.order_a.status, 'CONCLUIDO')

    def test_cross_store_category_linking_rejected(self):
        """Lojista B tentando criar produto na Loja B apontando para Categoria da Loja A é rejeitado (400 Bad Request)."""
        self.api_client.force_authenticate(user=self.owner_b)
        response = self.api_client.post(
            f'/api/v1/catalog/merchant/{self.store_b.id}/products/',
            {
                'category': self.cat_a.id, # Categoria pertence à Loja A!
                'name': 'Hambúrguer Inválido',
                'price': '25.00'
            },
            format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('A categoria selecionada não pertence a esta loja.', str(response.data))

    def test_order_creation_blocked_when_store_is_paused(self):
        """Tentativa de criar pedido em loja com pedidos pausados deve falhar com 400."""
        self.store_a.is_paused = True
        self.store_a.save()

        payload = {
            'customer': {'name': 'Teste', 'phone': '11988887777'},
            'delivery_type': 'PICKUP',
            'payment_method': 'PIX',
            'items': [{'product_id': self.prod_a.id, 'quantity': 1}]
        }
        response = self.api_client.post(
            f'/api/v1/orders/public/{self.store_a.slug}/',
            payload,
            format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('pausado', str(response.data).lower())

    def test_order_creation_blocked_when_subtotal_below_minimum(self):
        """Tentativa de submeter pedido abaixo do valor mínimo da loja deve falhar com 400."""
        # Loja A exige valor mínimo de R$ 25.00
        cheap_prod = Product.objects.create(
            store=self.store_a,
            category=self.cat_a,
            name='Brigadeiro',
            price=Decimal('5.00')
        )
        payload = {
            'customer': {'name': 'Teste', 'phone': '11988887777'},
            'delivery_type': 'PICKUP',
            'payment_method': 'PIX',
            'items': [{'product_id': cheap_prod.id, 'quantity': 1}] # Total R$ 5,00 < R$ 25,00
        }
        response = self.api_client.post(
            f'/api/v1/orders/public/{self.store_a.slug}/',
            payload,
            format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('mínimo', str(response.data).lower())
