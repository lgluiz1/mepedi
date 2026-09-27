import json
import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth import get_user_model

from stores.models import Store
from accounts.models import StoreMembership
from catalog.models import Category, Product, StockMovement
from orders.models import Order, OrderItem
from customers.models import Customer
from analytics.models import TrafficVisit, TrackableLink, AnalyticsEvent
from analytics.services import AnalyticsService
from analytics.queries import parse_date_period, AnalyticsQueryService

User = get_user_model()


class AnalyticsModuleTests(TestCase):
    """
    Suíte completa de testes de integração e unidade para o Módulo de Analytics.
    Valida:
    - Segurança Multi-Tenant e Permissões
    - Filtros de Período e Timezones
    - Faturamento, Pedidos e Ticket Médio
    - Segmentação Online vs PDV
    - Cancelamentos e Estoque
    - Métricas de Produtos e Sem Vendas
    - Tráfego, UTMs, Links Rastreáveis e Funil
    - Tratamento de Dados Insuficientes
    """

    def setUp(self):
        self.client = Client()

        # Usuários e Lojas Isoladas
        self.user_a = User.objects.create_user(
            email='lojista_a@mepedi.com',
            password='password123',
            first_name='Lojista A'
        )
        self.store_a = Store.objects.create(
            name='Loja A Pizzaria',
            slug='loja-a',
            owner=self.user_a,
            preparation_time_minutes=30,
            is_active=True,
            is_open=True
        )
        StoreMembership.objects.create(
            user=self.user_a,
            store=self.store_a,
            role=StoreMembership.ROLE_OWNER,
            is_active=True
        )

        self.user_b = User.objects.create_user(
            email='lojista_b@mepedi.com',
            password='password123',
            first_name='Lojista B'
        )
        self.store_b = Store.objects.create(
            name='Loja B Hamburgueria',
            slug='loja-b',
            owner=self.user_b,
            preparation_time_minutes=25,
            is_active=True,
            is_open=True
        )
        StoreMembership.objects.create(
            user=self.user_b,
            store=self.store_b,
            role=StoreMembership.ROLE_OWNER,
            is_active=True
        )

        # Clientes
        self.customer_a = Customer.objects.create(
            store=self.store_a,
            name='Cliente A',
            phone='11999990001'
        )
        self.customer_b = Customer.objects.create(
            store=self.store_b,
            name='Cliente B',
            phone='11999990002'
        )

        # Categorias e Produtos da Loja A
        self.cat_pizzas = Category.objects.create(
            store=self.store_a,
            name='Pizzas Salgadas'
        )
        self.prod_calabresa = Product.objects.create(
            store=self.store_a,
            category=self.cat_pizzas,
            name='Pizza Calabresa',
            price=Decimal('50.00'),
            track_stock=True,
            stock_quantity=10,
            is_active=True
        )
        self.prod_marguerita = Product.objects.create(
            store=self.store_a,
            category=self.cat_pizzas,
            name='Pizza Marguerita',
            price=Decimal('55.00'),
            track_stock=True,
            stock_quantity=3,  # Estoque crítico
            is_active=True
        )
        self.prod_refrigerante = Product.objects.create(
            store=self.store_a,
            category=self.cat_pizzas,
            name='Refrigerante Lata',
            price=Decimal('7.00'),
            track_stock=True,
            stock_quantity=0,  # Esgotado
            is_active=True
        )
        self.prod_sem_venda = Product.objects.create(
            store=self.store_a,
            category=self.cat_pizzas,
            name='Sobremesa Especial',
            price=Decimal('20.00'),
            track_stock=True,
            stock_quantity=15,
            is_active=True
        )

        # Produto da Loja B (para validação de isolamento)
        self.cat_burgers = Category.objects.create(
            store=self.store_b,
            name='Burgers'
        )
        self.prod_burger_b = Product.objects.create(
            store=self.store_b,
            category=self.cat_burgers,
            name='Mega Burger B',
            price=Decimal('45.00'),
            is_active=True
        )

    # -------------------------------------------------------------------------
    # 1. TESTES DE SEGURANÇA E MULTI-TENANT
    # -------------------------------------------------------------------------
    def test_anonymous_user_redirected_to_login(self):
        """Usuário não autenticado deve ser redirecionado para a tela de login do painel."""
        response = self.client.get(f'/painel/{self.store_a.slug}/analytics/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/painel/login/', response.url)

    def test_cross_tenant_access_is_forbidden(self):
        """Lojista B não pode acessar o painel de Analytics da Loja A (HTTP 403 Forbidden)."""
        self.client.login(username='lojista_b@mepedi.com', password='password123')
        response = self.client.get(f'/painel/{self.store_a.slug}/analytics/')
        self.assertEqual(response.status_code, 403)

    def test_authorized_merchant_can_access_own_analytics(self):
        """Lojista A acessa com sucesso o dashboard da sua própria Loja A."""
        self.client.login(username='lojista_a@mepedi.com', password='password123')
        response = self.client.get(f'/painel/{self.store_a.slug}/analytics/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboard/analytics.html')
        self.assertEqual(response.context['store'], self.store_a)

    def test_query_service_strictly_filters_by_store(self):
        """Garante que dados da Loja B nunca contaminam as métricas da Loja A."""
        now = timezone.now()
        # Pedido na Loja A
        order_a = Order.objects.create(
            store=self.store_a,
            customer=self.customer_a,
            order_number=101,
            origin=Order.ORIGIN_ONLINE,
            status=Order.STATUS_COMPLETED,
            subtotal=Decimal('100.00'),
            total=Decimal('100.00')
        )
        # Pedido na Loja B
        order_b = Order.objects.create(
            store=self.store_b,
            customer=self.customer_b,
            order_number=201,
            origin=Order.ORIGIN_ONLINE,
            status=Order.STATUS_COMPLETED,
            subtotal=Decimal('500.00'),
            total=Decimal('500.00')
        )

        start_dt, end_dt, label = parse_date_period('30d')
        metrics_a = AnalyticsQueryService(self.store_a, start_dt, end_dt, label).get_all_metrics()

        self.assertEqual(metrics_a['overview']['total_revenue'], Decimal('100.00'))
        self.assertEqual(metrics_a['overview']['total_orders'], 1)

    # -------------------------------------------------------------------------
    # 2. TESTES DE FILTRO DE PERÍODO
    # -------------------------------------------------------------------------
    def test_parse_date_period_options(self):
        """Valida que todos os períodos ('hoje', 'ontem', '7d', '30d', '90d', 'custom') retornam datetimes válidos."""
        now = timezone.localtime()

        # Hoje
        s, e, lbl = parse_date_period('hoje')
        self.assertEqual(lbl, 'Hoje')
        self.assertEqual(s.date(), now.date())

        # Ontem
        s, e, lbl = parse_date_period('ontem')
        self.assertEqual(lbl, 'Ontem')
        self.assertEqual(s.date(), (now.date() - datetime.timedelta(days=1)))

        # 7 dias
        s, e, lbl = parse_date_period('7d')
        self.assertEqual(lbl, 'Últimos 7 dias')
        self.assertEqual((e.date() - s.date()).days, 6)

        # 30 dias
        s, e, lbl = parse_date_period('30d')
        self.assertEqual(lbl, 'Últimos 30 dias')
        self.assertEqual((e.date() - s.date()).days, 29)

        # Custom
        s, e, lbl = parse_date_period('custom', '2026-09-01', '2026-09-15')
        self.assertIn('01/09/2026', lbl)
        self.assertIn('15/09/2026', lbl)

    # -------------------------------------------------------------------------
    # 3. TESTES DE FATURAMENTO, ONLINE X PDV E TICKET MÉDIO
    # -------------------------------------------------------------------------
    def test_sales_and_channel_segmentation(self):
        """Testa o cálculo preciso de Faturamento, Pedidos, Online vs PDV e Ticket Médio."""
        now = timezone.now()

        # Pedido 1: Online Concluído R$ 100,00
        o1 = Order.objects.create(
            store=self.store_a,
            customer=self.customer_a,
            order_number=1001,
            origin=Order.ORIGIN_ONLINE,
            status=Order.STATUS_COMPLETED,
            subtotal=Decimal('90.00'),
            delivery_fee=Decimal('10.00'),
            total=Decimal('100.00'),
            payment_method=Order.PAY_PIX
        )
        # Pedido 2: PDV Concluído R$ 50,00
        o2 = Order.objects.create(
            store=self.store_a,
            customer=self.customer_a,
            order_number=1002,
            origin=Order.ORIGIN_PDV,
            status=Order.STATUS_COMPLETED,
            subtotal=Decimal('50.00'),
            total=Decimal('50.00'),
            payment_method=Order.PAY_MONEY
        )
        # Pedido 3: Online Cancelado R$ 80,00 (não deve somar na receita válida)
        o3 = Order.objects.create(
            store=self.store_a,
            customer=self.customer_a,
            order_number=1003,
            origin=Order.ORIGIN_ONLINE,
            status=Order.STATUS_CANCELLED,
            subtotal=Decimal('80.00'),
            total=Decimal('80.00')
        )

        start_dt, end_dt, label = parse_date_period('30d')
        metrics = AnalyticsQueryService(self.store_a, start_dt, end_dt, label).get_all_metrics()

        # Faturamento total = 100 + 50 = 150
        self.assertEqual(metrics['overview']['total_revenue'], Decimal('150.00'))
        self.assertEqual(metrics['overview']['valid_orders'], 2)
        self.assertEqual(metrics['overview']['total_orders'], 3)
        self.assertEqual(metrics['overview']['cancelled_orders'], 1)
        self.assertEqual(metrics['overview']['cancel_rate'], 33.3)

        # Ticket médio = 150 / 2 = 75.00
        self.assertEqual(metrics['overview']['ticket_medio'], Decimal('75.00'))

        # Segmentação de canal
        self.assertEqual(metrics['overview']['online_revenue'], Decimal('100.00'))
        self.assertEqual(metrics['overview']['online_orders_count'], 1)
        self.assertEqual(metrics['overview']['pdv_revenue'], Decimal('50.00'))
        self.assertEqual(metrics['overview']['pdv_orders_count'], 1)

    # -------------------------------------------------------------------------
    # 4. TESTES DE PRODUTOS (TOP, MENOR VOLUME E SEM VENDAS)
    # -------------------------------------------------------------------------
    def test_product_sales_metrics(self):
        """Valida agregação de produtos vendidos e listagem de produtos sem saída."""
        order = Order.objects.create(
            store=self.store_a,
            customer=self.customer_a,
            order_number=2001,
            origin=Order.ORIGIN_ONLINE,
            status=Order.STATUS_COMPLETED,
            subtotal=Decimal('155.00'),
            total=Decimal('155.00')
        )

        # 3x Calabresa (total R$ 150,00)
        OrderItem.objects.create(
            order=order,
            product=self.prod_calabresa,
            product_name=self.prod_calabresa.name,
            unit_price=Decimal('50.00'),
            quantity=3,
            subtotal=Decimal('150.00'),
            total=Decimal('150.00')
        )
        # 1x Marguerita (total R$ 55,00)
        OrderItem.objects.create(
            order=order,
            product=self.prod_marguerita,
            product_name=self.prod_marguerita.name,
            unit_price=Decimal('55.00'),
            quantity=1,
            subtotal=Decimal('55.00'),
            total=Decimal('55.00')
        )

        start_dt, end_dt, label = parse_date_period('30d')
        metrics = AnalyticsQueryService(self.store_a, start_dt, end_dt, label).get_product_metrics()

        top_names = [p['product_name'] for p in metrics['top_selling']]
        self.assertEqual(top_names[0], 'Pizza Calabresa')
        self.assertEqual(metrics['top_selling'][0]['qty'], 3)
        self.assertEqual(metrics['top_selling'][0]['total_revenue'], Decimal('150.00'))

        # Produto sem venda no período (Sobremesa Especial e Refrigerante Lata)
        unsold_names = [u['name'] for u in metrics['unsold_products']]
        self.assertIn('Sobremesa Especial', unsold_names)
        self.assertIn('Refrigerante Lata', unsold_names)
        self.assertNotIn('Pizza Calabresa', unsold_names)

    # -------------------------------------------------------------------------
    # 5. TESTES DE TRÁFEGO, LINKS RASTREÁVEIS E FUNIL
    # -------------------------------------------------------------------------
    def test_traffic_visit_and_event_recording(self):
        """Registra visita com UTMs e eventos de funil."""
        client = Client()
        # Visita pública com UTM
        response = client.get(f'/{self.store_a.slug}/?utm_source=instagram&utm_campaign=setembro')
        self.assertEqual(response.status_code, 200)

        visits = TrafficVisit.objects.filter(store=self.store_a)
        self.assertEqual(visits.count(), 1)
        v = visits.first()
        self.assertEqual(v.utm_source, 'instagram')
        self.assertEqual(v.utm_campaign, 'setembro')

        # Evento de PAGE_VIEW deve ter sido gerado
        events = AnalyticsEvent.objects.filter(store=self.store_a, event_type=AnalyticsEvent.EVENT_PAGE_VIEW)
        self.assertEqual(events.count(), 1)

    def test_trackable_link_creation_and_url_builder(self):
        """Lojista cria Link Rastreável e URL parametrizada é montada corretamente."""
        link = AnalyticsService.create_trackable_link(
            store=self.store_a,
            name='Instagram Promo Setembro',
            utm_source='instagram',
            utm_campaign='setembro',
            utm_medium='bio'
        )
        self.assertEqual(link.utm_source, 'instagram')
        self.assertEqual(link.utm_campaign, 'setembro')
        self.assertTrue(link.slug_code)

        generated_url = link.build_url()
        self.assertIn('utm_source=instagram', generated_url)
        self.assertIn('utm_campaign=setembro', generated_url)
        self.assertIn('utm_medium=bio', generated_url)
        self.assertIn(f'/{self.store_a.slug}/', generated_url)

    def test_api_event_tracking_endpoint(self):
        """Endpoint /api/v1/analytics/<store_slug>/event/ processa eventos do cliente."""
        payload = {
            'event_type': 'PRODUCT_VIEW',
            'product_id': self.prod_calabresa.id,
            'metadata': {'screen': 'menu'}
        }
        response = self.client.post(
            f'/api/v1/analytics/{self.store_a.slug}/event/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get('success'))

        event = AnalyticsEvent.objects.filter(store=self.store_a, event_type='PRODUCT_VIEW').first()
        self.assertIsNotNone(event)
        self.assertEqual(event.product, self.prod_calabresa)

    # -------------------------------------------------------------------------
    # 6. TESTES DE OPERAÇÃO E DADOS INSUFICIENTES
    # -------------------------------------------------------------------------
    def test_operational_metrics_with_and_without_timestamps(self):
        """Valida que quando não há timestamps, informa 'Dados insuficientes', e quando há, calcula com precisão."""
        start_dt, end_dt, label = parse_date_period('30d')

        # 1. Sem timestamps: deve retornar has_operational_data = False
        metrics_empty = AnalyticsQueryService(self.store_a, start_dt, end_dt, label).get_operations_metrics()
        self.assertFalse(metrics_empty['has_operational_data'])
        self.assertIsNone(metrics_empty['avg_prep_min'])

        # 2. Com timestamps reais
        now = timezone.now()
        created = now - datetime.timedelta(minutes=45)
        accepted = now - datetime.timedelta(minutes=40)  # 5 min para aceite
        ready = now - datetime.timedelta(minutes=5)      # 35 min de preparo (5 min atrasado vs 30 min padrão)

        order = Order.objects.create(
            store=self.store_a,
            customer=self.customer_a,
            order_number=3001,
            origin=Order.ORIGIN_ONLINE,
            status=Order.STATUS_COMPLETED,
            subtotal=Decimal('50.00'),
            total=Decimal('50.00'),
            accepted_at=accepted,
            ready_at=ready
        )
        Order.objects.filter(id=order.id).update(created_at=created)
        OrderItem.objects.create(
            order=order,
            product=self.prod_calabresa,
            product_name=self.prod_calabresa.name,
            unit_price=Decimal('50.00'),
            quantity=1,
            subtotal=Decimal('50.00'),
            total=Decimal('50.00')
        )

        metrics_with_data = AnalyticsQueryService(self.store_a, start_dt, end_dt, label).get_operations_metrics()
        self.assertTrue(metrics_with_data['has_operational_data'])
        self.assertEqual(metrics_with_data['avg_accept_min'], 5.0)
        self.assertEqual(metrics_with_data['avg_prep_min'], 35.0)
        self.assertEqual(metrics_with_data['delayed_count'], 1)
        self.assertEqual(metrics_with_data['avg_delay_min'], 5.0)

    # -------------------------------------------------------------------------
    # 7. TESTES DE ESTOQUE
    # -------------------------------------------------------------------------
    def test_stock_metrics(self):
        """Valida identificação de estoque esgotado, crítico e movimentações."""
        start_dt, end_dt, label = parse_date_period('30d')
        metrics = AnalyticsQueryService(self.store_a, start_dt, end_dt, label).get_stock_metrics()

        # Esgotado: Refrigerante Lata (saldo 0)
        out_names = [p['name'] for p in metrics['out_of_stock']]
        self.assertIn('Refrigerante Lata', out_names)

        # Crítico: Pizza Marguerita (saldo 3 <= 5)
        crit_names = [p['name'] for p in metrics['critical_stock']]
        self.assertIn('Pizza Marguerita', crit_names)
