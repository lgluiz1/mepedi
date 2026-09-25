from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework import status

from stores.models import Store
from accounts.models import StoreMembership
from catalog.models import Category, Product, OptionGroup, OptionItem
from customers.models import Customer
from delivery.models import DeliveryZone
from orders.models import Order, OrderItem, OrderItemOption
from orders.services import OrderService

User = get_user_model()


class OrderServiceCreationAndRecalculationTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='chef@pedidos.com',
            password='Password123!',
            full_name='Chef Pedidos'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name="Hamburgueria do Bairro",
            whatsapp="11999990000",
            is_active=True,
            is_open=True,
            minimum_order_value=Decimal("20.00")
        )
        self.cat = Category.objects.create(store=self.store, name="Burgers")
        self.prod = Product.objects.create(
            store=self.store,
            category=self.cat,
            name="Monster Burger",
            price=Decimal("30.00")
        )
        self.group = OptionGroup.objects.create(
            product=self.prod,
            name="Adicionais",
            min_options=0,
            max_options=3
        )
        self.opt_bacon = OptionItem.objects.create(
            option_group=self.group,
            name="Bacon Crocante",
            price=Decimal("5.00")
        )
        self.opt_queijo = OptionItem.objects.create(
            option_group=self.group,
            name="Queijo Cheddar",
            price=Decimal("3.00")
        )

        self.zone = DeliveryZone.objects.create(
            store=self.store,
            name="Bairros Próximos",
            neighborhoods="Centro, Jardins",
            fee=Decimal("8.00")
        )

    def test_order_creation_with_server_side_price_recalculation(self):
        """
        Garante que o backend recalcula os preços com base nos registros do banco:
        - Monster Burger (R$ 30,00)
        - + Bacon (R$ 5,00)
        - + Queijo (R$ 3,00)
        - Preço unitário com adicionais = R$ 38,00
        - Quantidade = 2 ➔ Subtotal = R$ 76,00
        - Frete para 'Centro' = R$ 8,00
        - Total Final = R$ 84,00
        """
        items_payload = [
            {
                "product_id": self.prod.id,
                "quantity": 2,
                "notes": "Bem passado",
                "options": [{"id": self.opt_bacon.id}, {"id": self.opt_queijo.id}]
            }
        ]
        address_payload = {
            "street": "Rua das Flores",
            "number": "123",
            "neighborhood": "Centro"
        }
        customer_payload = {
            "name": "Cliente VIP",
            "phone": "11988881234"
        }

        order = OrderService.create_order(
            store=self.store,
            customer_payload=customer_payload,
            delivery_type=Order.TYPE_DELIVERY,
            address_payload=address_payload,
            payment_method=Order.PAY_PIX,
            items_payload=items_payload
        )

        self.assertEqual(order.order_number, 1001)
        self.assertEqual(order.subtotal, Decimal("76.00"))
        self.assertEqual(order.delivery_fee, Decimal("8.00"))
        self.assertEqual(order.total, Decimal("84.00"))
        self.assertEqual(order.items.count(), 1)

        item = order.items.first()
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.unit_price, Decimal("30.00"))
        self.assertEqual(item.total, Decimal("76.00"))
        self.assertEqual(item.selected_options.count(), 2)

        # Valida que as métricas do cliente foram atualizadas
        customer = order.customer
        self.assertEqual(customer.orders_count, 1)
        self.assertEqual(customer.total_spent, Decimal("84.00"))

    def test_order_number_increments_sequentially_per_store(self):
        """Testa geração de numeração sequencial #1001, #1002."""
        items = [{"product_id": self.prod.id, "quantity": 1, "options": []}]
        cust = {"name": "Cliente 1", "phone": "11911112222"}

        order1 = OrderService.create_order(
            store=self.store,
            customer_payload=cust,
            delivery_type=Order.TYPE_PICKUP,
            items_payload=items
        )
        order2 = OrderService.create_order(
            store=self.store,
            customer_payload=cust,
            delivery_type=Order.TYPE_PICKUP,
            items_payload=items
        )

        self.assertEqual(order1.order_number, 1001)
        self.assertEqual(order2.order_number, 1002)

    def test_order_blocked_when_store_is_closed_or_paused(self):
        """Loja fechada ou pausada bloqueia a criação do pedido."""
        self.store.is_paused = True
        self.store.save()

        items = [{"product_id": self.prod.id, "quantity": 1}]
        cust = {"name": "Cliente Teste", "phone": "11988880000"}

        with self.assertRaises(ValidationError):
            OrderService.create_order(
                store=self.store,
                customer_payload=cust,
                delivery_type=Order.TYPE_PICKUP,
                items_payload=items
            )

    def test_order_blocked_when_below_minimum_order_value(self):
        """Pedido com valor menor que o mínimo configurado da loja deve falhar."""
        self.store.minimum_order_value = Decimal("50.00")
        self.store.save()

        items = [{"product_id": self.prod.id, "quantity": 1, "options": []}]  # Total R$ 30,00 < R$ 50,00
        cust = {"name": "Cliente", "phone": "11977770000"}

        with self.assertRaises(ValidationError):
            OrderService.create_order(
                store=self.store,
                customer_payload=cust,
                delivery_type=Order.TYPE_PICKUP,
                items_payload=items
            )


class OrderMultiTenancyIsolationTest(TestCase):
    """
    TESTE CRÍTICO (Requisito 23):
    Comprova que a LOJA A não consegue acessar os PEDIDOS da LOJA B.
    """
    def setUp(self):
        self.client = APIClient()

        # Loja A
        self.user_a = User.objects.create_user(email='lojista_a@pedidos.com', password='Password123!', full_name='Loj A')
        self.store_a = Store.objects.create(owner=self.user_a, name="Loja Alfa", whatsapp="11911110001", is_active=True, is_open=True)
        StoreMembership.objects.create(user=self.user_a, store=self.store_a, role=StoreMembership.ROLE_OWNER)
        self.cust_a = Customer.objects.create(store=self.store_a, name="Cliente Loja A", phone="11911112222")

        # Loja B
        self.user_b = User.objects.create_user(email='lojista_b@pedidos.com', password='Password123!', full_name='Loj B')
        self.store_b = Store.objects.create(owner=self.user_b, name="Loja Beta", whatsapp="11922220002", is_active=True, is_open=True)
        StoreMembership.objects.create(user=self.user_b, store=self.store_b, role=StoreMembership.ROLE_OWNER)
        self.cust_b = Customer.objects.create(store=self.store_b, name="Cliente Loja B", phone="11922223333")

        # Pedido da Loja B
        self.order_b = Order.objects.create(
            store=self.store_b,
            customer=self.cust_b,
            order_number=1001,
            subtotal=Decimal("45.00"),
            total=Decimal("45.00"),
            delivery_type=Order.TYPE_PICKUP,
            status=Order.STATUS_NEW
        )

    def test_merchant_a_cannot_list_or_view_order_of_store_b(self):
        """
        O Lojista da Loja A autenticado tenta listar ou acessar o pedido da Loja B.
        O sistema deve bloquear com 403 Forbidden.
        """
        self.client.force_authenticate(user=self.user_a)

        # 1. Tentativa de listar pedidos da Loja B
        list_resp = self.client.get(f'/api/v1/orders/merchant/{self.store_b.id}/')
        self.assertEqual(list_resp.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Tentativa de ver detalhes do pedido da Loja B
        detail_resp = self.client.get(f'/api/v1/orders/merchant/{self.store_b.id}/{self.order_b.id}/')
        self.assertEqual(detail_resp.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Tentativa de alterar status do pedido da Loja B
        update_resp = self.client.patch(
            f'/api/v1/orders/merchant/{self.store_b.id}/{self.order_b.id}/status/',
            {"status": "ACEITO"},
            format='json'
        )
        self.assertEqual(update_resp.status_code, status.HTTP_403_FORBIDDEN)


class PublicOrderAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(email='dono@api.com', password='Password123!', full_name='Dono API')
        self.store = Store.objects.create(
            owner=self.owner,
            name="Hamburgueria API",
            whatsapp="11988887777",
            is_active=True,
            is_open=True
        )
        StoreMembership.objects.create(user=self.owner, store=self.store, role=StoreMembership.ROLE_OWNER)

        self.cat = Category.objects.create(store=self.store, name="Lanches")
        self.prod = Product.objects.create(
            store=self.store,
            category=self.cat,
            name="Smash Burger",
            price=Decimal("22.00")
        )

    def test_public_create_order_endpoint_and_tracking(self):
        """
        Testa o fluxo completo pela API:
        1. Cliente sem conta submete pedido na URL pública da loja.
        2. Retorna 201 com o pedido criado e seu UUID público.
        3. Cliente consulta o status do pedido pelo UUID.
        4. Lojista atualiza o status para 'ACEITO'.
        """
        payload = {
            "customer": {
                "name": "João da Silva",
                "phone": "(11) 98765-4321"
            },
            "delivery_type": "PICKUP",
            "payment_method": "PIX",
            "items": [
                {
                    "product_id": self.prod.id,
                    "quantity": 2,
                    "notes": "Sem picles"
                }
            ]
        }

        # 1. Criação do pedido
        response = self.client.post(
            f'/api/v1/orders/public/{self.store.slug}/',
            payload,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['order_number'], 1001)
        self.assertEqual(Decimal(response.data['total']), Decimal("44.00"))
        public_id = response.data['public_id']
        order_id = response.data['id']

        # 2. Cliente consulta status pelo UUID público
        track_resp = self.client.get(f'/api/v1/orders/public/status/{public_id}/')
        self.assertEqual(track_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(track_resp.data['status'], "NOVO")

        # 3. Lojista autenticado atualiza status para 'ACEITO'
        self.client.force_authenticate(user=self.owner)
        status_resp = self.client.patch(
            f'/api/v1/orders/merchant/{self.store.id}/{order_id}/status/',
            {"status": "ACEITO"},
            format='json'
        )
        self.assertEqual(status_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(status_resp.data['status'], "ACEITO")


class MerchantDashboardTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='dono@pizzaria.com',
            password='secretpassword123',
            full_name='Dono Pizzaria'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name='Pizzaria do Bairro',
            slug='pizzaria-do-bairro',
            whatsapp='(11) 98888-7777',
            is_active=True,
            is_open=True
        )
        StoreMembership.objects.create(
            user=self.owner,
            store=self.store,
            role='owner',
            is_active=True
        )

        # Outra loja de outro dono para testar isolamento
        self.other_owner = User.objects.create_user(
            email='outro@loja.com',
            password='secretpassword123',
            full_name='Outro Dono'
        )
        self.other_store = Store.objects.create(
            owner=self.other_owner,
            name='Hamburgueria Rival',
            slug='hamburgueria-rival',
            whatsapp='(11) 96666-5555',
            is_active=True,
            is_open=True
        )
        StoreMembership.objects.create(
            user=self.other_owner,
            store=self.other_store,
            role='owner',
            is_active=True
        )

    def test_unauthenticated_user_redirected_to_login(self):
        """Usuário não logado ao acessar o painel é redirecionado para o login."""
        response = self.client.get('/painel/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/painel/login/', response['Location'])

    def test_merchant_login_flow(self):
        """Testa tentativa de login com credenciais inválidas e válidas."""
        # Inválidas
        bad_resp = self.client.post('/painel/login/', {
            'email': 'dono@pizzaria.com',
            'password': 'wrongpassword'
        })
        self.assertEqual(bad_resp.status_code, 200)
        self.assertContains(bad_resp, 'E-mail ou senha inválidos')

        # Válidas
        good_resp = self.client.post('/painel/login/', {
            'email': 'dono@pizzaria.com',
            'password': 'secretpassword123'
        })
        self.assertEqual(good_resp.status_code, 302)
        self.assertEqual(good_resp['Location'], '/painel/')

    def test_merchant_dashboard_root_redirects_to_first_store(self):
        """Lojista logado acessando /painel/ é redirecionado para a loja ativa."""
        self.client.login(username='dono@pizzaria.com', password='secretpassword123')
        response = self.client.get('/painel/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f'/painel/{self.store.slug}/')

    def test_merchant_dashboard_view_renders_store_orders(self):
        """Lojista acessando o painel de sua loja recebe 200 com os dados da loja."""
        self.client.login(username='dono@pizzaria.com', password='secretpassword123')
        response = self.client.get(f'/painel/{self.store.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pizzaria do Bairro')
        self.assertContains(response, 'Painel de Pedidos')

    def test_merchant_cross_store_isolation_forbidden(self):
        """Lojista A tentando acessar o painel da Loja B recebe 403 Forbidden."""
        self.client.login(username='dono@pizzaria.com', password='secretpassword123')
        response = self.client.get(f'/painel/{self.other_store.slug}/')
        self.assertEqual(response.status_code, 403)

    def test_merchant_store_settings_view_get_and_post(self):
        """Lojista consegue visualizar e atualizar configurações e identidade visual da loja."""
        self.client.login(username='dono@pizzaria.com', password='secretpassword123')
        get_resp = self.client.get(f'/painel/{self.store.slug}/configuracoes/')
        self.assertEqual(get_resp.status_code, 200)
        self.assertContains(get_resp, 'Identidade Visual')

        # Atualiza configurações
        post_resp = self.client.post(f'/painel/{self.store.slug}/configuracoes/', {
            'name': 'Pizzaria do Bairro Atualizada',
            'description': 'Nova descrição da pizzaria',
            'whatsapp': '5511999998888',
            'phone': '1133334444',
            'allows_delivery': 'on',
            'allows_pickup': 'on',
            'estimated_delivery_time_min': '25',
            'estimated_delivery_time_max': '50',
        })
        self.assertEqual(post_resp.status_code, 200)
        self.store.refresh_from_db()
        self.assertEqual(self.store.name, 'Pizzaria do Bairro Atualizada')
        self.assertEqual(self.store.description, 'Nova descrição da pizzaria')

    def test_merchant_products_crud_lifecycle(self):
        """Lojista gerencia produtos (criação, listagem e exclusão) via painel."""
        self.client.login(username='dono@pizzaria.com', password='secretpassword123')
        cat = Category.objects.create(store=self.store, name="Pizzas Salgadas")

        # 1. Cria produto
        create_resp = self.client.post(f'/painel/{self.store.slug}/produtos/', {
            'action': 'create',
            'name': 'Pizza Margherita Especial',
            'category': str(cat.id),
            'price': '45,90',
            'description': 'Molho de tomate fresco, mussarela e manjericão',
            'is_active': 'on'
        })
        self.assertEqual(create_resp.status_code, 200)
        product = Product.objects.filter(store=self.store, name='Pizza Margherita Especial').first()
        self.assertIsNotNone(product)
        self.assertEqual(product.price, Decimal('45.90'))

        # 2. Toggle status
        toggle_resp = self.client.post(f'/painel/{self.store.slug}/produtos/', {
            'action': 'toggle',
            'product_id': str(product.id)
        })
        self.assertEqual(toggle_resp.status_code, 200)
        product.refresh_from_db()
        self.assertFalse(product.is_active)

        # 3. Exclui produto
        del_resp = self.client.post(f'/painel/{self.store.slug}/produtos/', {
            'action': 'delete',
            'product_id': str(product.id)
        })
        self.assertEqual(del_resp.status_code, 200)
        self.assertFalse(Product.objects.filter(id=product.id).exists())


