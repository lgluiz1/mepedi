from decimal import Decimal
from django.core.management.base import BaseCommand
from accounts.models import User, StoreMembership
from stores.models import Store, BusinessHour
from catalog.models import Category, Product, OptionGroup, OptionItem
from delivery.models import DeliveryZone
from customers.models import Customer
from orders.models import Order, OrderItem, OrderItemOption


class Command(BaseCommand):
    help = "Popula o banco de dados com dados realistas de demonstração para a Pizzaria Bella."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Iniciando população de dados de demonstração..."))

        # 1. Usuário Lojista / Administrador
        owner, created = User.objects.get_or_create(
            email="admin@pizzaria.com",
            defaults={
                "full_name": "Mario Dono",
                "phone": "(11) 98765-4321",
                "is_staff": True,
                "is_superuser": True,
                "is_merchant": True,
            }
        )
        if created or not owner.has_usable_password():
            owner.set_password("admin123")
            owner.save()
            self.stdout.write(self.style.SUCCESS("[OK] Usuário 'admin@pizzaria.com' criado (senha: admin123)"))

        # 2. Estabelecimento (Loja)
        store, created = Store.objects.get_or_create(
            slug="pizzaria-bella",
            defaults={
                "owner": owner,
                "name": "Pizzaria Bella & Forno a Lenha",
                "description": "As melhores pizzas artesanais em forno a lenha de São Paulo. Massa de fermentação lenta.",
                "whatsapp": "(11) 98765-4321",
                "phone": "(11) 3344-5566",
                "street": "Rua Augusta",
                "number": "1500",
                "neighborhood": "Consolação",
                "city": "São Paulo",
                "state": "SP",
                "postal_code": "01305-100",
                "is_active": True,
                "is_open": True,
                "is_paused": False,
                "banner": "stores/banners/pizzaria_banner.jpg",
                "logo": "stores/logos/pizzaria_logo.jpg",
                "minimum_order_value": Decimal("30.00"),
            }
        )
        if not store.banner:
            store.banner = "stores/banners/pizzaria_banner.jpg"
        if not store.logo:
            store.logo = "stores/logos/pizzaria_logo.jpg"
        store.save()
        StoreMembership.objects.get_or_create(
            user=owner,
            store=store,
            defaults={"role": "owner", "is_active": True}
        )
        self.stdout.write(self.style.SUCCESS(f"[OK] Loja '{store.name}' vinculada (/pizzaria-bella/)"))

        # 3. Horários de Funcionamento (Seg a Dom, 18:00 às 23:59)
        for day in range(7):
            BusinessHour.objects.get_or_create(
                store=store,
                weekday=day,
                defaults={
                    "opening_time": "18:00:00",
                    "closing_time": "23:59:00",
                    "is_closed": False
                }
            )

        # 4. Zonas de Entrega
        zone_centro, _ = DeliveryZone.objects.get_or_create(
            store=store,
            name="Região Central",
            defaults={
                "fee": Decimal("6.00"),
                "estimated_time_min": 30,
                "estimated_time_max": 45,
                "neighborhoods": "Centro, Bela Vista, Consolação, República, Higienópolis",
                "is_active": True
            }
        )
        zone_paulista, _ = DeliveryZone.objects.get_or_create(
            store=store,
            name="Jardins & Paulista",
            defaults={
                "fee": Decimal("9.00"),
                "estimated_time_min": 40,
                "estimated_time_max": 55,
                "neighborhoods": "Jardins, Cerqueira César, Paraíso, Vila Mariana",
                "is_active": True
            }
        )

        # 5. Categorias
        cat_trad, _ = Category.objects.get_or_create(store=store, name="🍕 Pizzas Tradicionais", defaults={"order": 1})
        cat_espec, _ = Category.objects.get_or_create(store=store, name="⭐ Pizzas Especiais", defaults={"order": 2})
        cat_bebidas, _ = Category.objects.get_or_create(store=store, name="🥤 Bebidas", defaults={"order": 3})
        cat_doces, _ = Category.objects.get_or_create(store=store, name="🍰 Sobremesas", defaults={"order": 4})

        # 6. Produtos e Adicionais
        # Pizza Calabresa
        p_calabresa, _ = Product.objects.get_or_create(
            store=store,
            category=cat_trad,
            name="Calabresa Especial",
            defaults={
                "description": "Molho de tomate artesanal, fatias generosas de calabresa defumada, cebola roxa e azeitonas pretas.",
                "price": Decimal("48.00"),
                "image": "products/images/pizza_calabresa.jpg",
                "is_active": True,
                "order": 1
            }
        )
        if not p_calabresa.image:
            p_calabresa.image = "products/images/pizza_calabresa.jpg"
            p_calabresa.save()
        # Grupo de Bordas
        grp_bordas, _ = OptionGroup.objects.get_or_create(
            product=p_calabresa,
            name="Bordas Recheadas",
            defaults={"min_options": 0, "max_options": 1, "is_required": False, "order": 1}
        )
        opt_catupiry, _ = OptionItem.objects.get_or_create(
            option_group=grp_bordas,
            name="Catupiry Original",
            defaults={"price": Decimal("8.00"), "is_available": True}
        )
        OptionItem.objects.get_or_create(
            option_group=grp_bordas,
            name="Cheddar Cremoso",
            defaults={"price": Decimal("8.00"), "is_available": True}
        )

        # Grupo de Remoções
        grp_remocoes, _ = OptionGroup.objects.get_or_create(
            product=p_calabresa,
            name="Preferências de Ingredientes",
            defaults={"min_options": 0, "max_options": 2, "is_required": False, "order": 2}
        )
        opt_sem_cebola, _ = OptionItem.objects.get_or_create(
            option_group=grp_remocoes,
            name="Sem Cebola",
            defaults={"price": Decimal("0.00"), "is_available": True}
        )
        OptionItem.objects.get_or_create(
            option_group=grp_remocoes,
            name="Sem Azeitonas",
            defaults={"price": Decimal("0.00"), "is_available": True}
        )

        # Pizza Margherita
        Product.objects.get_or_create(
            store=store,
            category=cat_trad,
            name="Margherita Di Bufala",
            defaults={
                "description": "Molho pelado italiano, mozzarella de búfala fresca, manjericão gigante e azeite extravirgem.",
                "price": Decimal("54.00"),
                "is_active": True,
                "order": 2
            }
        )

        # Pizza Família (4 Sabores Obrigatórios - Caso de Uso Solicitado)
        p_familia, _ = Product.objects.get_or_create(
            store=store,
            category=cat_espec,
            name="Pizza Família (Escolha 4 Sabores)",
            defaults={
                "description": "Pizza gigante de 40cm. Monte sua pizza combinando exatamente 4 sabores favoritos entre tradicionais e especiais.",
                "price": Decimal("74.00"),
                "image": "products/images/pizza_calabresa.jpg",
                "is_active": True,
                "order": 0
            }
        )
        grp_sabores, _ = OptionGroup.objects.get_or_create(
            product=p_familia,
            name="Escolha 4 Sabores",
            defaults={
                "description": "Obrigatório selecionar 4 sabores para compor os 4 quadrantes da pizza.",
                "min_options": 4,
                "max_options": 4,
                "is_required": True,
                "order": 1
            }
        )
        sabores_data = [
            ("Calabresa Especial", Decimal("0.00"), True),
            ("Quatro Queijos Gratinado", Decimal("0.00"), True),
            ("Frango Cremoso com Catupiry", Decimal("0.00"), True),
            ("Margherita Clássica", Decimal("0.00"), True),
            ("Portuguesa Completa", Decimal("0.00"), True),
            ("Camarão Especial (+R$ 10,00)", Decimal("10.00"), True),
            ("Lombo Canadense (Esgotado Hoje)", Decimal("0.00"), False),
        ]
        for s_name, s_price, s_avail in sabores_data:
            OptionItem.objects.get_or_create(
                option_group=grp_sabores,
                name=s_name,
                defaults={"price": s_price, "is_available": s_avail}
            )

        # Borda opcional para a Pizza Família
        grp_borda_fam, _ = OptionGroup.objects.get_or_create(
            product=p_familia,
            name="Borda Recheada",
            defaults={"min_options": 0, "max_options": 1, "is_required": False, "order": 2}
        )
        OptionItem.objects.get_or_create(option_group=grp_borda_fam, name="Borda Catupiry", defaults={"price": Decimal("9.00"), "is_available": True})
        OptionItem.objects.get_or_create(option_group=grp_borda_fam, name="Borda Vulcão Cheddar", defaults={"price": Decimal("9.00"), "is_available": True})


        # Pizza Quatro Queijos
        Product.objects.get_or_create(
            store=store,
            category=cat_espec,
            name="Quatro Formaggi Gran Riserva",
            defaults={
                "description": "Mozzarella, Gorgonzola italiano dolce, Catupiry legítimo e Parmesão maturado 12 meses.",
                "price": Decimal("58.00"),
                "is_active": True,
                "order": 1
            }
        )

        # Bebidas
        Product.objects.get_or_create(
            store=store,
            category=cat_bebidas,
            name="Coca-Cola Original 2L",
            defaults={"description": "Garrafa PET 2 Litros gelada.", "price": Decimal("14.00"), "is_active": True, "order": 1}
        )
        Product.objects.get_or_create(
            store=store,
            category=cat_bebidas,
            name="Guaraná Antarctica 2L",
            defaults={"description": "Garrafa PET 2 Litros gelada.", "price": Decimal("12.00"), "is_active": True, "order": 2}
        )

        # Sobremesa
        Product.objects.get_or_create(
            store=store,
            category=cat_doces,
            name="Pudim de Leite Tradicional",
            defaults={"description": "Fatia generosa com calda dourada de caramelo sem furinhos.", "price": Decimal("16.00"), "is_active": True, "order": 1}
        )

        # 7. Pedido demonstrativo para o Painel
        customer, _ = Customer.objects.get_or_create(
            store=store,
            phone="11998877665",
            defaults={"name": "Ana Clara Santos"}
        )

        demo_order, order_created = Order.objects.get_or_create(
            store=store,
            order_number=1001,
            defaults={
                "customer": customer,
                "delivery_type": Order.TYPE_DELIVERY,
                "status": Order.STATUS_NEW,
                "payment_method": Order.PAY_MONEY,
                "change_for": Decimal("100.00"),
                "street": "Alameda Santos",
                "number": "1200",
                "complement": "Apto 81",
                "neighborhood": "Cerqueira César",
                "city": "São Paulo",
                "state": "SP",
                "reference": "Em frente ao colégio",
                "subtotal": Decimal("56.00"),
                "delivery_fee": Decimal("9.00"),
                "total": Decimal("65.00"),
                "notes": "Por favor, não tocar a campainha, mandar mensagem no WhatsApp."
            }
        )

        if order_created:
            item = OrderItem.objects.create(
                order=demo_order,
                product_name="Calabresa Especial",
                unit_price=Decimal("48.00"),
                quantity=1,
                subtotal=Decimal("48.00"),
                total=Decimal("56.00"),
                notes="Borda bem douradinha"
            )
            OrderItemOption.objects.create(
                order_item=item,
                name="Catupiry Original",
                price=Decimal("8.00"),
                group_name="Bordas Recheadas"
            )
            OrderItemOption.objects.create(
                order_item=item,
                name="Sem Cebola",
                price=Decimal("0.00"),
                group_name="Preferências de Ingredientes"
            )

        self.stdout.write(self.style.SUCCESS("[OK] Catálogo, produtos e pedido de demonstração criados com sucesso!"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("Pronto para testar:"))
        self.stdout.write(self.style.SUCCESS("1. Cardápio Público:   http://localhost:8000/pizzaria-bella/"))
        self.stdout.write(self.style.SUCCESS("2. Painel do Lojista:   http://localhost:8000/painel/ (admin@pizzaria.com / admin123)"))
        self.stdout.write(self.style.SUCCESS("3. Admin do Django:     http://localhost:8000/admin/"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
