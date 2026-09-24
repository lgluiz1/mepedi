import re
import urllib.parse
from decimal import Decimal


def clean_phone_number(phone: str, default_country_code: str = '55') -> str:
    """
    Remove caracteres não numéricos de um número de telefone e garante
    que o código do país (default '55' para o Brasil) esteja presente.
    Exemplos:
      "(11) 98765-4321" -> "5511987654321"
      "+55 (21) 99999-0000" -> "5521999990000"
      "5511987654321" -> "5511987654321"
    """
    if not phone:
        return ""
    digits = re.sub(r'\D', '', str(phone))
    if not digits:
        return ""
    
    # Se já começar com o código do país (ex: 55 com 12 ou 13 dígitos)
    if digits.startswith(default_country_code) and len(digits) in (12, 13):
        return digits
    
    # Se tiver 10 ou 11 dígitos (DDD + número brasileiro)
    if len(digits) in (10, 11):
        return f"{default_country_code}{digits}"
    
    return digits


def format_order_whatsapp_message(order, public_url: str = None) -> str:
    """
    Gera o texto estruturado e amigável para envio de pedidos via WhatsApp.
    Contém todos os dados do pedido, itens, adicionais, modalidade, pagamento e link.
    """
    lines = []
    
    # Cabeçalho
    lines.append(f"🍕 *NOVO PEDIDO #{order.order_number}*")
    lines.append(f"🏪 *Loja:* {order.store.name}")
    lines.append("───────────────────────")
    
    # Dados do Cliente
    lines.append(f"👤 *Cliente:* {order.customer.name}")
    lines.append(f"📱 *Telefone:* {order.customer.phone}")
    lines.append(f"🛵 *Modalidade:* {order.get_delivery_type_display()}")
    
    if order.delivery_type == 'DELIVERY':
        lines.append(f"📍 *Endereço:* {order.formatted_delivery_address}")
        if order.reference:
            lines.append(f"📌 *Ponto de Ref.:* {order.reference}")
    
    lines.append("───────────────────────")
    lines.append("📋 *ITENS DO PEDIDO:*")
    
    # Itens do Pedido
    for item in order.items.all():
        lines.append(f"▫️ *{item.quantity}x {item.product_name}* - R$ {item.total:.2f}")
        
        # Opções/Adicionais
        for opt in item.selected_options.all():
            if opt.price > Decimal('0.00'):
                lines.append(f"   ➕ {opt.name} (+R$ {opt.price:.2f})")
            else:
                lines.append(f"   ➖ {opt.name}")
        
        # Observação do item
        if item.notes:
            lines.append(f"   ✍️ _Obs: {item.notes}_")
    
    lines.append("───────────────────────")
    lines.append(f"💵 *Subtotal:* R$ {order.subtotal:.2f}")
    
    if order.delivery_type == 'DELIVERY':
        lines.append(f"🛵 *Taxa de Entrega:* R$ {order.delivery_fee:.2f}")
    
    lines.append(f"💰 *TOTAL DO PEDIDO:* R$ {order.total:.2f}")
    lines.append("───────────────────────")
    
    # Forma de Pagamento
    lines.append(f"💳 *Forma de Pagamento:* {order.get_payment_method_display()}")
    if order.payment_method in ('MONEY', 'CASH') and order.change_for:
        change_amount = order.change_for - order.total
        if change_amount > Decimal('0.00'):
            lines.append(f"🪙 *Troco para:* R$ {order.change_for:.2f} (Troco: R$ {change_amount:.2f})")
        else:
            lines.append(f"🪙 *Troco para:* R$ {order.change_for:.2f} (Não precisa de troco)")
    
    if order.notes:
        lines.append(f"📝 *Observações Gerais:* {order.notes}")
    
    # Link de acompanhamento
    if public_url:
        lines.append("───────────────────────")
        lines.append("🔗 *Acompanhe seu pedido em tempo real:*")
        lines.append(public_url)
    
    return "\n".join(lines)


def build_whatsapp_link(phone: str, message: str) -> str:
    """
    Gera o link oficial do WhatsApp no formato wa.me com a mensagem codificada em URL.
    """
    clean_phone = clean_phone_number(phone)
    encoded_message = urllib.parse.quote(message)
    return f"https://wa.me/{clean_phone}?text={encoded_message}"


def get_store_order_whatsapp_link(order, request=None) -> str:
    """
    Gera o link para o cliente enviar a mensagem do pedido diretamente para o WhatsApp da loja.
    """
    if request:
        public_url = request.build_absolute_uri(f"/{order.store.slug}/pedidos/{order.public_id}/")
    else:
        public_url = f"/{order.store.slug}/pedidos/{order.public_id}/"
    
    message = format_order_whatsapp_message(order, public_url=public_url)
    store_phone = order.store.whatsapp or order.store.phone
    return build_whatsapp_link(store_phone, message)


def get_customer_whatsapp_link(order, custom_message: str = None) -> str:
    """
    Gera o link para o lojista iniciar conversa com o cliente sobre o pedido.
    """
    if not custom_message:
        custom_message = (
            f"Olá {order.customer.name}! Aqui é da {order.store.name}. "
            f"Estamos entrando em contato sobre o seu pedido #{order.order_number}."
        )
    return build_whatsapp_link(order.customer.phone, custom_message)
