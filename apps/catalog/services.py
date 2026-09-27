from django.db import transaction
from django.core.exceptions import ValidationError
from .models import Product, StockMovement


class StockService:
    """
    Camada de serviço centralizada e atômica para toda movimentação de estoque
    no sistema (Pedido Online, PDV Balcão, Devoluções por Cancelamento e Ajustes Manuais).
    """

    @classmethod
    @transaction.atomic
    def decrement_stock(
        cls,
        product: Product,
        quantity: int,
        order,
        user=None,
        origin: str = 'ONLINE'
    ) -> Product:
        """
        Valida e debita o estoque do produto com bloqueio pessimista (select_for_update)
        para garantir integridade absoluta em concorrência.
        """
        if quantity <= 0:
            raise ValidationError("A quantidade a ser debitada deve ser maior que zero.")

        # Bloqueia a linha do produto no banco durante a transação
        locked_product = Product.objects.select_for_update().get(id=product.id)

        if locked_product.track_stock:
            if locked_product.stock_quantity < quantity:
                raise ValidationError(
                    f"Estoque insuficiente para '{locked_product.name}'. "
                    f"Disponível: {locked_product.stock_quantity}, Solicitado: {quantity}."
                )

            previous_stock = locked_product.stock_quantity
            locked_product.stock_quantity -= quantity
            locked_product.save(update_fields=['stock_quantity'])

            movement_type = (
                StockMovement.TYPE_SALE_PDV
                if origin == 'PDV'
                else StockMovement.TYPE_SALE_ONLINE
            )

            StockMovement.objects.create(
                store=locked_product.store,
                product=locked_product,
                order=order,
                operator=user,
                movement_type=movement_type,
                quantity=-quantity,
                previous_stock=previous_stock,
                current_stock=locked_product.stock_quantity,
                notes=f"Venda {origin} #{order.order_number}"
            )

        return locked_product

    @classmethod
    @transaction.atomic
    def restore_stock(cls, order, user=None) -> bool:
        """
        Estorna e devolve os itens do pedido ao estoque centralizado caso o pedido
        seja cancelado. Protegido contra devolução duplicada (idempotente).
        """
        if order.stock_returned:
            return False

        for item in order.items.select_related('product').all():
            if item.product:
                locked_product = Product.objects.select_for_update().get(id=item.product.id)
                if locked_product.track_stock:
                    previous_stock = locked_product.stock_quantity
                    locked_product.stock_quantity += item.quantity
                    locked_product.save(update_fields=['stock_quantity'])

                    StockMovement.objects.create(
                        store=order.store,
                        product=locked_product,
                        order=order,
                        operator=user,
                        movement_type=StockMovement.TYPE_CANCEL_RETURN,
                        quantity=+item.quantity,
                        previous_stock=previous_stock,
                        current_stock=locked_product.stock_quantity,
                        notes=f"Devolução por cancelamento do Pedido #{order.order_number}"
                    )

        order.stock_returned = True
        order.save(update_fields=['stock_returned'])
        return True

    @classmethod
    @transaction.atomic
    def adjust_stock(
        cls,
        product: Product,
        new_quantity: int,
        user=None,
        reason: str = ''
    ) -> Product:
        """
        Realiza ajuste manual de estoque com auditoria completa.
        """
        locked_product = Product.objects.select_for_update().get(id=product.id)
        previous_stock = locked_product.stock_quantity
        diff = new_quantity - previous_stock

        locked_product.stock_quantity = new_quantity
        locked_product.save(update_fields=['stock_quantity'])

        movement_type = StockMovement.TYPE_RESTOCK if diff > 0 else StockMovement.TYPE_MANUAL_ADJUST

        StockMovement.objects.create(
            store=locked_product.store,
            product=locked_product,
            operator=user,
            movement_type=movement_type,
            quantity=diff,
            previous_stock=previous_stock,
            current_stock=new_quantity,
            notes=reason or f"Ajuste manual de saldo ({diff:+d})"
        )

        return locked_product
