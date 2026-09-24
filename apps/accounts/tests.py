from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from stores.models import Store
from accounts.models import StoreMembership

User = get_user_model()


class UserModelTest(TestCase):
    def test_create_user_with_email_successful(self):
        """Testa criação de usuário normal com e-mail único."""
        user = User.objects.create_user(
            email='lojista@example.com',
            password='Password123!',
            full_name='Luiz Silva'
        )
        self.assertEqual(user.email, 'lojista@example.com')
        self.assertEqual(user.full_name, 'Luiz Silva')
        self.assertTrue(user.check_password('Password123!'))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)

    def test_create_superuser(self):
        """Testa criação de superusuário."""
        admin = User.objects.create_superuser(
            email='admin@example.com',
            password='AdminPassword123!',
            full_name='Administrador'
        )
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_email_must_be_unique(self):
        """Testa que não é permitido criar dois usuários com o mesmo e-mail."""
        User.objects.create_user(
            email='duplicado@example.com',
            password='Password123!',
            full_name='User 1'
        )
        with self.assertRaises(Exception):
            User.objects.create_user(
                email='duplicado@example.com',
                password='Password456!',
                full_name='User 2'
            )


class MerchantRegistrationAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_merchant_and_store_success(self):
        """
        Testa o fluxo completo de cadastro do lojista:
        Cria o User, a Store e o StoreMembership (ROLE_OWNER) atomicamente.
        """
        payload = {
            "email": "luiz@lanches.com",
            "password": "SenhaSegura123!",
            "full_name": "Luiz Santos",
            "phone": "11988887777",
            "store_name": "Lanchonete do Luiz",
            "whatsapp": "11999998888",
            "street": "Rua das Flores",
            "number": "100",
            "city": "São Paulo",
            "state": "SP",
            "postal_code": "01001-000"
        }
        response = self.client.post('/api/v1/accounts/register/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['user']['email'], "luiz@lanches.com")
        self.assertEqual(response.data['store']['name'], "Lanchonete do Luiz")
        self.assertEqual(response.data['store']['slug'], "lanchonete-do-luiz")

        # Verifica no banco de dados
        user = User.objects.get(email="luiz@lanches.com")
        store = Store.objects.get(slug="lanchonete-do-luiz")
        self.assertEqual(store.owner, user)

        membership = StoreMembership.objects.get(user=user, store=store)
        self.assertEqual(membership.role, StoreMembership.ROLE_OWNER)
        self.assertTrue(membership.is_active)

    def test_login_successful(self):
        """Testa login com email e senha."""
        user = User.objects.create_user(
            email='login@teste.com',
            password='SenhaValida123!',
            full_name='Usuario Teste'
        )
        response = self.client.post('/api/v1/accounts/login/', {
            'email': 'login@teste.com',
            'password': 'SenhaValida123!'
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('user', response.data)
