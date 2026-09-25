from decimal import Decimal
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import StoreBoundedModel, UUIDModel, TimeStampedModel


class Order(StoreBoundedModel, UUIDModel):
    """
    Entidade central de Pedido na plataforma IA-Pedidos.
    Armazena o cabeçalho, status, valores recalculados e dados cadastrais/endereço congelados.
    """
    # Status do Pedido
    STATUS_NEW = 'NOVO'
    STATUS_ACCEPTED = 'ACEITO'
    STATUS_PREPARING = 'EM_PREPARACAO'
    STATUS_READY = 'PRONTO'
    STATUS_OUT_FOR_DELIVERY = 'SAIU_PARA_ENTREGA'
    STATUS_COMPLETED = 'CONCLUIDO'
    STATUS_CANCELLED = 'CANCELADO'

    STATUS_CHOICES = [
        (STATUS_NEW, _('Novo')),
        (STATUS_ACCEPTED, _('Aceito')),
        (STATUS_PREPARING, _('Em Preparação')),
        (STATUS_READY, _('Pronto para Retirada / Envio')),
        (STATUS_OUT_FOR_DELIVERY, _('Saiu para Entrega')),
        (STATUS_COMPLETED, _('Concluído')),
        (STATUS_CANCELLED, _('Cancelado')),
    ]

    # Modalidade de Atendimento
    TYPE_DELIVERY = 'DELIVERY'
    TYPE_PICKUP = 'PICKUP'

    TYPE_CHOICES = [
        (TYPE_DELIVERY, _('Entrega')),
        (TYPE_PICKUP, _('Retirada na Loja')),
    ]

    # Formas de Pagamento (Informativas no MVP)
    PAY_MONEY = 'MONEY'
    PAY_PIX = 'PIX'
    PAY_DEBIT = 'DEBIT_CARD'
    PAY_CREDIT = 'CREDIT_CARD'
    PAY_MEAL = 'MEAL_VOUCHER'
    PAY_OTHER = 'OTHER'

    PAYMENT_CHOICES = [
        (PAY_MONEY, _('Dinheiro')),
        (PAY_PIX, _('Pix')),
        (PAY_DEBIT, _('Cartão de Débito (na entrega)')),
        (PAY_CREDIT, _('Cartão de Crédito (na entrega)')),
        (PAY_MEAL, _('Vale-Refeição')),
        (PAY_OTHER, _('Outros')),
    ]

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='orders',
        verbose_name=_('Cliente')
    )
    order_number = models.PositiveIntegerField(
        _('Número do Pedido'),
        db_index=True,
        help_text=_('Identificador amigável sequencial por loja (ex: 1001, 1002).')
    )
    status = models.CharField(
        _('Status'),
        max_length=25,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
        db_index=True
    )
    delivery_type = models.CharField(
        _('Modalidade'),
        max_length=15,
        choices=TYPE_CHOICES,
        default=TYPE_DELIVERY
    )

    # Valores Financeiros (Sempre recalculados no servidor)
    subtotal = models.DecimalField(
        _('Subtotal dos Itens (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    delivery_fee = models.DecimalField(
        _('Taxa de Entrega (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    total = models.DecimalField(
        _('Total do Pedido (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )

    # Pagamento
    payment_method = models.CharField(
        _('Forma de Pagamento'),
        max_length=20,
        choices=PAYMENT_CHOICES,
        default=PAY_PIX
    )
    change_for = models.DecimalField(
        _('Troco para (R$)'),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_('Caso o cliente pague em dinheiro e necessite de troco.')
    )

    # Endereço de Entrega Congelado no Pedido
    street = models.CharField(_('Rua / Logradouro'), max_length=150, blank=True)
    number = models.CharField(_('Número'), max_length=20, blank=True)
    complement = models.CharField(_('Complemento'), max_length=100, blank=True)
    neighborhood = models.CharField(_('Bairro'), max_length=100, blank=True)
    city = models.CharField(_('Cidade'), max_length=100, blank=True)
    state = models.CharField(_('Estado (UF)'), max_length=2, blank=True)
    postal_code = models.CharField(_('CEP'), max_length=10, blank=True)
    reference = models.CharField(_('Ponto de Referência'), max_length=150, blank=True)

    notes = models.TextField(
        _('Observações Gerais do Pedido'),
        blank=True
    )

    # Marcos Temporais da Operação
    accepted_at = models.DateTimeField(_('Aceito em'), null=True, blank=True)
    preparing_at = models.DateTimeField(_('Em Preparação em'), null=True, blank=True)
    ready_at = models.DateTimeField(_('Pronto em'), null=True, blank=True)

    class Meta:
        verbose_name = _('Pedido')
        verbose_name_plural = _('Pedidos')
        ordering = ['-created_at']
        unique_together = ('store', 'order_number')

    def __str__(self):
        return f"{self.display_number} - {self.customer.name} (R$ {self.total:.2f}) [{self.store.name}]"

    @property
    def display_number(self) -> str:
        return f"#{self.order_number}"

    @property
    def formatted_delivery_address(self) -> str:
        if self.delivery_type == self.TYPE_PICKUP:
            return "Retirada no Balcão da Loja"
        parts = [f"{self.street}, {self.number}"]
        if self.complement:
            parts.append(f"({self.complement})")
        parts.append(f"- {self.neighborhood}, {self.city}/{self.state}")
        if self.reference:
            parts.append(f"[Ref: {self.reference}]")
        return " ".join(parts)

    @property
    def seconds_remaining_to_accept(self) -> int:
        """Tempo restante em segundos para o aceite (janela limite de 10 minutos)."""
        from django.utils import timezone
        if self.status != self.STATUS_NEW:
            return 0
        elapsed = (timezone.now() - self.created_at).total_seconds()
        remaining = int(10 * 60 - elapsed)
        return max(0, remaining)

    @property
    def preparation_seconds_remaining(self) -> int:
        """Tempo restante de preparo em segundos (baseado no tempo configurado na loja)."""
        from django.utils import timezone
        if not self.accepted_at or self.status not in [self.STATUS_ACCEPTED, self.STATUS_PREPARING]:
            return 0
        total_prep = (self.store.preparation_time_minutes or 30) * 60
        elapsed = (timezone.now() - self.accepted_at).total_seconds()
        return int(total_prep - elapsed)

    @property
    def is_preparation_delayed(self) -> bool:
        """Indica se o tempo de preparo estimado já foi ultrapassado."""
        if not self.accepted_at or self.status not in [self.STATUS_ACCEPTED, self.STATUS_PREPARING]:
            return False
        return self.preparation_seconds_remaining <= 0



class OrderItem(TimeStampedModel):
    """
    Item individual dentro de um pedido com precificação congelada.
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('Pedido')
    )
    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.PROTECT,
        related_name='order_items',
        verbose_name=_('Produto Original'),
        null=True,
        blank=True
    )
    product_name = models.CharField(_('Nome do Produto'), max_length=150)
    unit_price = models.DecimalField(_('Preço Unitário (R$)'), max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(_('Quantidade'), default=1)
    subtotal = models.DecimalField(_('Subtotal do Item (R$)'), max_digits=10, decimal_places=2)
    total = models.DecimalField(_('Total com Adicionais (R$)'), max_digits=10, decimal_places=2)
    notes = models.TextField(_('Observações do Item'), blank=True)

    class Meta:
        verbose_name = _('Item do Pedido')
        verbose_name_plural = _('Itens do Pedido')
        ordering = ['id']

    def __str__(self):
        return f"{self.quantity}x {self.product_name} ({self.order.display_number})"


class OrderItemOption(TimeStampedModel):
    """
    Opção ou adicional selecionado para um item de pedido.
    """
    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.CASCADE,
        related_name='selected_options',
        verbose_name=_('Item do Pedido')
    )
    option_item = models.ForeignKey(
        'catalog.OptionItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('Opção Original')
    )
    name = models.CharField(_('Nome da Opção'), max_length=100)
    price = models.DecimalField(_('Preço Adicional (R$)'), max_digits=10, decimal_places=2, default=Decimal('0.00'))
    group_name = models.CharField(_('Grupo de Opção'), max_length=100, blank=True)

    class Meta:
        verbose_name = _('Opção do Item de Pedido')
        verbose_name_plural = _('Opções dos Itens de Pedido')
        ordering = ['id']

    def __str__(self):
        return f"{self.name} (+ R$ {self.price:.2f})"
