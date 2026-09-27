import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from core.models import StoreBoundedModel, UUIDModel, TimeStampedModel


class Table(StoreBoundedModel):
    """
    Representação física de uma mesa no estabelecimento.
    Identificada por número único por loja e token seguro de QR Code.
    """
    number = models.CharField(
        _('Número da Mesa'),
        max_length=20,
        db_index=True,
        help_text=_('Ex: 01, 12, Varanda 3, Deck 02.')
    )
    name = models.CharField(
        _('Identificação / Nome Opcional'),
        max_length=100,
        blank=True,
        help_text=_('Ex: Salão Principal, Vista Mar, VIP.')
    )
    qr_token = models.UUIDField(
        _('Token Seguro do QR Code'),
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        help_text=_('Token criptográfico não sequencial para o QR Code da mesa.')
    )
    is_active = models.BooleanField(
        _('Ativa'),
        default=True,
        help_text=_('Se desativada, não aceita pedidos nem novas sessões.')
    )

    class Meta:
        verbose_name = _('Mesa')
        verbose_name_plural = _('Mesas')
        unique_together = ('store', 'number')
        ordering = ['number']

    def __str__(self):
        desc = f" - {self.name}" if self.name else ""
        return f"Mesa {self.number}{desc} [{self.store.name}]"

    @property
    def current_session(self):
        """Retorna a sessão de consumo aberta/ativa desta mesa, se houver."""
        return self.sessions.filter(
            status__in=[TableSession.STATUS_OPEN, TableSession.STATUS_WAITING_PAYMENT]
        ).first()

    @property
    def is_occupied(self) -> bool:
        """Indica se a mesa possui comanda/sessão aberta no momento."""
        return self.current_session is not None


class TableSession(StoreBoundedModel, UUIDModel):
    """
    Sessão / Comanda de consumo contínuo da Mesa.
    Agrupa múltiplas solicitações/pedidos feitos ao longo do tempo pelos clientes sentados na mesa.
    """
    STATUS_OPEN = 'OPEN'
    STATUS_WAITING_PAYMENT = 'WAITING_PAY'
    STATUS_CLOSED = 'CLOSED'
    STATUS_CANCELLED = 'CANCELLED'

    STATUS_CHOICES = [
        (STATUS_OPEN, _('Em Consumo (Aberta)')),
        (STATUS_WAITING_PAYMENT, _('Aguardando Pagamento (Pediu a Conta)')),
        (STATUS_CLOSED, _('Encerrada / Paga')),
        (STATUS_CANCELLED, _('Cancelada')),
    ]

    table = models.ForeignKey(
        Table,
        on_delete=models.PROTECT,
        related_name='sessions',
        verbose_name=_('Mesa')
    )
    session_token = models.UUIDField(
        _('Token de Validação da Sessão'),
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False
    )
    status = models.CharField(
        _('Status da Sessão'),
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
        db_index=True
    )
    opened_at = models.DateTimeField(
        _('Aberta em'),
        auto_now_add=True
    )
    closed_at = models.DateTimeField(
        _('Encerrada em'),
        null=True,
        blank=True
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_table_sessions',
        verbose_name=_('Operador Responsável pelo Fechamento')
    )
    payment_method = models.CharField(
        _('Forma de Pagamento'),
        max_length=20,
        blank=True
    )
    discount = models.DecimalField(
        _('Desconto (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    total_paid = models.DecimalField(
        _('Total Pago (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    notes = models.TextField(
        _('Observações da Mesa / Comanda'),
        blank=True
    )

    class Meta:
        verbose_name = _('Sessão de Mesa / Comanda')
        verbose_name_plural = _('Sessões de Mesas / Comandas')
        ordering = ['-opened_at']
        constraints = [
            models.UniqueConstraint(
                fields=['table'],
                condition=models.Q(status__in=['OPEN', 'WAITING_PAY']),
                name='unique_active_session_per_table'
            )
        ]

    def __str__(self):
        return f"Mesa {self.table.number} - Sessão #{str(self.public_id)[:8]} ({self.get_status_display()})"

    def get_valid_orders(self):
        """Retorna todos os pedidos não cancelados desta sessão ordenados cronologicamente."""
        return self.orders.exclude(status=Order.STATUS_CANCELLED).order_by('created_at')

    def calculate_subtotal(self) -> Decimal:
        """Calcula o subtotal somando os itens válidos de todas as rodadas."""
        orders = self.get_valid_orders()
        subtotal = Decimal('0.00')
        for ord in orders:
            subtotal += ord.subtotal
        return subtotal

    def calculate_total(self) -> Decimal:
        """Calcula o total final da mesa (subtotal - descontos)."""
        orders = self.get_valid_orders()
        total_orders = sum(ord.total for ord in orders) if orders else Decimal('0.00')
        return max(Decimal('0.00'), total_orders - self.discount)

    def get_items_breakdown(self) -> list:
        """
        Retorna a lista agregada de produtos e adicionais consumidos na sessão,
        agrupados por produto para conferência no fechamento da conta.
        """
        aggregated = {}
        for ord in self.get_valid_orders().prefetch_related('items__selected_options'):
            for item in ord.items.all():
                opts_key = tuple(sorted((opt.name, str(opt.price)) for opt in item.selected_options.all()))
                key = (item.product_id, item.product_name, item.unit_price, opts_key)
                if key not in aggregated:
                    aggregated[key] = {
                        'product_id': item.product_id,
                        'product_name': item.product_name,
                        'unit_price': item.unit_price,
                        'quantity': 0,
                        'total': Decimal('0.00'),
                        'options': [
                            {'name': opt.name, 'price': opt.price, 'group_name': opt.group_name}
                            for opt in item.selected_options.all()
                        ]
                    }
                aggregated[key]['quantity'] += item.quantity
                aggregated[key]['total'] += item.total

        return list(aggregated.values())


class Coupon(StoreBoundedModel):
    """
    Cupom de desconto promocional criado pelo lojista.
    """
    DISCOUNT_PERCENTAGE = 'PERCENTAGE'
    DISCOUNT_FIXED = 'FIXED'

    DISCOUNT_CHOICES = [
        (DISCOUNT_PERCENTAGE, _('Porcentagem (%)')),
        (DISCOUNT_FIXED, _('Valor Fixo (R$)')),
    ]

    code = models.CharField(
        _('Código do Cupom'),
        max_length=30,
        help_text=_('Código digitado pelo cliente ou operador (ex: BEMVINDO10).')
    )
    discount_type = models.CharField(
        _('Tipo de Desconto'),
        max_length=15,
        choices=DISCOUNT_CHOICES,
        default=DISCOUNT_PERCENTAGE
    )
    discount_value = models.DecimalField(
        _('Valor do Desconto'),
        max_digits=10,
        decimal_places=2,
        help_text=_('Percentual (ex: 10 para 10%) ou valor fixo em R$ (ex: 15.00).')
    )
    min_order_value = models.DecimalField(
        _('Valor Mínimo do Pedido (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Subtotal mínimo de mercadorias para liberar o cupom.')
    )
    apply_to_delivery = models.BooleanField(
        _('Desconto no Total Geral (inclui frete)'),
        default=False,
        help_text=_('Se marcado, o desconto pode incidir sobre o total com frete. Se desmarcado, incide apenas nas mercadorias.')
    )
    max_uses = models.PositiveIntegerField(
        _('Limite Máximo de Usos'),
        null=True,
        blank=True,
        help_text=_('Deixe em branco para usos ilimitados.')
    )
    times_used = models.PositiveIntegerField(
        _('Quantidade de Usos'),
        default=0
    )
    valid_from = models.DateTimeField(
        _('Válido a partir de'),
        null=True,
        blank=True
    )
    valid_until = models.DateTimeField(
        _('Válido até'),
        null=True,
        blank=True
    )
    is_public = models.BooleanField(
        _('Destacar no Cardápio / Checkout'),
        default=False,
        help_text=_('Se ativo, exibe o cupom publicamente incentivando o cliente a atingir o valor mínimo.')
    )
    is_active = models.BooleanField(
        _('Ativo'),
        default=True
    )

    class Meta:
        verbose_name = _('Cupom de Desconto')
        verbose_name_plural = _('Cupons de Desconto')
        unique_together = ('store', 'code')
        ordering = ['-created_at']

    def __str__(self):
        type_str = f"{self.discount_value}%" if self.discount_type == self.DISCOUNT_PERCENTAGE else f"R$ {self.discount_value:.2f}"
        return f"{self.code} ({type_str}) - {self.store.name}"

    def clean(self):
        super().clean()
        if self.code:
            self.code = self.code.strip().upper()
        if self.discount_value is not None:
            if self.discount_value <= Decimal('0.00'):
                raise ValidationError({'discount_value': _('O valor do desconto deve ser maior que zero.')})
            if self.discount_type == self.DISCOUNT_PERCENTAGE and self.discount_value > Decimal('100.00'):
                raise ValidationError({'discount_value': _('Desconto em porcentagem não pode ser maior que 100%.')})

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        self.full_clean()
        super().save(*args, **kwargs)

    def calculate_discount(self, subtotal: Decimal, delivery_fee: Decimal = Decimal('0.00')) -> Decimal:
        """Calcula o valor nominal do desconto em R$ para a cesta."""
        base_amount = (subtotal + delivery_fee) if self.apply_to_delivery else subtotal
        if self.discount_type == self.DISCOUNT_PERCENTAGE:
            discount = (base_amount * self.discount_value) / Decimal('100.00')
        else:
            discount = min(self.discount_value, base_amount)
        return min(discount, base_amount).quantize(Decimal('0.01'))

    def validate_for_order(self, subtotal: Decimal, delivery_fee: Decimal = Decimal('0.00')) -> tuple[bool, str]:
        """
        Valida se o cupom pode ser aplicado neste pedido.
        Retorna (is_valid, error_message).
        """
        from django.utils import timezone
        now = timezone.now()
        if not self.is_active:
            return False, "Este cupom está desativado."
        if self.valid_from and now < self.valid_from:
            return False, "Este cupom ainda não é válido."
        if self.valid_until and now > self.valid_until:
            return False, "Este cupom expirou."
        if self.max_uses is not None and self.times_used >= self.max_uses:
            return False, "Este cupom atingiu o limite máximo de utilizações."
        if subtotal < self.min_order_value:
            needed = self.min_order_value - subtotal
            return False, f"Valor mínimo não atingido. Adicione mais R$ {needed:.2f} em produtos para liberar este cupom."
        return True, ""


class Order(StoreBoundedModel, UUIDModel):
    """
    Entidade central de Pedido na plataforma IA-Pedidos.
    Armazena o cabeçalho, status, valores recalculados e dados cadastrais/endereço congelados.
    """
    # Origem do Pedido
    ORIGIN_ONLINE = 'ONLINE'
    ORIGIN_PDV = 'PDV'
    ORIGIN_TABLE = 'TABLE'
    ORIGIN_CHOICES = [
        (ORIGIN_ONLINE, _('Online (Cardápio)')),
        (ORIGIN_PDV, _('PDV (Balcão)')),
        (ORIGIN_TABLE, _('Mesa (QR Code)')),
    ]

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
        (STATUS_OUT_FOR_DELIVERY, _('Saiu para Entrega / Na Mesa')),
        (STATUS_COMPLETED, _('Concluído')),
        (STATUS_CANCELLED, _('Cancelado')),
    ]

    # Modalidade de Atendimento
    TYPE_DELIVERY = 'DELIVERY'
    TYPE_PICKUP = 'PICKUP'
    TYPE_DINE_IN = 'DINE_IN'

    TYPE_CHOICES = [
        (TYPE_DELIVERY, _('Entrega')),
        (TYPE_PICKUP, _('Retirada na Loja')),
        (TYPE_DINE_IN, _('Consumo no Local / Mesa')),
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

    origin = models.CharField(
        _('Origem do Pedido'),
        max_length=10,
        choices=ORIGIN_CHOICES,
        default=ORIGIN_ONLINE,
        db_index=True,
        help_text=_('Identifica se a venda foi originada pelo Cardápio Online, PDV ou Mesa QR.')
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pos_orders',
        verbose_name=_('Operador do PDV'),
        help_text=_('Usuário lojista responsável por registrar a venda no PDV.')
    )
    table = models.ForeignKey(
        Table,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name=_('Mesa Física'),
        help_text=_('Mesa vinculada caso a venda tenha sido originada por QR Code ou consumida no local.')
    )
    table_session = models.ForeignKey(
        TableSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name=_('Sessão da Mesa / Comanda'),
        help_text=_('Comanda agregada contínua de consumo da mesa.')
    )
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
    discount = models.DecimalField(
        _('Desconto (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Valor de desconto concedido por cupom ou promoção.')
    )
    total = models.DecimalField(
        _('Total do Pedido (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name=_('Cupom Aplicado')
    )
    coupon_code = models.CharField(
        _('Código do Cupom'),
        max_length=30,
        blank=True
    )
    stock_returned = models.BooleanField(
        _('Estoque Estornado'),
        default=False,
        help_text=_('Indica se o estoque já foi devolvido após cancelamento do pedido.')
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
        if self.delivery_type == self.TYPE_DINE_IN:
            if self.table:
                return f"Consumo na Mesa {self.table.number}"
            return "Consumo no Local (Mesa)"
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

    @property
    def customer_whatsapp_link(self) -> str:
        """Gera o link wa.me direto para o lojista falar com o cliente no WhatsApp."""
        if not hasattr(self, 'customer') or not self.customer or not self.customer.phone:
            return "#"
        try:
            from whatsapp.services import get_customer_whatsapp_link
            return get_customer_whatsapp_link(self)
        except Exception:
            import re
            clean = re.sub(r'\D', '', str(self.customer.phone or ''))
            if clean and not clean.startswith('55') and len(clean) in (10, 11):
                clean = f"55{clean}"
            return f"https://wa.me/{clean}" if clean else "#"




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
