from datetime import timedelta
from decimal import Decimal
from django.db import migrations
from django.utils import timezone


def seed_saas_data_and_transition_stores(apps, schema_editor):
    Feature = apps.get_model('subscriptions', 'Feature')
    Plan = apps.get_model('subscriptions', 'Plan')
    Subscription = apps.get_model('subscriptions', 'Subscription')
    Store = apps.get_model('stores', 'Store')

    # 1. Features
    features_def = [
        ('orders_online', 'Pedidos Online (Cardápio Digital)', 'Recebimento de pedidos via cardápio online com autoatendimento.'),
        ('pdv', 'Frente de Caixa (PDV Balcão)', 'Operação de balcão e atendimento presencial com controle de operador.'),
        ('inventory', 'Controle de Estoque', 'Gestão de ingredientes, insumos e baixa automática por itens vendidos.'),
        ('analytics', 'Relatórios e Métricas Básicas', 'Painel de métricas operacionais, faturamento e produtos mais vendidos.'),
        ('advanced_analytics', 'Analytics Avançado & Cohort', 'Análise aprofundada de comportamento de consumo, retenção e ticket médio.'),
        ('customer_history', 'Histórico Completo de Clientes', 'Cadastro enriquecido, histórico de consumo e hábitos de clientes.'),
        ('whatsapp', 'Integração WhatsApp & Avisos', 'Notificações automáticas de status de pedido e carrinho via WhatsApp.'),
        ('multi_user', 'Múltiplos Usuários e Operadores', 'Gestão de permissões para atendentes, gerentes e operadores.'),
        ('thermal_printing', 'Impressão Térmica Direta', 'Emissão de comandas e vias de produção em impressoras térmicas (58mm/80mm).'),
        ('custom_domain', 'Domínio Próprio Personalizado', 'Utilização de domínio próprio exclusivo para a loja (ex: suapizzaria.com.br).'),
    ]

    features_map = {}
    for code, name, desc in features_def:
        feat, _ = Feature.objects.get_or_create(
            code=code,
            defaults={'name': name, 'description': desc, 'is_active': True}
        )
        features_map[code] = feat

    # 2. Planos Comerciais (NÃO possuem max_orders nem max_revenue)
    # START: R$ 49,90/mês
    start_plan, _ = Plan.objects.get_or_create(
        slug='start',
        defaults={
            'name': 'Start',
            'description': 'Ideal para quem está começando e quer vender online e no balcão de forma profissional.',
            'price': Decimal('49.90'),
            'billing_cycle': 'MONTHLY',
            'is_active': True,
            'display_order': 1,
        }
    )
    start_features = [
        features_map['orders_online'],
        features_map['pdv'],
        features_map['inventory'],
        features_map['whatsapp'],
        features_map['customer_history'],
    ]
    start_plan.features.set(start_features)

    # PRO: R$ 99,90/mês
    pro_plan, _ = Plan.objects.get_or_create(
        slug='pro',
        defaults={
            'name': 'Pro',
            'description': 'Para estabelecimentos consolidados que buscam controle analítico e agilidade operacional.',
            'price': Decimal('99.90'),
            'billing_cycle': 'MONTHLY',
            'is_active': True,
            'display_order': 2,
        }
    )
    pro_features = start_features + [
        features_map['analytics'],
        features_map['thermal_printing'],
    ]
    pro_plan.features.set(pro_features)

    # GESTÃO: R$ 199,90/mês
    gestao_plan, _ = Plan.objects.get_or_create(
        slug='gestao',
        defaults={
            'name': 'Gestão',
            'description': 'Solução completa para operações de alto volume, franquias e equipes multidisciplinares.',
            'price': Decimal('199.90'),
            'billing_cycle': 'MONTHLY',
            'is_active': True,
            'display_order': 3,
        }
    )
    gestao_features = pro_features + [
        features_map['advanced_analytics'],
        features_map['multi_user'],
        features_map['custom_domain'],
    ]
    gestao_plan.features.set(gestao_features)

    # 3. Transição para lojas existentes (Seção 26):
    # Preserva o funcionamento operacional de lojas existentes criando um Trial inicial de 30 dias.
    # Não inventa assinatura paga inexistente.
    now = timezone.now()
    for store in Store.objects.all():
        has_sub = Subscription.objects.filter(
            store=store,
            status__in=['TRIAL', 'ACTIVE', 'PAST_DUE']
        ).exists()
        if not has_sub:
            Subscription.objects.create(
                store=store,
                plan=None,
                status='TRIAL',
                trial_started_at=now,
                trial_ends_at=now + timedelta(days=30),
            )


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0001_initial'),
        ('stores', '0004_store_fixed_delivery_fee'),
    ]

    operations = [
        migrations.RunPython(seed_saas_data_and_transition_stores, reverse_noop),
    ]
