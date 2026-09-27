import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from core.models import TimeStampedModel


class Feature(TimeStampedModel):
    """
    Funcionalidade do sistema controlada por plano ou trial.
    """
    code = models.SlugField(
        _('Código da Funcionalidade'),
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_('Identificador único da funcionalidade (ex: orders_online, pdv, analytics).')
    )
    name = models.CharField(
        _('Nome'),
        max_length=100,
        help_text=_('Nome legível da funcionalidade.')
    )
    description = models.TextField(
        _('Descrição'),
        blank=True,
        help_text=_('Detalhamento da funcionalidade.')
    )
    is_active = models.BooleanField(
        _('Ativa'),
        default=True,
        help_text=_('Indica se a funcionalidade está globalmente ativa no sistema.')
    )

    class Meta:
        verbose_name = _('Funcionalidade')
        verbose_name_plural = _('Funcionalidades')
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class Plan(TimeStampedModel):
    """
    Model representativo EXCLUSIVAMENTE dos planos comerciais pagos do SaaS MePedi.

    REGRA ABSOLUTA DO MEPEDI:
    Os planos pagos NÃO possuem limite de pedidos, faturamento ou vendas.
    NÃO POSSUEM max_orders, max_revenue ou equivalentes.
    A diferenciação entre planos é EXCLUSIVAMENTE Features + Preço.
    """
    BILLING_MONTHLY = 'MONTHLY'
    BILLING_YEARLY = 'YEARLY'
    BILLING_CHOICES = [
        (BILLING_MONTHLY, _('Mensal')),
        (BILLING_YEARLY, _('Anual')),
    ]

    name = models.CharField(
        _('Nome Comercial'),
        max_length=100,
        help_text=_('Nome de exibição do plano (ex: Start, Pro, Gestão).')
    )
    slug = models.SlugField(
        _('Slug'),
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_('Identificador único em URLs e integrações (ex: start, pro, gestao).')
    )
    description = models.TextField(
        _('Descrição Comercial'),
        blank=True,
        help_text=_('Apresentação dos benefícios e proposta de valor do plano.')
    )
    price = models.DecimalField(
        _('Preço (R$)'),
        max_digits=10,
        decimal_places=2,
        help_text=_('Valor cobrado por ciclo de faturamento.')
    )
    billing_cycle = models.CharField(
        _('Ciclo de Faturamento'),
        max_length=10,
        choices=BILLING_CHOICES,
        default=BILLING_MONTHLY
    )
    is_active = models.BooleanField(
        _('Ativo para Novas Contratações'),
        default=True,
        help_text=_('Permite desativar um plano sem apagar o histórico de quem já contratou.')
    )
    display_order = models.PositiveIntegerField(
        _('Ordem de Exibição'),
        default=0,
        help_text=_('Ordenação dos planos na vitrine e checkout.')
    )
    features = models.ManyToManyField(
        Feature,
        related_name='plans',
        blank=True,
        verbose_name=_('Funcionalidades Inclusas')
    )

    class Meta:
        verbose_name = _('Plano Comercial')
        verbose_name_plural = _('Planos Comerciais')
        ordering = ['display_order', 'price']

    def __str__(self):
        return f"{self.name} - R$ {self.price}/{self.get_billing_cycle_display()}"


class Subscription(TimeStampedModel):
    """
    Assinatura do estabelecimento (Store) no SaaS MePedi.
    Controla o ciclo de vida da loja (Trial, Ativo, Vencido, Suspenso, Cancelado, Expirado).
    """
    STATUS_TRIAL = 'TRIAL'
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_PAST_DUE = 'PAST_DUE'
    STATUS_SUSPENDED = 'SUSPENDED'
    STATUS_CANCELLED = 'CANCELLED'
    STATUS_EXPIRED = 'EXPIRED'

    STATUS_CHOICES = [
        (STATUS_TRIAL, _('Em Período de Testes (Trial)')),
        (STATUS_ACTIVE, _('Ativa')),
        (STATUS_PAST_DUE, _('Pagamento Pendente / Atrasado')),
        (STATUS_SUSPENDED, _('Suspensa')),
        (STATUS_CANCELLED, _('Cancelada')),
        (STATUS_EXPIRED, _('Expirada')),
    ]

    REASON_DAYS_LIMIT = 'DAYS_LIMIT'
    REASON_ORDERS_LIMIT = 'ORDERS_LIMIT'
    REASON_REVENUE_LIMIT = 'REVENUE_LIMIT'

    EXPIRED_REASON_CHOICES = [
        (REASON_DAYS_LIMIT, _('Limite de Dias Atingido (30 dias)')),
        (REASON_ORDERS_LIMIT, _('Limite de Pedidos Válidos Atingido (300 pedidos)')),
        (REASON_REVENUE_LIMIT, _('Limite de Faturamento Atingido (R$ 2.000,00)')),
    ]

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='subscriptions',
        verbose_name=_('Loja')
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='subscriptions',
        verbose_name=_('Plano Contratado'),
        help_text=_('Nulo se a loja estiver em Trial inicial sem plano contratado.')
    )
    status = models.CharField(
        _('Status da Assinatura'),
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_TRIAL,
        db_index=True
    )

    # Ciclo de Trial
    trial_started_at = models.DateTimeField(
        _('Início do Trial'),
        null=True,
        blank=True
    )
    trial_ends_at = models.DateTimeField(
        _('Fim Previsto do Trial'),
        null=True,
        blank=True
    )
    trial_expired_reason = models.CharField(
        _('Motivo do Encerramento do Trial'),
        max_length=30,
        choices=EXPIRED_REASON_CHOICES,
        null=True,
        blank=True,
        help_text=_('Primeiro motivo atingido: DAYS_LIMIT, ORDERS_LIMIT ou REVENUE_LIMIT.')
    )

    # Ciclo Comercial (Plano Pago)
    started_at = models.DateTimeField(
        _('Data de Ativação do Plano Pago'),
        null=True,
        blank=True
    )
    current_period_start = models.DateTimeField(
        _('Início do Ciclo Atual'),
        null=True,
        blank=True
    )
    current_period_end = models.DateTimeField(
        _('Fim do Ciclo Atual'),
        null=True,
        blank=True
    )

    # Cancelamento
    cancelled_at = models.DateTimeField(
        _('Data de Cancelamento'),
        null=True,
        blank=True
    )
    cancel_reason = models.TextField(
        _('Motivo do Cancelamento'),
        blank=True
    )

    # Identificadores no Gateway de Pagamento
    external_customer_id = models.CharField(
        _('ID do Cliente no Gateway'),
        max_length=100,
        blank=True,
        db_index=True
    )
    external_subscription_id = models.CharField(
        _('ID da Assinatura no Gateway'),
        max_length=100,
        blank=True,
        db_index=True
    )

    class Meta:
        verbose_name = _('Assinatura')
        verbose_name_plural = _('Assinaturas')
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['store'],
                condition=models.Q(status__in=['TRIAL', 'ACTIVE', 'PAST_DUE']),
                name='unique_active_or_trial_subscription_per_store'
            )
        ]

    def __str__(self):
        plan_name = self.plan.name if self.plan else "Sem Plano (Trial)"
        return f"{self.store.name} - {plan_name} ({self.get_status_display()})"

    @property
    def is_trial(self):
        return self.status == self.STATUS_TRIAL

    @property
    def is_active(self):
        return self.status == self.STATUS_ACTIVE


class PaymentGatewayConfig(TimeStampedModel):
    """
    Configuração de credenciais e parâmetros para integração com Gateways.
    """
    GATEWAY_MERCADOPAGO = 'MERCADOPAGO'
    GATEWAY_ASAAS = 'ASAAS'
    GATEWAY_STRIPE = 'STRIPE'
    GATEWAY_CHOICES = [
        (GATEWAY_MERCADOPAGO, 'Mercado Pago'),
        (GATEWAY_ASAAS, 'Asaas'),
        (GATEWAY_STRIPE, 'Stripe'),
    ]

    ENV_SANDBOX = 'SANDBOX'
    ENV_PRODUCTION = 'PRODUCTION'
    ENV_CHOICES = [
        (ENV_SANDBOX, 'Sandbox / Testes'),
        (ENV_PRODUCTION, 'Produção'),
    ]

    gateway = models.CharField(
        _('Gateway'),
        max_length=30,
        choices=GATEWAY_CHOICES,
        default=GATEWAY_MERCADOPAGO
    )
    environment = models.CharField(
        _('Ambiente'),
        max_length=20,
        choices=ENV_CHOICES,
        default=ENV_SANDBOX
    )
    access_token = models.CharField(
        _('Access Token'),
        max_length=255,
        blank=True,
        help_text=_('Credencial secreta da API do Gateway.')
    )
    public_key = models.CharField(
        _('Public Key'),
        max_length=255,
        blank=True,
        help_text=_('Chave pública para frontend / checkout.')
    )
    webhook_secret = models.CharField(
        _('Webhook Secret'),
        max_length=255,
        blank=True,
        help_text=_('Segredo de validação das assinaturas de webhook.')
    )
    is_active = models.BooleanField(
        _('Ativo'),
        default=True
    )

    class Meta:
        verbose_name = _('Configuração de Gateway')
        verbose_name_plural = _('Configurações de Gateway')
        constraints = [
            models.UniqueConstraint(
                fields=['gateway', 'environment'],
                name='unique_gateway_per_environment'
            )
        ]

    def __str__(self):
        return f"{self.get_gateway_display()} ({self.get_environment_display()})"

    @property
    def masked_access_token(self):
        if not self.access_token:
            return ""
        if len(self.access_token) <= 8:
            return "••••••••"
        return f"••••••••••••{self.access_token[-4:]}"

    @property
    def masked_public_key(self):
        if not self.public_key:
            return ""
        if len(self.public_key) <= 8:
            return "••••••••"
        return f"••••••••••••{self.public_key[-4:]}"


class PaymentHistory(TimeStampedModel):
    """
    Registro histórico financeiro e imutável de pagamentos de assinaturas.
    """
    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_REFUNDED = 'REFUNDED'
    STATUS_CANCELLED = 'CANCELLED'

    STATUS_CHOICES = [
        (STATUS_PENDING, _('Pendente')),
        (STATUS_APPROVED, _('Aprovado')),
        (STATUS_REJECTED, _('Rejeitado')),
        (STATUS_REFUNDED, _('Reembolsado')),
        (STATUS_CANCELLED, _('Cancelado')),
    ]

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name=_('Assinatura')
    )
    gateway = models.CharField(
        _('Gateway'),
        max_length=30,
        default='MERCADOPAGO'
    )
    external_id = models.CharField(
        _('ID da Transação no Gateway'),
        max_length=150,
        blank=True,
        db_index=True
    )
    amount = models.DecimalField(
        _('Valor Cobrado (R$)'),
        max_digits=10,
        decimal_places=2
    )
    status = models.CharField(
        _('Status'),
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True
    )
    payment_date = models.DateTimeField(
        _('Data de Pagamento'),
        null=True,
        blank=True
    )
    raw_payload = models.JSONField(
        _('Payload Bruto do Gateway'),
        default=dict,
        blank=True
    )

    class Meta:
        verbose_name = _('Histórico de Pagamento')
        verbose_name_plural = _('Histórico de Pagamentos')
        ordering = ['-created_at']

    def __str__(self):
        return f"Pagamento {self.external_id or self.id} - R$ {self.amount} ({self.get_status_display()})"


class WebhookEvent(TimeStampedModel):
    """
    Registro de eventos de Webhook para garantia de idempotência e auditoria.
    """
    STATUS_PENDING = 'PENDING'
    STATUS_PROCESSED = 'PROCESSED'
    STATUS_IGNORED = 'IGNORED'
    STATUS_FAILED = 'FAILED'

    STATUS_CHOICES = [
        (STATUS_PENDING, _('Pendente')),
        (STATUS_PROCESSED, _('Processado')),
        (STATUS_IGNORED, _('Ignorado')),
        (STATUS_FAILED, _('Falhou')),
    ]

    gateway = models.CharField(
        _('Gateway'),
        max_length=30,
        default='MERCADOPAGO',
        db_index=True
    )
    external_id = models.CharField(
        _('ID do Evento / Notificação'),
        max_length=150,
        db_index=True
    )
    event_type = models.CharField(
        _('Tipo de Evento'),
        max_length=100,
        blank=True,
        db_index=True
    )
    payload = models.JSONField(
        _('Payload Recebido'),
        default=dict
    )
    status = models.CharField(
        _('Status do Processamento'),
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True
    )
    processed_at = models.DateTimeField(
        _('Processado em'),
        null=True,
        blank=True
    )
    error_message = models.TextField(
        _('Mensagem de Erro'),
        blank=True
    )

    class Meta:
        verbose_name = _('Evento de Webhook')
        verbose_name_plural = _('Eventos de Webhook')
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['gateway', 'external_id'],
                name='unique_webhook_event_per_gateway'
            )
        ]

    def __str__(self):
        return f"{self.gateway} - {self.event_type} ({self.external_id}) [{self.get_status_display()}]"
