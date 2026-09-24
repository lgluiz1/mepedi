from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from stores.models import Store
from accounts.models import StoreMembership

User = get_user_model()


class StoreModelTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='dono@teste.com',
            password='Password123!',
            full_name='Dono Teste'
        )

    def test_store_auto_slug_generation(self):
        """Testa geração automática de slug limpo a partir do nome."""
        store = Store.objects.create(
            owner=self.owner,
            name="Hamburgueria Artesanal & Grill",
            whatsapp="11999990000"
        )
        self.assertEqual(store.slug, "hamburgueria-artesanal-grill")

    def test_store_slug_collision_resolution(self):
        """Testa que duas lojas com o mesmo nome recebem slugs únicos distintos."""
        store1 = Store.objects.create(
            owner=self.owner,
            name="Pizzaria Bella",
            whatsapp="11999990001"
        )
        store2 = Store.objects.create(
            owner=self.owner,
            name="Pizzaria Bella",
            whatsapp="11999990002"
        )
        self.assertEqual(store1.slug, "pizzaria-bella")
        self.assertEqual(store2.slug, "pizzaria-bella-2")


class StoreMultiTenancyIsolationTest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Cria Lojista A e sua Loja A
        self.user_a = User.objects.create_user(
            email='lojista_a@email.com',
            password='Password123!',
            full_name='Lojista A'
        )
        self.store_a = Store.objects.create(
            owner=self.user_a,
            name="Restaurante Alfa",
            whatsapp="11900000001"
        )
        StoreMembership.objects.create(
            user=self.user_a,
            store=self.store_a,
            role=StoreMembership.ROLE_OWNER
        )

        # Cria Lojista B e sua Loja B
        self.user_b = User.objects.create_user(
            email='lojista_b@email.com',
            password='Password123!',
            full_name='Lojista B'
        )
        self.store_b = Store.objects.create(
            owner=self.user_b,
            name="Restaurante Beta",
            whatsapp="11900000002"
        )
        StoreMembership.objects.create(
            user=self.user_b,
            store=self.store_b,
            role=StoreMembership.ROLE_OWNER
        )

    def test_merchant_cannot_list_another_store(self):
        """
        O Lojista A autenticado NÃO pode ver a Loja B na listagem de suas lojas.
        """
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get('/api/v1/stores/merchant/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        store_ids = [item['id'] for item in response.data['results'] if 'results' in response.data] or [item['id'] for item in response.data]
        self.assertIn(self.store_a.id, store_ids)
        self.assertNotIn(self.store_b.id, store_ids)

    def test_merchant_cannot_access_or_edit_another_store_detail(self):
        """
        O Lojista A autenticado NÃO consegue acessar ou editar os detalhes da Loja B (retorna 404).
        """
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(f'/api/v1/stores/merchant/{self.store_b.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Tentativa de edição maliciosa
        edit_response = self.client.patch(
            f'/api/v1/stores/merchant/{self.store_b.id}/',
            {'name': 'Tentativa de Invasão'},
            format='json'
        )
        self.assertEqual(edit_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_store_detail_by_slug(self):
        """
        Qualquer cliente pode acessar dados públicos da loja pelo slug sem autenticação.
        """
        response = self.client.get(f'/api/v1/stores/public/{self.store_a.slug}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], "Restaurante Alfa")
        self.assertEqual(response.data['slug'], "restaurante-alfa")
        # Documento fiscal não deve ser exposto na API pública
        self.assertNotIn('document', response.data)
