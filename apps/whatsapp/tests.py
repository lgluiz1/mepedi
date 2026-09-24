import urllib.parse
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, StoreMembership
from stores.models import Store
from catalog.models import Category, Product, OptionGroup, OptionItem
from customers.models import Customer
from orders.models import Order, OrderItem, OrderItemOption
from whatsapp.services import (
    clean_phone_number,
    format_order_whatsapp_message,
    build_whatsapp_link,
    get_store_order_whatsapp_link,
    get_customer_whatsapp_link,
)


class WhatsAppIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(
            email='lojista@pizzaria.com',
            password='secretpassword123',
            full_name='Dono Pizzaria'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name='Pizzaria Bella',
            slug='pizzaria-bella',
            whatsapp='(11) 97777-6666',
            phone='(11) 3333-2222',
            is_active=True,
            is_open=True
        )
        StoreMembership.objects.create(
            user=self.owner,
            store=self.store,
            role='owner',
            is_active=True
        )

        self.customer = Customer.objects.create(
            store=self.store,
            name='Maria Oliveira',
            phone='11988887777'
        )

        self.order = Order.objects.create(
            store=self.store,
            customer=self.customer,
            order_number=1001,
            delivery_type=Order.TYPE_DELIVERY,
            status=Order.STATUS_NEW,
            street='Rua das Flores',
            number='123',
            neighborhood='Centro',
            city='São Paulo',
            state='SP',
            reference='Próximo à praça',
            payment_method=Order.PAY_MONEY,
            change_for=Decimal('100.00'),
            delivery_fee=Decimal('5.00'),
            subtotal=Decimal('62.00'),
            total=Decimal('67.00'),
            notes='Tocar o interfone'
        )

        self.item = OrderItem.objects.create(
            order=self.order,
            product_name='Pizza Calabresa',
            unit_price=Decimal('50.00'),
            quantity=1,
            subtotal=Decimal('50.00'),
            total=Decimal('62.00'),
            notes='Bem passada'
        )

        OrderItemOption.objects.create(
            order_item=self.item,
            name='Borda Recheada Catupiry',
            price=Decimal('12.00'),
            group_name='Bordas'
        )
        OrderItemOption.objects.create(
            order_item=self.item,
            name='Sem Cebola',
            price=Decimal('0.00'),
            group_name='Remoções'
        )

    def test_clean_phone_number(self):
        """Valida a sanitização e adição do DDI 55."""
        self.assertEqual(clean_phone_number('(11) 98765-4321'), '5511987654321')
        self.assertEqual(clean_phone_number('11987654321'), '5511987654321')
        self.assertEqual(clean_phone_number('+55 (21) 99999-0000'), '5521999990000')
        self.assertEqual(clean_phone_number('5511977776666'), '5511977776666')
        self.assertEqual(clean_phone_number(''), '')

    def test_format_order_whatsapp_message(self):
        """Valida a estrutura completa da mensagem para WhatsApp."""
        msg = format_order_whatsapp_message(self.order, public_url='http://testserver/pizzaria-bella/pedidos/uuid/')
        
        # Cabeçalho e dados
        self.assertIn('*NOVO PEDIDO #1001*', msg)
        self.assertIn('Pizzaria Bella', msg)
        self.assertIn('Maria Oliveira', msg)
        self.assertIn('11988887777', msg)
        self.assertIn('Rua das Flores, 123', msg)
        self.assertIn('Próximo à praça', msg)

        # Itens e opções
        self.assertIn('Pizza Calabresa', msg)
        self.assertIn('Borda Recheada Catupiry (+R$ 12.00)', msg)
        self.assertIn('Sem Cebola', msg)
        self.assertIn('Bem passada', msg)

        # Totais e Pagamento
        self.assertIn('R$ 67.00', msg)
        self.assertIn('Dinheiro', msg)
        self.assertIn('*Troco para:* R$ 100.00', msg)
        self.assertIn('Tocar o interfone', msg)
        self.assertIn('http://testserver/pizzaria-bella/pedidos/uuid/', msg)

    def test_build_whatsapp_link(self):
        """Valida que o link wa.me é gerado com formatação e urlencode adequados."""
        link = build_whatsapp_link('(11) 97777-6666', 'Olá Mundo!')
        self.assertTrue(link.startswith('https://wa.me/5511977776666?text='))
        self.assertIn('Ol%C3%A1%20Mundo%21', link)

    def test_order_whatsapp_redirect_view(self):
        """Testa o endpoint de redirecionamento 302 para o WhatsApp da loja."""
        url = reverse('order_whatsapp_redirect', kwargs={
            'store_slug': self.store.slug,
            'public_id': self.order.public_id
        })
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('https://wa.me/5511977776666?text='))

    def test_whatsapp_link_api_view(self):
        """Testa a API REST para obtenção da mensagem e links dinâmicos."""
        url = reverse('whatsapp:order-link', kwargs={'public_id': self.order.public_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['order_number'], 1001)
        self.assertTrue(data['store_whatsapp_link'].startswith('https://wa.me/5511977776666'))
        self.assertTrue(data['customer_whatsapp_link'].startswith('https://wa.me/5511988887777'))
        self.assertIn('Pizza Calabresa', data['formatted_message'])
