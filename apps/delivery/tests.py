from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from stores.models import Store
from accounts.models import StoreMembership
from delivery.models import DeliveryZone

User = get_user_model()


class DeliveryZoneModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='delivery_owner@teste.com',
            password='Password123!',
            full_name='Delivery Owner'
        )
        self.store = Store.objects.create(
            owner=self.user,
            name="Hamburgueria Express",
            whatsapp="11911112222"
        )

    def test_delivery_zone_creation(self):
        """Testa criação de zona de entrega."""
        zone = DeliveryZone.objects.create(
            store=self.store,
            name="Região Central",
            neighborhoods="Centro, República, Bela Vista, Consolação",
            fee=Decimal("7.50"),
            estimated_time_min=25,
            estimated_time_max=45
        )
        self.assertEqual(zone.name, "Região Central")
        self.assertEqual(zone.fee, Decimal("7.50"))
        self.assertTrue(zone.is_active)

    def test_neighborhood_matching(self):
        """Testa validação e correspondência de bairro dentro da zona."""
        zone = DeliveryZone.objects.create(
            store=self.store,
            name="Zona Oeste",
            neighborhoods="Pinheiros, Vila Madalena, Perdizes",
            fee=Decimal("10.00")
        )
        self.assertTrue(zone.match_neighborhood("Pinheiros"))
        self.assertTrue(zone.match_neighborhood("vila madalena"))  # Case-insensitive
        self.assertTrue(zone.match_neighborhood("  Perdizes  "))  # Com espaços
        self.assertFalse(zone.match_neighborhood("Moema"))  # Bairro não atendido


class DeliveryCalculationAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email='owner@calc.com',
            password='Password123!',
            full_name='Owner Calc'
        )
        self.store = Store.objects.create(
            owner=self.owner,
            name="Pizzaria Express",
            whatsapp="11988887777",
            is_active=True
        )

        self.zone1 = DeliveryZone.objects.create(
            store=self.store,
            name="Zona A",
            neighborhoods="Jardins, Cerqueira César",
            fee=Decimal("8.00"),
            is_active=True
        )
        self.zone2 = DeliveryZone.objects.create(
            store=self.store,
            name="Zona B",
            neighborhoods="Brooklin, Campo Belo",
            fee=Decimal("14.00"),
            is_active=True
        )

    def test_public_zones_list(self):
        """Lista regiões de entrega ativas da loja pelo slug."""
        response = self.client.get(f'/api/v1/delivery/public/{self.store.slug}/zones/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(len(results), 2)

    def test_calculate_fee_for_matched_neighborhood(self):
        """Calcula taxa de entrega correta quando o bairro informado coincide com a zona."""
        response = self.client.post(
            f'/api/v1/delivery/public/{self.store.slug}/calculate-fee/',
            {"neighborhood": "Jardins"},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['matched'])
        self.assertEqual(Decimal(response.data['delivery_fee']), Decimal("8.00"))
        self.assertEqual(response.data['zone_name'], "Zona A")


class DeliveryMultiTenancyAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.user_a = User.objects.create_user(email='loj_a@teste.com', password='Password123!', full_name='Loj A')
        self.store_a = Store.objects.create(owner=self.user_a, name="Loja A", whatsapp="11900000001")
        StoreMembership.objects.create(user=self.user_a, store=self.store_a, role=StoreMembership.ROLE_OWNER)

        self.user_b = User.objects.create_user(email='loj_b@teste.com', password='Password123!', full_name='Loj B')
        self.store_b = Store.objects.create(owner=self.user_b, name="Loja B", whatsapp="11900000002")
        StoreMembership.objects.create(user=self.user_b, store=self.store_b, role=StoreMembership.ROLE_OWNER)

        self.zone_a = DeliveryZone.objects.create(store=self.store_a, name="Zona A", fee=Decimal("5.00"))
        self.zone_b = DeliveryZone.objects.create(store=self.store_b, name="Zona B", fee=Decimal("9.00"))

    def test_merchant_cannot_manage_zones_of_another_store(self):
        """Lojista A não pode listar ou criar regiões na Loja B (403 Forbidden)."""
        self.client.force_authenticate(user=self.user_a)

        # Tenta listar zonas da Loja B
        resp = self.client.get(f'/api/v1/delivery/merchant/{self.store_b.id}/zones/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Tenta criar zona na Loja B
        create_resp = self.client.post(
            f'/api/v1/delivery/merchant/{self.store_b.id}/zones/',
            {"name": "Zona Hacker", "fee": "1.00"},
            format='json'
        )
        self.assertEqual(create_resp.status_code, status.HTTP_403_FORBIDDEN)
