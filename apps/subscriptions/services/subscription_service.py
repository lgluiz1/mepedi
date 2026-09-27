from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from ..models import Feature, Plan, Subscription


class SubscriptionService:
    """
    Serviço central de ciclo de vida das assinaturas (SaaS MePedi).
    Garante atomicidade em banco de dados e controle de concorrência com select_for_update().
    """

    @classmethod
    def get_current_subscription(cls, store):
        """
        Retorna a assinatura atual (ativa, trial ou mais recente) da loja.
        """
        return Subscription.objects.filter(
            store=store
        ).order_by('-created_at').first()

    @classmethod
    @transaction.atomic
    def start_trial(cls, store, start_date=None):
        """
        Inicia o Trial gratuito de 30 dias para uma loja.
        Garante que a loja não tenha múltiplas assinaturas ativas concorrentes.
        """
        now = start_date or timezone.now()
        trial_end = now + timedelta(days=30)

        # Bloqueia registros de assinatura da loja para evitar corrida
        existing = Subscription.objects.select_for_update().filter(
            store=store,
            status__in=[Subscription.STATUS_TRIAL, Subscription.STATUS_ACTIVE, Subscription.STATUS_PAST_DUE]
        ).first()

        if existing:
            return existing

        subscription = Subscription.objects.create(
            store=store,
            plan=None,
            status=Subscription.STATUS_TRIAL,
            trial_started_at=now,
            trial_ends_at=trial_end,
        )
        return subscription

    @classmethod
    @transaction.atomic
    def activate_plan(cls, store, plan, started_at=None, external_customer_id='', external_subscription_id=''):
        """
        Ativa ou atualiza o plano pago comercial para a loja.
        NUNCA impõe limites de pedidos ou faturamento para planos pagos.
        """
        now = started_at or timezone.now()
        period_days = 365 if plan.billing_cycle == Plan.BILLING_YEARLY else 30
        period_end = now + timedelta(days=period_days)

        # Localiza qualquer assinatura existente com lock
        sub = Subscription.objects.select_for_update().filter(
            store=store,
            status__in=[Subscription.STATUS_TRIAL, Subscription.STATUS_ACTIVE, Subscription.STATUS_PAST_DUE]
        ).first()

        if sub:
            sub.plan = plan
            sub.status = Subscription.STATUS_ACTIVE
            sub.started_at = sub.started_at or now
            sub.current_period_start = now
            sub.current_period_end = period_end
            if external_customer_id:
                sub.external_customer_id = external_customer_id
            if external_subscription_id:
                sub.external_subscription_id = external_subscription_id
            sub.save()
            return sub
        else:
            sub = Subscription.objects.create(
                store=store,
                plan=plan,
                status=Subscription.STATUS_ACTIVE,
                started_at=now,
                current_period_start=now,
                current_period_end=period_end,
                external_customer_id=external_customer_id,
                external_subscription_id=external_subscription_id,
            )
            return sub

    @classmethod
    @transaction.atomic
    def cancel_subscription(cls, store, reason=''):
        """
        Cancela a assinatura atual da loja.
        Dados nunca são apagados no cancelamento.
        """
        sub = Subscription.objects.select_for_update().filter(
            store=store,
            status__in=[Subscription.STATUS_TRIAL, Subscription.STATUS_ACTIVE, Subscription.STATUS_PAST_DUE]
        ).first()

        if sub:
            sub.status = Subscription.STATUS_CANCELLED
            sub.cancelled_at = timezone.now()
            sub.cancel_reason = reason
            sub.save(update_fields=['status', 'cancelled_at', 'cancel_reason', 'updated_at'])
            return sub
        return None

    @classmethod
    @transaction.atomic
    def seed_default_saas_data(cls):
        """
        Inicialização idempotente das funcionalidades (Features) e Planos Comerciais (Start, Pro, Gestão).
        Execuções sucessivas não duplicam dados nem sobrescrevem personalizações manuais indesejadas.
        """
        # 1. Definição das Features
        features_data = [
            {'code': 'orders_online', 'name': 'Pedidos Online (Cardápio Digital)', 'description': 'Recebimento de pedidos via cardápio online com autoatendimento.'},
            {'code': 'pdv', 'name': 'Frente de Caixa (PDV Balcão)', 'description': 'Operação de balcão e atendimento presencial com controle de operador.'},
            {'code': 'inventory', 'name': 'Controle de Estoque', 'description': 'Gestão de ingredientes, insumos e baixa automática por itens vendidos.'},
            {'code': 'analytics', 'name': 'Relatórios e Métricas Básicas', 'description': 'Painel de métricas operacionais, faturamento e produtos mais vendidos.'},
            {'code': 'advanced_analytics', 'name': 'Analytics Avançado & Cohort', 'description': 'Análise aprofundada de comportamento de consumo, retenção e ticket médio.'},
            {'code': 'customer_history', 'name': 'Histórico Completo de Clientes', 'description': 'Cadastro enriquecido, histórico de consumo e hábitos de clientes.'},
            {'code': 'whatsapp', 'name': 'Integração WhatsApp & Avisos', 'description': 'Notificações automáticas de status de pedido e carrinho via WhatsApp.'},
            {'code': 'multi_user', 'name': 'Múltiplos Usuários e Operadores', 'description': 'Gestão de permissões para atendentes, gerentes e operadores.'},
            {'code': 'thermal_printing', 'name': 'Impressão Térmica Direta', 'description': 'Emissão de comandas e vias de produção em impressoras térmicas (58mm/80mm).'},
            {'code': 'custom_domain', 'name': 'Domínio Próprio Personalizado', 'description': 'Utilização de domínio próprio exclusivo para a loja (ex: suapizzaria.com.br).'},
        ]

        feature_instances = {}
        for feat in features_data:
            obj, _ = Feature.objects.update_or_create(
                code=feat['code'],
                defaults={
                    'name': feat['name'],
                    'description': feat['description'],
                    'is_active': True,
                }
            )
            feature_instances[feat['code']] = obj

        # 2. Definição dos Planos Comerciais
        # START: R$ 49,90/mês
        # Features: orders_online, pdv, inventory, whatsapp, customer_history
        start_plan, _ = Plan.objects.update_or_create(
            slug='start',
            defaults={
                'name': 'Start',
                'description': 'Ideal para quem está começando e quer vender online e no balcão de forma profissional.',
                'price': Decimal('49.90'),
                'billing_cycle': Plan.BILLING_MONTHLY,
                'is_active': True,
                'display_order': 1,
            }
        )
        start_features = [
            feature_instances['orders_online'],
            feature_instances['pdv'],
            feature_instances['inventory'],
            feature_instances['whatsapp'],
            feature_instances['customer_history'],
        ]
        start_plan.features.set(start_features)

        # PRO: R$ 99,90/mês
        # Features: Start + analytics, thermal_printing
        pro_plan, _ = Plan.objects.update_or_create(
            slug='pro',
            defaults={
                'name': 'Pro',
                'description': 'Para estabelecimentos consolidados que buscam controle analítico e agilidade operacional.',
                'price': Decimal('99.90'),
                'billing_cycle': Plan.BILLING_MONTHLY,
                'is_active': True,
                'display_order': 2,
            }
        )
        pro_features = start_features + [
            feature_instances['analytics'],
            feature_instances['thermal_printing'],
        ]
        pro_plan.features.set(pro_features)

        # GESTÃO: R$ 199,90/mês
        # Features: Pro + advanced_analytics, multi_user, custom_domain
        gestao_plan, _ = Plan.objects.update_or_create(
            slug='gestao',
            defaults={
                'name': 'Gestão',
                'description': 'Solução completa para operações de alto volume, franquias e equipes multidisciplinares.',
                'price': Decimal('199.90'),
                'billing_cycle': Plan.BILLING_MONTHLY,
                'is_active': True,
                'display_order': 3,
            }
        )
        gestao_features = pro_features + [
            feature_instances['advanced_analytics'],
            feature_instances['multi_user'],
            feature_instances['custom_domain'],
        ]
        gestao_plan.features.set(gestao_features)

        return {
            'features': feature_instances,
            'plans': {
                'start': start_plan,
                'pro': pro_plan,
                'gestao': gestao_plan,
            }
        }
