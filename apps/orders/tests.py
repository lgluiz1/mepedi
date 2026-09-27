from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework import status

from datetime import timedelta
from django.utils import timezone

from stores.models import Store
from accounts.models import StoreMembership
from catalog.models import Category, Product, OptionGroup, OptionItem, StockMovement
from catalog.services import StockService
from customers.models import Customer
from delivery.models import DeliveryZone
from orders.models import Order, OrderItem, OrderItemOption, Coupon, Table, TableSession
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

        # Atualiza configurações com pedido mínimo e taxa fixa de entrega
        post_resp = self.client.post(f'/painel/{self.store.slug}/configuracoes/', {
            'name': 'Pizzaria do Bairro Atualizada',
            'description': 'Nova descrição da pizzaria',
            'whatsapp': '5511999998888',
            'phone': '1133334444',
            'allows_delivery': 'on',
            'allows_pickup': 'on',
            'estimated_delivery_time_min': '25',
            'estimated_delivery_time_max': '50',
            'minimum_order_value': '35,50',
            'fixed_delivery_fee': '7,90',
        })
        self.assertEqual(post_resp.status_code, 200)
        self.store.refresh_from_db()
        self.assertEqual(self.store.name, 'Pizzaria do Bairro Atualizada')
        self.assertEqual(self.store.description, 'Nova descrição da pizzaria')
        self.assertEqual(self.store.minimum_order_value, Decimal('35.50'))
        self.assertEqual(self.store.fixed_delivery_fee, Decimal('7.90'))

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

    def test_merchant_product_options_and_availability_toggle(self):
        """Lojista gerencia grupos de opções, sabores e alterna disponibilidade em tempo real."""
        self.client.login(username='dono@pizzaria.com', password='secretpassword123')
        cat = Category.objects.create(store=self.store, name="Pizzas Grandes")
        prod = Product.objects.create(store=self.store, category=cat, name="Pizza Família 4 Sabores", price=Decimal("70.00"))

        # 1. Acessa página de opções do produto
        get_resp = self.client.get(f'/painel/{self.store.slug}/produtos/{prod.id}/opcoes/')
        self.assertEqual(get_resp.status_code, 200)
        self.assertContains(get_resp, "Pizza Família 4 Sabores")

        # 2. Cria grupo de opções (ex: 4 Sabores Obrigatórios)
        create_grp_resp = self.client.post(f'/painel/{self.store.slug}/produtos/{prod.id}/opcoes/', {
            'action': 'create_group',
            'name': 'Escolha 4 Sabores',
            'description': 'Selecione exatamente 4 sabores',
            'min_options': '4',
            'max_options': '4',
            'is_required': 'on'
        })
        self.assertEqual(create_grp_resp.status_code, 200)
        group = OptionGroup.objects.filter(product=prod, name='Escolha 4 Sabores').first()
        self.assertIsNotNone(group)
        self.assertEqual(group.min_options, 4)
        self.assertEqual(group.max_options, 4)
        self.assertTrue(group.is_required)

        # 3. Adiciona sabor ao grupo
        create_item_resp = self.client.post(f'/painel/{self.store.slug}/produtos/{prod.id}/opcoes/', {
            'action': 'create_item',
            'group_id': str(group.id),
            'name': 'Calabresa Especial',
            'price': '0,00',
            'is_available': 'on'
        })
        self.assertEqual(create_item_resp.status_code, 200)
        item = OptionItem.objects.filter(option_group=group, name='Calabresa Especial').first()
        self.assertIsNotNone(item)
        self.assertTrue(item.is_available)
        self.assertEqual(item.price, Decimal('0.00'))

        # 4. Alterna disponibilidade do sabor (marca como Esgotado)
        toggle_resp = self.client.post(f'/painel/{self.store.slug}/produtos/{prod.id}/opcoes/', {
            'action': 'toggle_item',
            'item_id': str(item.id)
        })
        self.assertEqual(toggle_resp.status_code, 200)
        item.refresh_from_db()
        self.assertFalse(item.is_available)

        # 5. Exclui sabor
        del_item_resp = self.client.post(f'/painel/{self.store.slug}/produtos/{prod.id}/opcoes/', {
            'action': 'delete_item',
            'item_id': str(item.id)
        })
        self.assertEqual(del_item_resp.status_code, 200)
        self.assertFalse(OptionItem.objects.filter(id=item.id).exists())

        # 6. Exclui grupo
        del_grp_resp = self.client.post(f'/painel/{self.store.slug}/produtos/{prod.id}/opcoes/', {
            'action': 'delete_group',
            'group_id': str(group.id)
        })
        self.assertEqual(del_grp_resp.status_code, 200)
        self.assertFalse(OptionGroup.objects.filter(id=group.id).exists())


class PublicCustomerOrdersViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='pizzaiolo@pedidos.com',
            password='secretpassword123',
            full_name='Pizzaiolo Teste'
        )
        self.store = Store.objects.create(
            owner=self.user,
            name='Pizzaria Express Bella',
            whatsapp='5511999998888',
            fixed_delivery_fee=Decimal('8.50'),
            is_active=True
        )
        from customers.models import Customer
        self.customer = Customer.objects.create(
            store=self.store,
            name='João da Silva',
            phone='11977776666'
        )
        self.order_active = Order.objects.create(
            store=self.store,
            customer=self.customer,
            order_number=101,
            status=Order.STATUS_PREPARING,
            delivery_type=Order.TYPE_DELIVERY,
            delivery_fee=Decimal('8.50'),
            subtotal=Decimal('45.00'),
            total=Decimal('53.50'),
            street='Rua das Flores',
            number='100',
            neighborhood='Centro'
        )
        self.order_completed = Order.objects.create(
            store=self.store,
            customer=self.customer,
            order_number=100,
            status=Order.STATUS_COMPLETED,
            delivery_type=Order.TYPE_DELIVERY,
            delivery_fee=Decimal('8.50'),
            subtotal=Decimal('60.00'),
            total=Decimal('68.50'),
            street='Rua das Flores',
            number='100',
            neighborhood='Centro'
        )

    def test_my_orders_unidentified_renders_login_form(self):
        """Cliente sem identificação visualiza o formulário de login por WhatsApp."""
        resp = self.client.get(f'/{self.store.slug}/meus-pedidos/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Login (somente na primeira vez)')
        self.assertContains(resp, 'Seu WhatsApp (somente dígitos)')

    def test_my_orders_identified_displays_active_and_completed_orders(self):
        """Cliente identificado por WhatsApp vê seus pedidos ativos e finalizados em abas."""
        resp = self.client.get(f'/{self.store.slug}/meus-pedidos/?phone=11977776666')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'João da Silva')
        self.assertContains(resp, 'Em Andamento')
        self.assertContains(resp, 'Finalizados')
        self.assertContains(resp, f'Pedido #{self.order_active.order_number}')
        self.assertContains(resp, f'Pedido #{self.order_completed.order_number}')
        self.assertContains(resp, 'R$ 53,50')
        self.assertContains(resp, 'R$ 68,50')

    def test_my_orders_logout_clears_session(self):
        """Ação de logout limpa a sessão e retorna à tela de login."""
        session = self.client.session
        session['customer_phone'] = '11977776666'
        session.save()

        resp = self.client.get(f'/{self.store.slug}/meus-pedidos/?action=logout')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Login (somente na primeira vez)')


class UnifiedPOSStockAndCouponAuditTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='audit_owner@mepedi.com',
            password='SafePassword123!',
            full_name='Audit Owner'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name='Bolo & Cia Central',
            whatsapp='11999991234',
            is_active=True,
            is_open=True,
            minimum_order_value=Decimal('0.00'),
            fixed_delivery_fee=Decimal('5.00')
        )
        StoreMembership.objects.create(
            user=self.owner,
            store=self.store,
            role=StoreMembership.ROLE_OWNER,
            is_active=True
        )
        self.category = Category.objects.create(store=self.store, name='Bolos Artesanais')
        
        # Produto com estoque controlado e preço promocional
        self.product = Product.objects.create(
            store=self.store,
            category=self.category,
            name='Fatia Bolo de Chocolate',
            code='BOLO-01',
            price=Decimal('50.00'),
            is_promotional=True,
            promotional_price=Decimal('35.00'),
            track_stock=True,
            stock_quantity=20
        )
        self.customer = Customer.objects.create(
            store=self.store,
            name='Maria Cliente',
            phone='11988887777'
        )
        self.client = APIClient()

    def test_promotional_pricing_properties_and_calculations(self):
        """Valida propriedades de preço promocional e percentual de desconto no produto."""
        self.assertEqual(self.product.current_price, Decimal('35.00'))
        # Desconto: (50 - 35) / 50 = 30%
        self.assertEqual(self.product.discount_percent, 30)

        # Se não promocional, volta para preço cheio
        self.product.is_promotional = False
        self.product.save()
        self.assertEqual(self.product.current_price, Decimal('50.00'))
        self.assertEqual(self.product.discount_percent, 0)

    def test_unified_central_stock_between_online_and_pos(self):
        """
        Regra Principal: O cardápio online e o PDV DEVEM utilizar o MESMO estoque centralizado.
        Exemplo:
        Estoque inicial: 20
        Venda online (3 un): 20 -> 17
        Venda PDV (5 un): 17 -> 12
        """
        # 1. Venda Online de 3 unidades
        online_order = OrderService.create_order(
            store=self.store,
            customer_payload={'name': 'Maria Cliente', 'phone': '11988887777'},
            delivery_type=Order.TYPE_DELIVERY,
            address_payload={'street': 'Rua A', 'number': '10', 'neighborhood': 'Centro'},
            payment_method=Order.PAY_PIX,
            items_payload=[{'product_id': self.product.id, 'quantity': 3}]
        )
        self.assertEqual(online_order.origin, Order.ORIGIN_ONLINE)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 17)

        # Verifica rastreabilidade no StockMovement
        mov_online = StockMovement.objects.filter(product=self.product, movement_type=StockMovement.TYPE_SALE_ONLINE).first()
        self.assertIsNotNone(mov_online)
        self.assertEqual(mov_online.quantity, -3)
        self.assertEqual(mov_online.current_stock, 17)

        # 2. Venda Presencial no Balcão (PDV) de 5 unidades
        pos_order = OrderService.create_pos_order(
            store=self.store,
            items_payload=[{'product_id': self.product.id, 'quantity': 5}],
            payment_method=Order.PAY_MONEY,
            change_for=Decimal('200.00'),
            operator=self.owner
        )
        self.assertEqual(pos_order.origin, Order.ORIGIN_PDV)
        self.assertEqual(pos_order.operator, self.owner)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 12)

        # Verifica rastreabilidade no StockMovement para PDV
        mov_pos = StockMovement.objects.filter(product=self.product, movement_type=StockMovement.TYPE_SALE_PDV).first()
        self.assertIsNotNone(mov_pos)
        self.assertEqual(mov_pos.quantity, -5)
        self.assertEqual(mov_pos.current_stock, 12)

    def test_out_of_stock_prevents_overselling_both_online_and_pos(self):
        """Garante que tanto o pedido online quanto o PDV bloqueiam venda além do estoque disponível."""
        # Reduz estoque para 2
        self.product.stock_quantity = 2
        self.product.save()

        # Tentativa de compra online de 3 unidades deve falhar
        with self.assertRaises(ValidationError) as ctx_online:
            OrderService.create_order(
                store=self.store,
                customer_payload={'name': 'Maria Cliente', 'phone': '11988887777'},
                delivery_type=Order.TYPE_PICKUP,
                payment_method=Order.PAY_PIX,
                items_payload=[{'product_id': self.product.id, 'quantity': 3}]
            )
        self.assertIn("Estoque insuficiente", str(ctx_online.exception))

        # Estoque permaneceu 2
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 2)

        # Tentativa de venda balcão PDV de 3 unidades também deve falhar
        with self.assertRaises(ValidationError) as ctx_pos:
            OrderService.create_pos_order(
                store=self.store,
                items_payload=[{'product_id': self.product.id, 'quantity': 3}],
                payment_method=Order.PAY_MONEY,
                operator=self.owner
            )
        self.assertIn("Estoque insuficiente", str(ctx_pos.exception))

        # Estoque permaneceu 2
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 2)

    def test_order_cancellation_restores_stock_idempotently(self):
        """Cancelamento de pedido devolve o estoque com segurança e idempotência estrita."""
        # Realiza venda online de 4 unidades: 20 -> 16
        order = OrderService.create_order(
            store=self.store,
            customer_payload={'name': 'Maria Cliente', 'phone': '11988887777'},
            delivery_type=Order.TYPE_PICKUP,
            payment_method=Order.PAY_PIX,
            items_payload=[{'product_id': self.product.id, 'quantity': 4}]
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 16)
        self.assertFalse(order.stock_returned)

        # 1º Cancelamento: restaura 4 unidades -> volta para 20
        StockService.restore_stock(order)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)
        order.refresh_from_db()
        self.assertTrue(order.stock_returned)

        # Verifica registro de retorno de estoque
        mov_cancel = StockMovement.objects.filter(product=self.product, movement_type=StockMovement.TYPE_CANCEL_RETURN).first()
        self.assertIsNotNone(mov_cancel)
        self.assertEqual(mov_cancel.quantity, 4)
        self.assertEqual(mov_cancel.current_stock, 20)

        # 2º Cancelamento acidental ou repetido: NÃO deve duplicar devolução
        StockService.restore_stock(order)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)

    def test_global_consecutive_order_numbering_online_and_pos(self):
        """Sequência global de pedidos (#100X) é rigorosamente contínua entre Online e PDV."""
        # Pedido 1: Online
        order1 = OrderService.create_order(
            store=self.store,
            customer_payload={'name': 'Maria Cliente', 'phone': '11988887777'},
            delivery_type=Order.TYPE_PICKUP,
            payment_method=Order.PAY_PIX,
            items_payload=[{'product_id': self.product.id, 'quantity': 1}]
        )
        # Pedido 2: PDV Balcão
        order2 = OrderService.create_pos_order(
            store=self.store,
            items_payload=[{'product_id': self.product.id, 'quantity': 1}],
            payment_method=Order.PAY_DEBIT,
            operator=self.owner
        )
        # Pedido 3: Online
        order3 = OrderService.create_order(
            store=self.store,
            customer_payload={'name': 'Maria Cliente', 'phone': '11988887777'},
            delivery_type=Order.TYPE_PICKUP,
            payment_method=Order.PAY_PIX,
            items_payload=[{'product_id': self.product.id, 'quantity': 1}]
        )
        # Pedido 4: PDV Balcão
        order4 = OrderService.create_pos_order(
            store=self.store,
            items_payload=[{'product_id': self.product.id, 'quantity': 1}],
            payment_method=Order.PAY_CREDIT,
            operator=self.owner
        )

        self.assertEqual(order1.origin, Order.ORIGIN_ONLINE)
        self.assertEqual(order2.origin, Order.ORIGIN_PDV)
        self.assertEqual(order3.origin, Order.ORIGIN_ONLINE)
        self.assertEqual(order4.origin, Order.ORIGIN_PDV)

        self.assertEqual(order2.order_number, order1.order_number + 1)
        self.assertEqual(order3.order_number, order2.order_number + 1)
        self.assertEqual(order4.order_number, order3.order_number + 1)

    def test_coupon_rules_percentage_fixed_min_order_and_usage_limit(self):
        """Testa regras de negócio completas de cupons de desconto."""
        # 1. Cupom percentual de 20% com valor mínimo de R$ 50,00
        coupon_pct = Coupon.objects.create(
            store=self.store,
            code='PROMO20',
            discount_type=Coupon.DISCOUNT_PERCENTAGE,
            discount_value=Decimal('20.00'),
            min_order_value=Decimal('50.00'),
            max_uses=2,
            is_active=True
        )

        # Subtotal abaixo do mínimo (R$ 35,00 < R$ 50,00) deve falhar
        is_valid, msg = coupon_pct.validate_for_order(subtotal=Decimal('35.00'))
        self.assertFalse(is_valid)
        self.assertIn("mínimo", msg)

        # Subtotal atendido (R$ 70,00 >= R$ 50,00)
        is_valid, msg = coupon_pct.validate_for_order(subtotal=Decimal('70.00'))
        self.assertTrue(is_valid)
        disc_val = coupon_pct.calculate_discount(subtotal=Decimal('70.00'))
        # 20% de 70 = R$ 14,00
        self.assertEqual(disc_val, Decimal('14.00'))

        # Aplica o cupom criando pedido (2 fatias de R$ 35 = R$ 70 subtotal)
        order = OrderService.create_order(
            store=self.store,
            customer_payload={'name': 'Maria Cliente', 'phone': '11988887777'},
            delivery_type=Order.TYPE_PICKUP,
            payment_method=Order.PAY_PIX,
            items_payload=[{'product_id': self.product.id, 'quantity': 2}],
            coupon_code='PROMO20'
        )
        self.assertEqual(order.subtotal, Decimal('70.00'))
        self.assertEqual(order.discount, Decimal('14.00'))
        self.assertEqual(order.total, Decimal('56.00'))
        self.assertEqual(order.coupon_code, 'PROMO20')

        coupon_pct.refresh_from_db()
        self.assertEqual(coupon_pct.times_used, 1)

        # 2. Testa esgotamento de usos
        coupon_pct.times_used = 2
        coupon_pct.save()
        is_valid, msg = coupon_pct.validate_for_order(subtotal=Decimal('100.00'))
        self.assertFalse(is_valid)
        self.assertIn("atingiu o limite", msg)

        # 3. Cupom com valor fixo R$ 10,00
        coupon_fix = Coupon.objects.create(
            store=self.store,
            code='FIXO10',
            discount_type=Coupon.DISCOUNT_FIXED,
            discount_value=Decimal('10.00'),
            min_order_value=Decimal('30.00'),
            is_active=True
        )
        disc_fix = coupon_fix.calculate_discount(subtotal=Decimal('35.00'))
        self.assertEqual(disc_fix, Decimal('10.00'))

        # 4. Cupom inativo
        coupon_fix.is_active = False
        coupon_fix.save()
        is_valid, msg = coupon_fix.validate_for_order(subtotal=Decimal('50.00'))
        self.assertFalse(is_valid)
        self.assertIn("desativado", msg)

        # 5. Cupom expirado
        coupon_fix.is_active = True
        coupon_fix.valid_until = timezone.now() - timedelta(days=1)
        coupon_fix.save()
        is_valid, msg = coupon_fix.validate_for_order(subtotal=Decimal('50.00'))
        self.assertFalse(is_valid)
        self.assertIn("expirou", msg)

    def test_pos_api_endpoint_counter_sale(self):
        """Valida endpoint REST do PDV POST /api/v1/orders/merchant/<store_id>/pos/."""
        self.client.force_authenticate(user=self.owner)
        payload = {
            "items": [
                {"product_id": self.product.id, "quantity": 2, "notes": "Embalar para presente"}
            ],
            "customer_name": "Balcão José",
            "customer_phone": "11912345678",
            "payment_method": "MONEY",
            "change_for": "100.00",
            "notes": "Cliente regular"
        }
        resp = self.client.post(f'/api/v1/orders/merchant/{self.store.id}/pos/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.json()
        self.assertEqual(data['origin'], 'PDV')
        self.assertEqual(data['delivery_type'], 'PICKUP')
        self.assertEqual(data['status'], 'CONCLUIDO')
        self.assertEqual(data['total'], '70.00')
        self.assertEqual(data['change_for'], '100.00')

        order = Order.objects.get(id=data['id'])
        self.assertEqual(order.change_for - order.total, Decimal('30.00'))
        self.assertEqual(order.operator, self.owner)

    def test_validate_coupon_api_endpoint(self):
        """Valida endpoint REST POST /api/v1/orders/coupon/validate/."""
        Coupon.objects.create(
            store=self.store,
            code='DESC10',
            discount_type=Coupon.DISCOUNT_PERCENTAGE,
            discount_value=Decimal('10.00'),
            min_order_value=Decimal('20.00'),
            is_active=True
        )
        payload = {
            "store_slug": self.store.slug,
            "code": "DESC10",
            "subtotal": "50.00",
            "delivery_fee": "5.00"
        }
        resp = self.client.post('/api/v1/orders/coupon/validate/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertTrue(data['valid'])
        self.assertEqual(data['discount_amount'], '5.00')
        self.assertEqual(data['code'], 'DESC10')


class ProductOptionCloningDashboardViewTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='lojista_opcoes@mepedi.com',
            password='Password123!',
            full_name='Lojista Opções'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name='Açaí & Delícias',
            whatsapp='11955554444',
            is_active=True,
            is_open=True
        )
        StoreMembership.objects.create(
            user=self.owner,
            store=self.store,
            role=StoreMembership.ROLE_OWNER,
            is_active=True
        )
        self.category = Category.objects.create(store=self.store, name='Açaí')
        self.acai_500 = Product.objects.create(
            store=self.store,
            category=self.category,
            name='Açaí no Copo 500ml',
            price=Decimal('25.00')
        )
        self.group_toppings = OptionGroup.objects.create(
            store=self.store,
            product=self.acai_500,
            name='Escolha 4 Complementos',
            min_options=4,
            max_options=4,
            is_required=True
        )
        self.item_leite_ninho = OptionItem.objects.create(
            option_group=self.group_toppings,
            name='Leite Ninho',
            price=Decimal('0.00')
        )
        self.item_granola = OptionItem.objects.create(
            option_group=self.group_toppings,
            name='Granola Artesanal',
            price=Decimal('0.00')
        )
        self.item_nutella = OptionItem.objects.create(
            option_group=self.group_toppings,
            name='Nutella Pura',
            price=Decimal('5.00')
        )

        self.acai_300 = Product.objects.create(
            store=self.store,
            category=self.category,
            name='Açaí no Copo 300ml',
            price=Decimal('18.00')
        )
        self.client = APIClient()
        self.client.force_login(self.owner)

    def test_dashboard_clone_group_view(self):
        """Testa clonagem de grupo pelo painel ajustando limites para o copo menor."""
        url = f'/painel/{self.store.slug}/produtos/{self.acai_300.id}/opcoes/'
        payload = {
            'action': 'clone_group',
            'source_group_id': self.group_toppings.id,
            'name': 'Escolha até 2 Complementos',
            'description': 'Selecione 2 adicionais',
            'min_options': '1',
            'max_options': '2',
            'is_required': 'on',
            'selected_items': [str(self.item_leite_ninho.id), str(self.item_granola.id)]
        }
        resp = self.client.post(url, payload)
        self.assertEqual(resp.status_code, 200)

        cloned_grp = OptionGroup.objects.filter(product=self.acai_300).first()
        self.assertIsNotNone(cloned_grp)
        self.assertEqual(cloned_grp.name, 'Escolha até 2 Complementos')
        self.assertEqual(cloned_grp.min_options, 1)
        self.assertEqual(cloned_grp.max_options, 2)
        self.assertEqual(cloned_grp.items.count(), 2)
        # Nutella não estava em selected_items
        self.assertFalse(cloned_grp.items.filter(name='Nutella Pura').exists())

    def test_dashboard_edit_group_rules_view(self):
        """Testa edição de regras (min/max/nome) sem perder os itens cadastrados."""
        url = f'/painel/{self.store.slug}/produtos/{self.acai_500.id}/opcoes/'
        payload = {
            'action': 'edit_group',
            'group_id': self.group_toppings.id,
            'name': 'Escolha de 2 a 4 Complementos',
            'description': 'Mínimo 2 e máximo 4',
            'min_options': '2',
            'max_options': '4',
            'is_required': 'on'
        }
        resp = self.client.post(url, payload)
        self.assertEqual(resp.status_code, 200)

        self.group_toppings.refresh_from_db()
        self.assertEqual(self.group_toppings.name, 'Escolha de 2 a 4 Complementos')
        self.assertEqual(self.group_toppings.min_options, 2)
        self.assertEqual(self.group_toppings.max_options, 4)
        # Itens continuam intactos
        self.assertEqual(self.group_toppings.items.count(), 3)

    def test_dashboard_bulk_add_items_view(self):
        """Testa adicionar vários sabores ou complementos em massa colando uma lista."""
        url = f'/painel/{self.store.slug}/produtos/{self.acai_500.id}/opcoes/'
        payload = {
            'action': 'bulk_create_items',
            'group_id': self.group_toppings.id,
            'items_text': 'Morango Fresco\nBanana Prata\nPaçoca (+ R$ 2,50)\nGotas de Chocolate'
        }
        resp = self.client.post(url, payload)
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(self.group_toppings.items.count(), 7)
        pacoca = OptionItem.objects.get(option_group=self.group_toppings, name='Paçoca')
        self.assertEqual(pacoca.price, Decimal('2.50'))

    def test_create_product_with_copy_options_from(self):
        """Testa criação de novo produto já copiando grupos e complementos na mesma requisição."""
        url = f'/painel/{self.store.slug}/produtos/'
        payload = {
            'action': 'create',
            'name': 'Açaí no Copo 700ml',
            'category': self.category.id,
            'price': '32.00',
            'copy_options_from': str(self.acai_500.id)
        }
        resp = self.client.post(url, payload)
        self.assertEqual(resp.status_code, 200)

        acai_700 = Product.objects.get(name='Açaí no Copo 700ml', store=self.store)
        self.assertEqual(acai_700.option_groups.count(), 1)
        self.assertEqual(acai_700.option_groups.first().items.count(), 3)


class TableAndSessionModelTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='table_owner@pedidos.com',
            password='Password123!',
            full_name='Table Owner'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name="Restaurante Central",
            whatsapp="11988887777",
            is_active=True,
            is_open=True
        )

    def test_table_creation_and_unique_per_store(self):
        from django.db import IntegrityError, transaction
        t1 = Table.objects.create(store=self.store, number="01", name="Janela")
        self.assertIsNotNone(t1.qr_token)
        self.assertTrue(t1.is_active)

        # Tentativa de criar outra mesa com mesmo número na mesma loja deve falhar
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Table.objects.create(store=self.store, number="01", name="Outra")

    def test_table_unique_active_session_constraint(self):
        from django.db import IntegrityError, transaction
        t1 = Table.objects.create(store=self.store, number="02")
        s1 = TableSession.objects.create(store=self.store, table=t1, status=TableSession.STATUS_OPEN)

        # Tentar abrir segunda sessão simultânea na mesma mesa deve violar constraint
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                TableSession.objects.create(store=self.store, table=t1, status=TableSession.STATUS_OPEN)

        # Se a sessão for fechada, permite nova sessão aberta
        s1.status = TableSession.STATUS_CLOSED
        s1.closed_at = timezone.now()
        s1.save()

        s2 = TableSession.objects.create(store=self.store, table=t1, status=TableSession.STATUS_OPEN)
        self.assertIsNotNone(s2.id)


class TableOrderServiceTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='garcom@pedidos.com',
            password='Password123!',
            full_name='Garçom Chef'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name="Pizzaria Bella Mesa",
            whatsapp="11977776666",
            is_active=True,
            is_open=True
        )
        self.cat = Category.objects.create(store=self.store, name="Pizzas")
        self.prod = Product.objects.create(
            store=self.store,
            category=self.cat,
            name="Pizza Margherita",
            price=Decimal("45.00"),
            track_stock=True,
            stock_quantity=10
        )
        self.drink = Product.objects.create(
            store=self.store,
            category=self.cat,
            name="Refrigerante Lata",
            price=Decimal("6.00"),
            track_stock=True,
            stock_quantity=20
        )
        self.table = Table.objects.create(store=self.store, number="10", name="Varanda")

    def test_get_or_create_table_session(self):
        sess1, created1 = OrderService.get_or_create_table_session(self.table)
        self.assertTrue(created1)
        self.assertEqual(sess1.status, TableSession.STATUS_OPEN)

        # Chamar novamente deve retornar a mesma sessão ativa
        sess2, created2 = OrderService.get_or_create_table_session(self.table)
        self.assertFalse(created2)
        self.assertEqual(sess1.id, sess2.id)

    def test_create_table_order_multi_round_and_stock(self):
        session, _ = OrderService.get_or_create_table_session(self.table)

        # Rodada 1: 1 Pizza Margherita
        order1 = OrderService.create_table_order(
            store=self.store,
            table=self.table,
            session=session,
            items_payload=[{"product_id": self.prod.id, "quantity": 1}],
            customer_name="Luiz Silva",
            customer_phone="11999998888",
            order_notes="Massa fina"
        )
        self.assertEqual(order1.origin, Order.ORIGIN_TABLE)
        self.assertEqual(order1.delivery_type, Order.TYPE_DINE_IN)
        self.assertEqual(order1.table, self.table)
        self.assertEqual(order1.table_session, session)
        self.assertEqual(order1.subtotal, Decimal("45.00"))
        self.assertEqual(order1.total, Decimal("45.00"))

        # Estoque foi debitado corretamente com SALE_TABLE
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock_quantity, 9)
        movement = StockMovement.objects.filter(product=self.prod, order=order1).first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.movement_type, StockMovement.TYPE_SALE_TABLE)

        # Rodada 2: 2 Refrigerantes
        order2 = OrderService.create_table_order(
            store=self.store,
            table=self.table,
            session=session,
            items_payload=[{"product_id": self.drink.id, "quantity": 2}],
            customer_name="Luiz Silva",
            customer_phone="11999998888"
        )
        self.drink.refresh_from_db()
        self.assertEqual(self.drink.stock_quantity, 18)

        # Sessão consolidada reflete os dois pedidos
        total_session = session.calculate_total()
        self.assertEqual(total_session, Decimal("57.00"))
        self.assertEqual(session.orders.count(), 2)

    def test_request_table_bill(self):
        session, _ = OrderService.get_or_create_table_session(self.table)
        OrderService.create_table_order(
            store=self.store,
            table=self.table,
            session=session,
            items_payload=[{"product_id": self.prod.id, "quantity": 1}]
        )
        updated_sess = OrderService.request_table_bill(session)
        self.assertEqual(updated_sess.status, TableSession.STATUS_WAITING_PAYMENT)

    def test_close_table_session_atomic(self):
        session, _ = OrderService.get_or_create_table_session(self.table)
        order = OrderService.create_table_order(
            store=self.store,
            table=self.table,
            session=session,
            items_payload=[{"product_id": self.prod.id, "quantity": 2}]
        )
        self.assertEqual(order.status, Order.STATUS_NEW)

        closed = OrderService.close_table_session(
            session_id=session.id,
            operator=self.owner,
            payment_method=Order.PAY_PIX,
            discount=Decimal("10.00"),
            notes="Desconto cortesia"
        )
        self.assertEqual(closed.status, TableSession.STATUS_CLOSED)
        self.assertEqual(closed.calculate_subtotal(), Decimal("90.00"))
        self.assertEqual(closed.discount, Decimal("10.00"))
        self.assertEqual(closed.total_paid, Decimal("80.00"))
        self.assertIsNotNone(closed.closed_at)

        # Pedidos devem estar marcados como COMPLETED com forma de pagamento
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_COMPLETED)
        self.assertEqual(order.payment_method, Order.PAY_PIX)

        # Tentar fechar novamente deve gerar erro (segurança contra duplo fechamento)
        with self.assertRaises(ValidationError):
            OrderService.close_table_session(
                session_id=session.id,
                operator=self.owner,
                payment_method=Order.PAY_PIX
            )


class TableAPIsTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='lojista_table@pedidos.com',
            password='Password123!',
            full_name='Lojista Mesas'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name="Cantina Italiana",
            whatsapp="11955554444",
            is_active=True,
            is_open=True
        )
        StoreMembership.objects.create(store=self.store, user=self.owner, role="OWNER")
        self.cat = Category.objects.create(store=self.store, name="Massas")
        self.prod = Product.objects.create(
            store=self.store,
            category=self.cat,
            name="Lasanha Bolonhesa",
            price=Decimal("40.00")
        )
        self.table = Table.objects.create(store=self.store, number="05", name="Salão Nobre")
        self.client = APIClient()

    def test_public_create_table_order_flow(self):
        url = f"/api/v1/orders/table/{self.table.qr_token}/"
        payload = {
            "customer_name": "Marcos",
            "customer_phone": "11988887777",
            "notes": "Sem cebola",
            "items": [
                {
                    "product_id": self.prod.id,
                    "quantity": 2,
                    "notes": "Bem quente"
                }
            ]
        }
        resp = self.client.post(url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["table_number"], "05")
        self.assertEqual(Decimal(str(resp.data["subtotal"])), Decimal("80.00"))

        # Comanda pública
        url_comanda = f"/api/v1/orders/table/{self.table.qr_token}/comanda/"
        resp_comanda = self.client.get(url_comanda)
        self.assertEqual(resp_comanda.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_comanda.data["status"], "OPEN")
        self.assertEqual(len(resp_comanda.data["orders"]), 1)

        # Pedir conta
        url_pedir = f"/api/v1/orders/table/{self.table.qr_token}/pedir-conta/"
        resp_pedir = self.client.post(url_pedir)
        self.assertEqual(resp_pedir.status_code, status.HTTP_200_OK)
        self.assertTrue(resp_pedir.data["success"])
        self.assertEqual(resp_pedir.data["status"], "WAITING_PAY")

    def test_merchant_table_crud_and_close(self):
        self.client.force_authenticate(user=self.owner)

        # Criar nova mesa via API do lojista
        url_create_table = f"/api/v1/orders/merchant/{self.store.id}/tables/"
        resp = self.client.post(url_create_table, {"number": "06", "name": "Balcão"})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["number"], "06")

        # Inicia pedido na mesa 06
        t6 = Table.objects.get(id=resp.data["id"])
        sess, _ = OrderService.get_or_create_table_session(t6)
        OrderService.create_table_order(
            store=self.store,
            table=t6,
            session=sess,
            items_payload=[{"product_id": self.prod.id, "quantity": 1}]
        )

        # Consultar sessão ativa da mesa
        url_sess = f"/api/v1/orders/merchant/{self.store.id}/tables/{t6.id}/session/"
        resp_sess = self.client.get(url_sess)
        self.assertEqual(resp_sess.status_code, status.HTTP_200_OK)
        self.assertTrue(resp_sess.data["active"])
        self.assertEqual(resp_sess.data["total"], 40.0)

        # Fechar mesa no PDV com PIX e desconto
        url_close = f"/api/v1/orders/merchant/{self.store.id}/table-sessions/{sess.public_id}/close/"
        resp_close = self.client.post(url_close, {
            "payment_method": "PIX",
            "discount": "5.00",
            "notes": "Desconto amigo"
        }, format="json")
        self.assertEqual(resp_close.status_code, status.HTTP_200_OK)
        self.assertTrue(resp_close.data["success"])
        self.assertEqual(resp_close.data["total_paid"], 35.0)
        self.assertEqual(resp_close.data["status"], "CLOSED")

    def test_public_pages_render(self):
        # Página do Cardápio Digital da Mesa
        resp_menu = self.client.get(f"/{self.store.slug}/mesa/{self.table.qr_token}/")
        self.assertEqual(resp_menu.status_code, 200)

        # Página da Comanda
        resp_comanda = self.client.get(f"/{self.store.slug}/mesa/{self.table.qr_token}/comanda/")
        self.assertEqual(resp_comanda.status_code, 200)

        # Painel do Lojista: Gestão de Mesas
        self.client.force_login(self.owner)
        resp_painel = self.client.get(f"/painel/{self.store.slug}/mesas/")
        self.assertEqual(resp_painel.status_code, 200)







