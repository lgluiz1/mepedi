from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.models import StoreBoundedModel, TimeStampedModel


class Category(StoreBoundedModel):
    """
    Categoria de produtos pertencente a uma loja específica.
    Exemplos: Hambúrgueres, Bebidas, Sobremesas, Combos.
    """
    name = models.CharField(
        _('Nome da Categoria'),
        max_length=100
    )
    description = models.TextField(
        _('Descrição'),
        blank=True,
        help_text=_('Breve descrição da categoria exibida no cardápio.')
    )
    order = models.PositiveIntegerField(
        _('Ordem de Exibição'),
        default=0,
        help_text=_('Menor número aparece primeiro no cardápio.')
    )
    is_active = models.BooleanField(
        _('Ativa'),
        default=True,
        help_text=_('Categorias inativas não aparecem no cardápio público.')
    )

    class Meta:
        verbose_name = _('Categoria')
        verbose_name_plural = _('Categorias')
        ordering = ['order', 'name']
        unique_together = ('store', 'name')

    def __str__(self):
        return f"{self.name} ({self.store.name})"

    def save(self, *args, **kwargs):
        from .category_catalog import format_category_name_with_icon
        if self.name:
            self.name = format_category_name_with_icon(self.name)
        super().save(*args, **kwargs)


class Product(StoreBoundedModel):
    """
    Produto comercializado no cardápio da loja.
    """
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products',
        verbose_name=_('Categoria')
    )
    name = models.CharField(
        _('Nome do Produto'),
        max_length=150
    )
    description = models.TextField(
        _('Descrição'),
        blank=True,
        help_text=_('Ingredientes, tamanho e detalhes do produto.')
    )
    price = models.DecimalField(
        _('Preço Base (R$)'),
        max_digits=10,
        decimal_places=2,
        help_text=_('Valor de venda base do produto.')
    )
    image = models.ImageField(
        _('Foto do Produto'),
        upload_to='products/images/',
        blank=True,
        null=True
    )
    code = models.CharField(
        _('Código PDV'),
        max_length=30,
        blank=True,
        null=True,
        help_text=_('Identificador amigável e único por loja para busca rápida no PDV (ex: FAT001).')
    )
    track_stock = models.BooleanField(
        _('Controlar Estoque'),
        default=False,
        help_text=_('Se ativado, as vendas online e no PDV debitam o saldo deste produto.')
    )
    stock_quantity = models.IntegerField(
        _('Quantidade em Estoque'),
        default=0,
        help_text=_('Saldo físico disponível para venda.')
    )
    is_promotional = models.BooleanField(
        _('Em Promoção'),
        default=False,
        help_text=_('Ativa o preço promocional de venda deste produto.')
    )
    promotional_price = models.DecimalField(
        _('Preço Promocional (R$)'),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_('Valor com desconto para venda online e PDV.')
    )
    is_active = models.BooleanField(
        _('Disponível / Ativo'),
        default=True,
        help_text=_('Se desmarcado, fica marcado como esgotado/indisponível.')
    )
    order = models.PositiveIntegerField(
        _('Ordem de Exibição'),
        default=0
    )

    class Meta:
        verbose_name = _('Produto')
        verbose_name_plural = _('Produtos')
        ordering = ['order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['store', 'code'],
                condition=models.Q(code__isnull=False) & ~models.Q(code=''),
                name='unique_store_product_code'
            )
        ]

    def __str__(self):
        return f"{self.name} - R$ {self.price:.2f} ({self.store.name})"

    @property
    def current_price(self) -> Decimal:
        """Retorna o preço promocional caso a promoção esteja ativa e válida, senão o preço base."""
        if self.is_promotional and self.promotional_price is not None:
            if Decimal('0.00') < self.promotional_price < self.price:
                return self.promotional_price
        return self.price

    @property
    def discount_percent(self) -> int:
        """Calcula o percentual de desconto com base no preço base e no preço promocional."""
        if self.is_promotional and self.promotional_price is not None:
            if Decimal('0.00') < self.promotional_price < self.price:
                diff = self.price - self.promotional_price
                percent = (diff / self.price) * Decimal('100.0')
                return int(round(percent))
        return 0

    @property
    def is_in_stock(self) -> bool:
        """Indica se o produto possui estoque disponível para compra."""
        if not self.track_stock:
            return True
        return self.stock_quantity > 0

    def clean(self):
        super().clean()
        if self.code:
            self.code = self.code.strip().upper()
        if self.category_id and self.store_id:
            if self.category.store_id != self.store_id:
                raise ValidationError({
                    'category': _('A categoria selecionada não pertence a esta loja.')
                })
        if self.is_promotional and self.promotional_price is not None:
            if self.promotional_price <= Decimal('0.00'):
                raise ValidationError({
                    'promotional_price': _('O preço promocional deve ser maior que zero.')
                })
            if self.promotional_price >= self.price:
                raise ValidationError({
                    'promotional_price': _('O preço promocional deve ser menor que o preço base do produto.')
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class StockMovement(StoreBoundedModel):
    """
    Registro detalhado de auditoria de todas as entradas, saídas e ajustes de estoque.
    """
    TYPE_SALE_ONLINE = 'SALE_ONLINE'
    TYPE_SALE_PDV = 'SALE_PDV'
    TYPE_CANCEL_RETURN = 'CANCEL_RETURN'
    TYPE_MANUAL_ADJUST = 'MANUAL_ADJUST'
    TYPE_RESTOCK = 'RESTOCK'

    MOVEMENT_CHOICES = [
        (TYPE_SALE_ONLINE, _('Venda Online')),
        (TYPE_SALE_PDV, _('Venda PDV (Balcão)')),
        (TYPE_CANCEL_RETURN, _('Devolução por Cancelamento')),
        (TYPE_MANUAL_ADJUST, _('Ajuste Manual')),
        (TYPE_RESTOCK, _('Reposição de Estoque')),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='stock_movements',
        verbose_name=_('Produto')
    )
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_movements',
        verbose_name=_('Pedido Vinculado')
    )
    operator = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_movements',
        verbose_name=_('Operador / Responsável')
    )
    movement_type = models.CharField(
        _('Tipo de Movimentação'),
        max_length=20,
        choices=MOVEMENT_CHOICES
    )
    quantity = models.IntegerField(
        _('Quantidade Movimentada'),
        help_text=_('Valor negativo para saídas/vendas e positivo para entradas/estornos.')
    )
    previous_stock = models.IntegerField(
        _('Saldo Anterior')
    )
    current_stock = models.IntegerField(
        _('Saldo Atual')
    )
    notes = models.CharField(
        _('Observações / Motivo'),
        max_length=255,
        blank=True
    )

    class Meta:
        verbose_name = _('Movimentação de Estoque')
        verbose_name_plural = _('Movimentações de Estoque')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.product.name} ({self.quantity:+d}) - {self.get_movement_type_display()} [{self.store.name}]"



class OptionGroup(StoreBoundedModel):
    """
    Grupo de opções vinculadas a um produto.
    Exemplos:
    - 'ADICIONAIS' (Bacon +R$5, Queijo +R$3, Ovo +R$2)
    - 'REMOVER INGREDIENTES' (Sem cebola, Sem tomate)
    - 'PONTO DA CARNE' (Ao ponto, Bem passado)
    """
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        verbose_name=_('Loja'),
        db_index=True,
        blank=True
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='option_groups',
        verbose_name=_('Produto')
    )
    name = models.CharField(
        _('Nome do Grupo'),
        max_length=100,
        help_text=_('Ex: Adicionais, Remover Ingredientes, Escolha o Molho')
    )
    description = models.CharField(
        _('Instrução / Descrição'),
        max_length=200,
        blank=True,
        help_text=_('Ex: Escolha até 3 adicionais')
    )
    min_options = models.PositiveIntegerField(
        _('Mínimo Obrigatório'),
        default=0,
        help_text=_('Quantidade mínima de itens que o cliente deve escolher. 0 = Opcional.')
    )
    max_options = models.PositiveIntegerField(
        _('Máximo Permitido'),
        default=1,
        help_text=_('Quantidade máxima de itens que o cliente pode escolher.')
    )
    is_required = models.BooleanField(
        _('Seleção Obrigatória'),
        default=False,
        help_text=_('Se marcado, o cliente deve escolher ao menos 1 item.')
    )
    order = models.PositiveIntegerField(
        _('Ordem'),
        default=0
    )

    class Meta:
        verbose_name = _('Grupo de Opções')
        verbose_name_plural = _('Grupos de Opções')
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.product.name} - {self.name}"

    def clean(self):
        super().clean()
        if self.product_id:
            self.store_id = self.product.store_id
        if self.min_options > self.max_options:
            raise ValidationError({
                'min_options': _('A quantidade mínima não pode ser maior que o máximo permitido.')
            })
        if self.is_required and self.min_options == 0:
            self.min_options = 1

    def save(self, *args, **kwargs):
        if not self.store_id and self.product_id:
            self.store_id = self.product.store_id
        self.full_clean()
        super().save(*args, **kwargs)


class OptionItem(TimeStampedModel):
    """
    Item individual dentro de um grupo de opções.
    Pode ser um adicional com custo extra ou uma remoção/variação com custo zero (R$ 0,00).
    """
    option_group = models.ForeignKey(
        OptionGroup,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('Grupo de Opções')
    )
    name = models.CharField(
        _('Nome da Opção'),
        max_length=100,
        help_text=_('Ex: Bacon, Queijo Extra, Sem Cebola, Ao Ponto')
    )
    price = models.DecimalField(
        _('Preço Adicional (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Valor adicional cobrado. Utilize 0,00 para opções gratuitas ou remoções.')
    )
    is_available = models.BooleanField(
        _('Disponível'),
        default=True,
        help_text=_('Item disponível no momento.')
    )
    order = models.PositiveIntegerField(
        _('Ordem'),
        default=0
    )

    class Meta:
        verbose_name = _('Item de Opção')
        verbose_name_plural = _('Itens de Opção')
        ordering = ['order', 'name']

    def __str__(self):
        if self.price > 0:
            return f"{self.name} (+ R$ {self.price:.2f})"
        return self.name
