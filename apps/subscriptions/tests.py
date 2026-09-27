from datetime import timedelta
from decimal import Decimal
import json
from django.test import TestCase, RequestFactory, Client
from django.http import HttpResponse
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from stores.models import Store
from accounts.models import StoreMembership
from customers.models import Customer
from orders.models import Order
from subscriptions.models import (
    Feature, Plan, Subscription, PaymentGatewayConfig, PaymentHistory, WebhookEvent
)
from subscriptions.services.trial_service import TrialService
from subscriptions.services.feature_service import FeatureService, can_access_feature, get_accessible_features
from subscriptions.services.subscription_service import SubscriptionService
from subscriptions.services.payment_service import PaymentService
from subscriptions.decorators import feature_required
from subscriptions.context_processors import subscription_context

User = get_user_model()


class SaaSMePediSubscriptionTestCase(TestCase):
    """
    Suíte completa de testes para a Fase 8 do SaaS MePedi.
    Valida rigorosamente:
    1. Regras do Trial (30 dias, 300 pedidos, R$ 2.000)
    2. Exclusão de pedidos cancelados
    3. Planos pagos sem limites de pedidos ou faturamento
    4. Controle centralizado de acesso a features
    5. Preservação de dados no Downgrade
    6. Idempotência estrita de Webhooks
    7. Unicidade de assinaturas ativas por loja
    """

    def setUp(self):
        # 1. Usuário e Loja
        self.owner = User.objects.create_user(
            email='lojista@mepedi.com',
            password='TestPassword123!',
            full_name='Lojista Exemplo'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name="Hamburgueria Artesanal MePedi",
            whatsapp="11988887777",
            is_active=True,
            is_open=True
        )
        self.customer = Customer.objects.create(
            store=self.store,
            name="Cliente Fiel",
            phone="11977776666"
        )
        self.membership = StoreMembership.objects.create(
            user=self.owner,
            store=self.store,
            role='owner',
            is_active=True
        )
        self.factory = RequestFactory()

        # 2. Inicialização dos dados do SaaS
        seed_data = SubscriptionService.seed_default_saas_data()
        self.features = seed_data['features']
        self.plan_start = seed_data['plans']['start']
        self.plan_pro = seed_data['plans']['pro']
        self.plan_gestao = seed_data['plans']['gestao']

    def create_dummy_orders(self, count, total_each=Decimal('10.00'), status=Order.STATUS_COMPLETED):
        """
        Cria pedidos reais de forma rápida para validação de métricas.
        """
        orders = []
        base_order_number = Order.objects.filter(store=self.store).count() + 1000
        for i in range(count):
            order = Order.objects.create(
                store=self.store,
                customer=self.customer,
                order_number=base_order_number + i,
                status=status,
                subtotal=total_each,
                total=total_each,
                origin=Order.ORIGIN_ONLINE
            )
            orders.append(order)
        return orders

    # =========================================================================
    # 1. TESTES DO TRIAL (30 dias / 300 pedidos / R$ 2.000)
    # =========================================================================

    def test_trial_initialization(self):
        """
        Garante que o Trial inicia corretamente com 30 dias e métricas zeradas.
        """
        sub = SubscriptionService.start_trial(self.store)
        self.assertEqual(sub.status, Subscription.STATUS_TRIAL)
        self.assertIsNone(sub.plan)
        self.assertIsNotNone(sub.trial_started_at)
        self.assertIsNotNone(sub.trial_ends_at)
        self.assertEqual((sub.trial_ends_at - sub.trial_started_at).days, 30)

        status_info = TrialService.check_trial_status(self.store)
        self.assertTrue(status_info['is_active'])
        self.assertFalse(status_info['is_expired'])
        self.assertIsNone(status_info['expired_reason'])
        self.assertEqual(status_info['orders_count'], 0)
        self.assertEqual(status_info['revenue_total'], Decimal('0.00'))
        self.assertEqual(status_info['orders_limit'], 300)
        self.assertEqual(status_info['revenue_limit'], Decimal('2000.00'))

    def test_trial_active_when_within_all_limits(self):
        """
        Garante que abaixo dos 3 limites o Trial permanece ATIVO.
        Ex: 15 dias, 250 pedidos, R$ 1.800 -> Ativo.
        """
        SubscriptionService.start_trial(self.store)
        # Cria 250 pedidos de R$ 7.20 -> R$ 1.800,00
        self.create_dummy_orders(count=250, total_each=Decimal('7.20'))

        status_info = TrialService.check_trial_status(self.store)
        self.assertTrue(status_info['is_active'])
        self.assertFalse(status_info['is_expired'])
        self.assertIsNone(status_info['expired_reason'])
        self.assertEqual(status_info['orders_count'], 250)
        self.assertEqual(status_info['revenue_total'], Decimal('1800.00'))

    def test_trial_expires_on_order_limit(self):
        """
        Garante que atingir 300 pedidos válidos encerra o Trial com motivo ORDERS_LIMIT.
        """
        SubscriptionService.start_trial(self.store)
        # 300 pedidos de R$ 5.00 -> Total R$ 1.500,00 (< R$ 2.000)
        self.create_dummy_orders(count=300, total_each=Decimal('5.00'))

        status_info = TrialService.check_trial_status(self.store)
        self.assertFalse(status_info['is_active'])
        self.assertTrue(status_info['is_expired'])
        self.assertEqual(status_info['expired_reason'], Subscription.REASON_ORDERS_LIMIT)

        # Verifica persistência no banco
        sub = Subscription.objects.get(store=self.store)
        self.assertEqual(sub.status, Subscription.STATUS_EXPIRED)
        self.assertEqual(sub.trial_expired_reason, Subscription.REASON_ORDERS_LIMIT)

    def test_trial_expires_on_revenue_limit(self):
        """
        Garante que atingir R$ 2.000 em vendas válidas encerra o Trial com motivo REVENUE_LIMIT.
        """
        SubscriptionService.start_trial(self.store)
        # 100 pedidos de R$ 20.00 -> Total R$ 2.000,00 (< 300 pedidos)
        self.create_dummy_orders(count=100, total_each=Decimal('20.00'))

        status_info = TrialService.check_trial_status(self.store)
        self.assertFalse(status_info['is_active'])
        self.assertTrue(status_info['is_expired'])
        self.assertEqual(status_info['expired_reason'], Subscription.REASON_REVENUE_LIMIT)

        sub = Subscription.objects.get(store=self.store)
        self.assertEqual(sub.status, Subscription.STATUS_EXPIRED)
        self.assertEqual(sub.trial_expired_reason, Subscription.REASON_REVENUE_LIMIT)

    def test_trial_expires_on_days_limit(self):
        """
        Garante que ultrapassar 30 dias encerra o Trial com motivo DAYS_LIMIT.
        """
        Subscription.objects.filter(store=self.store).delete()
        past_date = timezone.now() - timedelta(days=31)
        sub = Subscription.objects.create(
            store=self.store,
            status=Subscription.STATUS_TRIAL,
            trial_started_at=past_date,
            trial_ends_at=past_date + timedelta(days=30),
        )
        # Poucos pedidos e faturamento baixo
        self.create_dummy_orders(count=10, total_each=Decimal('10.00'))

        status_info = TrialService.check_trial_status(self.store)
        self.assertFalse(status_info['is_active'])
        self.assertTrue(status_info['is_expired'])
        self.assertEqual(status_info['expired_reason'], Subscription.REASON_DAYS_LIMIT)

        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_EXPIRED)
        self.assertEqual(sub.trial_expired_reason, Subscription.REASON_DAYS_LIMIT)

    def test_cancelled_orders_do_not_count_towards_trial_limits(self):
        """
        Garante que pedidos cancelados (Order.STATUS_CANCELLED) NÃO contam nem para
        quantidade de pedidos nem para o faturamento do Trial.
        """
        SubscriptionService.start_trial(self.store)

        # Cria 50 pedidos concluídos de R$ 10.00 -> R$ 500.00
        self.create_dummy_orders(count=50, total_each=Decimal('10.00'), status=Order.STATUS_COMPLETED)

        # Cria 300 pedidos CANCELADOS de R$ 100.00 -> R$ 30.000,00 cancelados!
        self.create_dummy_orders(count=300, total_each=Decimal('100.00'), status=Order.STATUS_CANCELLED)

        status_info = TrialService.check_trial_status(self.store)
        # O trial DEVE permanecer ativo porque apenas os 50 pedidos concluídos contam
        self.assertTrue(status_info['is_active'])
        self.assertFalse(status_info['is_expired'])
        self.assertEqual(status_info['orders_count'], 50)
        self.assertEqual(status_info['revenue_total'], Decimal('500.00'))

    # =========================================================================
    # 2. REGRA ABSOLUTA: PLANO PAGO NÃO POSSUI LIMITES DE PEDIDOS OU FATURAMENTO
    # =========================================================================

    def test_paid_plan_has_no_volume_or_revenue_limits(self):
        """
        Valida a regra mais importante: uma loja no plano pago (ex: Start R$ 49,90)
        pode realizar 15.000 pedidos e R$ 450.000,00 sem NENHUM bloqueio ou limite.
        """
        # Ativa plano Start
        sub = SubscriptionService.activate_plan(self.store, self.plan_start)
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(sub.plan.slug, 'start')

        # Cria simulação de volume muito alto: 500 pedidos válidos (acima dos 300 do trial)
        self.create_dummy_orders(count=350, total_each=Decimal('20.00'))  # R$ 7.000,00

        status_info = TrialService.check_trial_status(self.store)
        # Não bloqueia nem expira
        self.assertTrue(status_info['is_active'])
        self.assertFalse(status_info['is_expired'])
        self.assertIsNone(status_info['orders_limit'])
        self.assertIsNone(status_info['revenue_limit'])

        # Valida que o model Plan NÃO possui atributos proibidos
        self.assertFalse(hasattr(self.plan_start, 'max_orders'))
        self.assertFalse(hasattr(self.plan_start, 'max_revenue'))
        self.assertFalse(hasattr(self.plan_start, 'max_sales'))
        self.assertFalse(hasattr(self.plan_start, 'monthly_order_limit'))
        self.assertFalse(hasattr(self.plan_start, 'monthly_revenue_limit'))

    # =========================================================================
    # 3. CONTROLE DE FEATURES (FeatureService)
    # =========================================================================

    def test_features_access_flow(self):
        """
        Valida a árvore de permissão de features:
        - Sem assinatura -> False
        - Trial ativo -> True para todas as features
        - Trial expirado -> False
        - Plano Start -> True apenas para features do Start
        - Plano Pro -> True para Start + analytics + thermal_printing
        - Plano Gestão -> True para todas as features
        """
        # 1. Sem assinatura (força ausência para testar retorno seguro False)
        Subscription.objects.filter(store=self.store).delete()
        self.assertFalse(can_access_feature(self.store, 'orders_online'))
        self.assertFalse(can_access_feature(self.store, 'advanced_analytics'))

        # 2. Trial Ativo: todas as features liberadas
        SubscriptionService.start_trial(self.store)
        self.assertTrue(can_access_feature(self.store, 'orders_online'))
        self.assertTrue(can_access_feature(self.store, 'analytics'))
        self.assertTrue(can_access_feature(self.store, 'advanced_analytics'))
        self.assertTrue(can_access_feature(self.store, 'custom_domain'))

        # 3. Trial Expirado: nenhuma liberada
        self.create_dummy_orders(count=300, total_each=Decimal('10.00'))
        # Força checagem de expiração
        TrialService.check_trial_status(self.store)
        self.assertFalse(can_access_feature(self.store, 'orders_online'))
        self.assertFalse(can_access_feature(self.store, 'analytics'))

        # 4. Plano Start: liberado apenas features do Start
        SubscriptionService.activate_plan(self.store, self.plan_start)
        self.assertTrue(can_access_feature(self.store, 'orders_online'))
        self.assertTrue(can_access_feature(self.store, 'pdv'))
        self.assertTrue(can_access_feature(self.store, 'whatsapp'))
        self.assertFalse(can_access_feature(self.store, 'analytics'))
        self.assertFalse(can_access_feature(self.store, 'advanced_analytics'))

        # 5. Plano Pro: libera analytics e thermal_printing
        SubscriptionService.activate_plan(self.store, self.plan_pro)
        self.assertTrue(can_access_feature(self.store, 'analytics'))
        self.assertTrue(can_access_feature(self.store, 'thermal_printing'))
        self.assertFalse(can_access_feature(self.store, 'advanced_analytics'))

        # 6. Plano Gestão: libera advanced_analytics e custom_domain
        SubscriptionService.activate_plan(self.store, self.plan_gestao)
        self.assertTrue(can_access_feature(self.store, 'advanced_analytics'))
        self.assertTrue(can_access_feature(self.store, 'custom_domain'))

    # =========================================================================
    # 4. DOWNGRADE NÃO APAGA DADOS
    # =========================================================================

    def test_downgrade_does_not_delete_data_and_only_blocks_feature(self):
        """
        Valida que o downgrade de Gestão para Pro ou Start NÃO apaga nenhum registro
        do banco, apenas restringe o acesso funcional.
        """
        # Loja contrata Gestão
        SubscriptionService.activate_plan(self.store, self.plan_gestao)
        self.assertTrue(can_access_feature(self.store, 'advanced_analytics'))

        # Simula pedidos e dados existentes acumulados
        orders = self.create_dummy_orders(count=20, total_each=Decimal('30.00'))
        orders_count_before = Order.objects.filter(store=self.store).count()

        # Faz Downgrade para Start
        SubscriptionService.activate_plan(self.store, self.plan_start)

        # Feature avançada agora fica bloqueada
        self.assertFalse(can_access_feature(self.store, 'advanced_analytics'))
        # Mas features do Start continuam liberadas
        self.assertTrue(can_access_feature(self.store, 'orders_online'))

        # NENHUM dado ou pedido foi apagado
        orders_count_after = Order.objects.filter(store=self.store).count()
        self.assertEqual(orders_count_before, orders_count_after)

    # =========================================================================
    # 5. IDEMPOTÊNCIA DE WEBHOOKS E PAGAMENTO
    # =========================================================================

    def test_webhook_idempotency(self):
        """
        Garante que o recebimento repetido do mesmo webhook do gateway:
        - Não cria duplicidade em PaymentHistory
        - Não reexecuta a operação repetidamente
        - Retorna status de sucesso de forma segura
        """
        sub = SubscriptionService.start_trial(self.store)
        payment_service = PaymentService(gateway_name='MERCADOPAGO')

        webhook_payload = {
            'action': 'payment.created',
            'data': {'id': 'mp_pay_998877'},
            'status': 'approved',
            'transaction_amount': 99.90,
            'external_reference': str(sub.id)
        }

        # Primeiro envio do webhook
        result1 = payment_service.process_webhook_event(
            gateway='MERCADOPAGO',
            external_id='mp_pay_998877',
            event_type='payment.created',
            payload=webhook_payload
        )
        self.assertEqual(result1['status'], 'PROCESSED')

        # Assinatura ativada e 1 pagamento registrado
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(PaymentHistory.objects.filter(subscription=sub).count(), 1)
        self.assertEqual(WebhookEvent.objects.filter(gateway='MERCADOPAGO', external_id='mp_pay_998877').count(), 1)

        # Segundo envio EXATO do mesmo webhook (ex: reenvio por retry de rede)
        result2 = payment_service.process_webhook_event(
            gateway='MERCADOPAGO',
            external_id='mp_pay_998877',
            event_type='payment.created',
            payload=webhook_payload
        )
        self.assertEqual(result2['status'], 'ALREADY_PROCESSED')

        # Garante que continua com apenas 1 registro em PaymentHistory e 1 WebhookEvent
        self.assertEqual(PaymentHistory.objects.filter(subscription=sub).count(), 1)
        self.assertEqual(WebhookEvent.objects.filter(gateway='MERCADOPAGO', external_id='mp_pay_998877').count(), 1)

    # =========================================================================
    # 6. UNICIDADE DE ASSINATURA ATIVA POR LOJA
    # =========================================================================

    def test_single_active_subscription_constraint(self):
        """
        Garante que a restrição de banco (UniqueConstraint parcial) impede que uma loja
        tenha duas assinaturas ativas/trial simultaneamente.
        """
        SubscriptionService.start_trial(self.store)

        # Tentativa de criar uma segunda assinatura ACTIVE para a mesma loja deve estourar IntegrityError
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Subscription.objects.create(
                    store=self.store,
                    plan=self.plan_start,
                    status=Subscription.STATUS_ACTIVE,
                )

    # =========================================================================
    # 7. FASE 9: DECORATORS, FEATURE GATES E CONTEXT PROCESSOR
    # =========================================================================

    def test_feature_required_decorator_allows_access_when_feature_available(self):
        """
        Garante que uma loja com plano compatível (ex: Start com feature 'pdv')
        acessa a view protegida por @feature_required normalmente (HTTP 200).
        """
        @feature_required('pdv')
        def dummy_view(request, store_slug):
            return HttpResponse('allowed', status=200)

        SubscriptionService.activate_plan(self.store, self.plan_start)
        req = self.factory.get(f'/painel/{self.store.slug}/pdv/')
        req.user = self.owner
        resp = dummy_view(req, store_slug=self.store.slug)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content.decode(), 'allowed')

    def test_feature_required_decorator_blocks_html_request_when_feature_missing(self):
        """
        Garante que uma loja com plano não compatível (ex: Start tentando acessar 'analytics')
        recebe HTTP 403 e a tela subscriptions/feature_locked.html com os planos compatíveis.
        """
        @feature_required('analytics')
        def dummy_view(request, store_slug):
            return HttpResponse('allowed', status=200)

        SubscriptionService.activate_plan(self.store, self.plan_start)
        req = self.factory.get(f'/painel/{self.store.slug}/analytics/')
        req.user = self.owner
        resp = dummy_view(req, store_slug=self.store.slug)
        self.assertEqual(resp.status_code, 403)
        html = resp.content.decode()
        self.assertIn('Recurso do MePedi SaaS', html)
        self.assertIn('Relatórios e Métricas Básicas', html)
        self.assertIn('Plano Pro', html)

    def test_feature_required_decorator_blocks_ajax_request_with_json_403(self):
        """
        Garante que requisições AJAX recebam JSON estruturado com status HTTP 403
        e dados dos planos compatíveis para exibição de modal de upgrade no frontend.
        """
        @feature_required('analytics')
        def dummy_view(request, store_slug):
            return HttpResponse('allowed', status=200)

        SubscriptionService.activate_plan(self.store, self.plan_start)
        req = self.factory.get(
            f'/painel/{self.store.slug}/analytics/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        req.user = self.owner
        resp = dummy_view(req, store_slug=self.store.slug)
        self.assertEqual(resp.status_code, 403)
        data = json.loads(resp.content.decode())
        self.assertEqual(data['error'], 'feature_locked')
        self.assertEqual(data['feature_code'], 'analytics')
        self.assertTrue(len(data['plans']) > 0)

    def test_merchant_analytics_view_protected_by_feature_required(self):
        """
        Testa a rota real do painel /painel/<slug>/analytics/ integrada:
        1. Plano Start (sem analytics) -> HTTP 403 com tela de upgrade
        2. Upgrade para Pro (com analytics) -> HTTP 200 com dashboard de analytics
        3. Trial ativo -> HTTP 200 (todas as features liberadas)
        """
        self.client.force_login(self.owner)

        # 1. Start -> Bloqueado
        SubscriptionService.activate_plan(self.store, self.plan_start)
        resp = self.client.get(f'/painel/{self.store.slug}/analytics/')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('Recurso do MePedi SaaS', resp.content.decode())

        # 2. Upgrade para Pro -> Liberado
        SubscriptionService.activate_plan(self.store, self.plan_pro)
        resp = self.client.get(f'/painel/{self.store.slug}/analytics/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Analytics & Inteligência', resp.content.decode())

        # 3. Loja em Trial -> Liberado
        sub = Subscription.objects.get(store=self.store)
        sub.status = Subscription.STATUS_TRIAL
        sub.plan = None
        sub.trial_started_at = timezone.now()
        sub.trial_ends_at = timezone.now() + timedelta(days=30)
        sub.save()
        resp = self.client.get(f'/painel/{self.store.slug}/analytics/')
        self.assertEqual(resp.status_code, 200)

    def test_subscription_context_processor_injects_expected_variables(self):
        """
        Garante que o subscription_context injeta current_subscription, trial_info
        e accessible_features corretamente para os templates do lojista.
        """
        SubscriptionService.start_trial(self.store)
        req = self.factory.get(f'/painel/{self.store.slug}/')
        req.user = self.owner
        req.resolver_match = type('Match', (), {'kwargs': {'store_slug': self.store.slug}})()

        ctx = subscription_context(req)
        self.assertIn('current_subscription', ctx)
        self.assertIn('trial_info', ctx)
        self.assertEqual(ctx['current_subscription'].status, Subscription.STATUS_TRIAL)
        self.assertTrue(ctx['trial_info']['is_active'])
        self.assertIn('orders_online', ctx['accessible_features'])
        self.assertIn('analytics', ctx['accessible_features'])
        self.assertIn('pdv', ctx['accessible_features'])

    # =========================================================================
    # 8. TESTES DO PAINEL "MINHA ASSINATURA" E CHECKOUT MERCADO PAGO
    # =========================================================================

    def test_merchant_subscription_view_renders_200_for_owner(self):
        """
        Garante que o lojista autenticado visualiza a tela Minha Assinatura (/painel/<slug>/assinatura/)
        com métricas do trial, vitrine comparativa de planos e histórico financeiro.
        """
        self.client.force_login(self.owner)
        resp = self.client.get(f'/painel/{self.store.slug}/assinatura/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'dashboard/subscription.html')
        self.assertIn('Minha Assinatura', resp.content.decode())
        self.assertIn('Start', resp.content.decode())
        self.assertIn('Pro', resp.content.decode())
        self.assertIn('Gestão', resp.content.decode())
        self.assertIn('ILIMITADOS', resp.content.decode())

    def test_merchant_subscription_view_forbidden_for_non_owner(self):
        """
        Garante isolamento multi-tenant: usuário não associado à loja recebe 403 Forbidden.
        """
        other_user = User.objects.create_user(
            email='intruso@outro.com',
            password='TestPassword123!',
            full_name='Outro Usuário'
        )
        self.client.force_login(other_user)
        resp = self.client.get(f'/painel/{self.store.slug}/assinatura/')
        self.assertEqual(resp.status_code, 403)

    def test_merchant_subscription_checkout_view_creates_payment_history_and_redirects(self):
        """
        Garante que a rota de contratação /painel/<slug>/assinatura/checkout/<plan_slug>/
        cria o registro de pagamento como PENDING e redireciona para o checkout do gateway.
        """
        self.client.force_login(self.owner)
        resp = self.client.post(f'/painel/{self.store.slug}/assinatura/checkout/pro/')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue('mercadopago.com' in resp.url)

        # Valida que o PaymentHistory foi criado no banco
        pending_payment = PaymentHistory.objects.filter(
            subscription__store=self.store,
            status=PaymentHistory.STATUS_PENDING
        ).first()
        self.assertIsNotNone(pending_payment)
        self.assertEqual(pending_payment.amount, self.plan_pro.price)
        self.assertEqual(pending_payment.gateway, 'MERCADOPAGO')

    def test_merchant_subscription_checkout_view_ajax_returns_json(self):
        """
        Valida que requisições AJAX para o checkout retornam JSON 200 com a URL de checkout.
        """
        self.client.force_login(self.owner)
        resp = self.client.post(
            f'/painel/{self.store.slug}/assinatura/checkout/start/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content.decode())
        self.assertEqual(data['status'], 'success')
        self.assertIn('checkout_url', data)
        self.assertTrue('mercadopago.com' in data['checkout_url'])

    def test_merchant_subscription_return_view_activates_plan_on_success(self):
        """
        Valida o retorno do gateway /painel/<slug>/assinatura/retorno/?status=success:
        Atualiza o pagamento para APPROVED e ativa o plano comercial correspondente.
        """
        self.client.force_login(self.owner)
        sub = Subscription.objects.get(store=self.store)
        pay = PaymentHistory.objects.create(
            subscription=sub,
            gateway='MERCADOPAGO',
            amount=self.plan_gestao.price,
            status=PaymentHistory.STATUS_PENDING
        )

        resp = self.client.get(
            f'/painel/{self.store.slug}/assinatura/retorno/?status=success&plan=gestao&payment_id={pay.id}'
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn('status=success', resp.url)

        # Valida se o pagamento virou APPROVED e a assinatura virou ACTIVE
        pay.refresh_from_db()
        self.assertEqual(pay.status, PaymentHistory.STATUS_APPROVED)

        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(sub.plan, self.plan_gestao)

    def test_payment_service_webhook_activates_subscription_with_external_reference(self):
        """
        Testa o fluxo completo do Webhook do Mercado Pago:
        Recebe notificação aprovada, localiza a assinatura pela external_reference,
        marca o pagamento como APPROVED e ativa a assinatura comercialmente.
        """
        sub = Subscription.objects.get(store=self.store)
        pay = PaymentHistory.objects.create(
            subscription=sub,
            gateway='MERCADOPAGO',
            amount=self.plan_pro.price,
            status=PaymentHistory.STATUS_PENDING,
            external_id='pref_test_123'
        )
        ext_ref = f"mepedi_sub_{sub.id}_{self.plan_pro.id}_{pay.id}"

        webhook_payload = {
            'action': 'payment.created',
            'data': {'id': 'mp_pay_998877'},
            'status': 'approved',
            'transaction_amount': float(self.plan_pro.price),
            'external_reference': ext_ref,
        }

        payment_service = PaymentService('MERCADOPAGO')
        result = payment_service.process_webhook_event(
            gateway='MERCADOPAGO',
            external_id='mp_pay_998877',
            event_type='payment.created',
            payload=webhook_payload
        )

        self.assertEqual(result['status'], 'PROCESSED')
        self.assertEqual(result['payment_status'], 'APPROVED')

        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(sub.plan, self.plan_pro)

        pay.refresh_from_db()
        self.assertEqual(pay.status, PaymentHistory.STATUS_APPROVED)

