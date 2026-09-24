from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient
from rest_framework import status

from stores.models import Store
from accounts.models import StoreMembership
from customers.models import Customer, CustomerAddress, clean_phone_number

User = get_user_model()


class CustomerModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='dono@teste.com',
            password='Password123!',
            full_name='Dono'
        )
        self.store_a = Store.objects.create(
            owner=self.user,
            name="Loja A",
            whatsapp="11911111111"
        )
        self.store_b = Store.objects.create(
            owner=self.user,
            name="Loja B",
            whatsapp="11922222222"
        )

    def test_phone_number_cleaning(self):
        """Testa normalização do telefone (remove pontuação e espaços)."""
        self.assertEqual(clean_phone_number('(11) 98888-7777'), '11988887777')
        self.assertEqual(clean_phone_number('+55 11 99999 8888'), '5511999998888')

    def test_customer_creation_and_uniqueness_per_store(self):
        """
        Garante que o telefone é único por loja, mas pode existir o mesmo telefone
        em lojas diferentes da plataforma SaaS.
        """
        c1 = Customer.objects.create(
            store=self.store_a,
            name="Luiz Silva",
            phone="(11) 98765-4321"
        )
        self.assertEqual(c1.phone, "11987654321")

        # Tentativa de duplicar o mesmo telefone na MESMA loja deve falhar
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Customer.objects.create(
                    store=self.store_a,
                    name="Luiz Outro Nome",
                    phone="11987654321"
                )

        # O mesmo telefone em OUTRA loja deve ser permitido (isolamento de lojistas)
        c2 = Customer.objects.create(
            store=self.store_b,
            name="Luiz Silva",
            phone="11987654321"
        )
        self.assertEqual(c2.store, self.store_b)

    def test_customer_address_creation(self):
        """Testa associação de endereços ao cliente."""
        customer = Customer.objects.create(
            store=self.store_a,
            name="Mariana Santos",
            phone="11977776666"
        )
        address = CustomerAddress.objects.create(
            customer=customer,
            street="Av. Paulista",
            number="1000",
            complement="Apto 42",
            neighborhood="Bela Vista",
            city="São Paulo",
            state="SP",
            postal_code="01310-100",
            is_default=True
        )
        self.assertEqual(customer.addresses.count(), 1)
        self.assertIn("Av. Paulista, 1000 (Apto 42)", address.formatted_address)


class CustomerCheckoutIdentifyAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email='dono@delivery.com',
            password='Password123!',
            full_name='Dono Delivery'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name="Pizzaria da Nonna",
            whatsapp="11988880000",
            is_active=True
        )

    def test_identify_new_customer_creates_successfully(self):
        """
        Quando um cliente compra pela primeira vez na loja, ele é criado automaticamente
        pelo endpoint de identificação no checkout.
        """
        payload = {
            "name": "Carlos Eduardo",
            "phone": "(11) 97777-8888",
            "document": "123.456.789-00",
            "email": "carlos@email.com"
        }
        response = self.client.post(
            f'/api/v1/customers/public/{self.store.slug}/identify/',
            payload,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['created'])
        self.assertEqual(response.data['customer']['phone'], "11977778888")
        self.assertEqual(response.data['customer']['name'], "Carlos Eduardo")

    def test_identify_existing_customer_returns_data_and_addresses(self):
        """
        Quando o cliente já comprou na loja anteriormente, seus dados e endereços salvos
        são recuperados para confirmação no checkout.
        """
        customer = Customer.objects.create(
            store=self.store,
            name="Fernanda Lima",
            phone="11966665555"
        )
        CustomerAddress.objects.create(
            customer=customer,
            street="Rua Augusta",
            number="500",
            neighborhood="Consolação",
            city="São Paulo",
            state="SP",
            is_default=True
        )

        payload = {
            "name": "Fernanda Lima",
            "phone": "11966665555"
        }
        response = self.client.post(
            f'/api/v1/customers/public/{self.store.slug}/identify/',
            payload,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['created'])
        self.assertEqual(len(response.data['customer']['addresses']), 1)
        self.assertEqual(response.data['customer']['addresses'][0]['street'], "Rua Augusta")


class CustomerMultiTenancyAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.user_a = User.objects.create_user(
            email='lojista_a@loja.com',
            password='Password123!',
            full_name='Lojista A'
        )
        self.store_a = Store.objects.create(owner=self.user_a, name="Loja A", whatsapp="11911110001")
        StoreMembership.objects.create(user=self.user_a, store=self.store_a, role=StoreMembership.ROLE_OWNER)

        self.user_b = User.objects.create_user(
            email='lojista_b@loja.com',
            password='Password123!',
            full_name='Lojista B'
        )
        self.store_b = Store.objects.create(owner=self.user_b, name="Loja B", whatsapp="11922220002")
        StoreMembership.objects.create(user=self.user_b, store=self.store_b, role=StoreMembership.ROLE_OWNER)

        # Clientes
        self.cust_a = Customer.objects.create(store=self.store_a, name="Cliente A", phone="11911112222")
        self.cust_b = Customer.objects.create(store=self.store_b, name="Cliente B", phone="11922223333")

    def test_merchant_cannot_list_or_access_customers_from_another_store(self):
        """
        Lojista A autenticado NÃO consegue listar clientes da Loja B (retorna 403 Forbidden).
        """
        self.client.force_authenticate(user=self.user_a)

        resp = self.client.get(f'/api/v1/customers/merchant/{self.store_b.id}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        detail_resp = self.client.get(f'/api/v1/customers/merchant/{self.store_b.id}/{self.cust_b.id}/')
        self.assertEqual(detail_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_merchant_can_list_own_customers_and_search_by_phone(self):
        """
        Lojista A autenticado lista apenas seus clientes e consegue buscar por telefone.
        """
        self.client.force_authenticate(user=self.user_a)

        resp = self.client.get(f'/api/v1/customers/merchant/{self.store_a.id}/?search=11911112222')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['phone'], "11911112222")
