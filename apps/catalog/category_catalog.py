import unicodedata
import re

# Dicionário de mapeamento semântico de palavras-chave para ícones de categorias
CATEGORY_KEYWORD_ICONS = {
    # Pizzas e Derivados
    'pizza': '🍕',
    'calzone': '🥟',
    'fogaza': '🥟',
    'borda': '🥖',
    'massa': '🍝',
    'espaguete': '🍝',
    'macarrao': '🍝',
    'lasanha': '🫓',
    'nhoque': '🫓',
    'risoto': '🍲',

    # Hambúrgueres e Lanches
    'hamburguer': '🍔',
    'burger': '🍔',
    'smash': '🥓',
    'hot dog': '🌭',
    'hotdog': '🌭',
    'cachorro quente': '🌭',
    'lanche': '🥪',
    'sanduiche': '🥪',
    'beirute': '🥪',
    'bauru': '🥪',
    'misto': '🥪',
    'tapioca': '🥪',
    'crepe': '🥞',
    'panqueca': '🥞',
    'wrap': '🌯',
    'shawarma': '🌯',
    'kebab': '🌯',

    # Petiscos, Porções e Frituras
    'batata': '🍟',
    'frita': '🍟',
    'porcao': '🍟',
    'petisco': '🍟',
    'frango': '🍗',
    'coxinha': '🍗',
    'tulipa': '🍗',
    'empanado': '🍗',
    'pastel': '🥟',
    'salgado': '🥟',
    'esfiha': '🥟',
    'kibe': '🥟',
    'queijo': '🧀',
    'frios': '🧀',
    'tabua': '🧀',
    'espeto': '🍢',
    'espetinho': '🍢',
    'churrasco': '🥩',

    # Refeições e Carnes
    'marmita': '🍱',
    'marmitex': '🍱',
    'prato feito': '🍱',
    'pf': '🍱',
    'refeicao': '🍱',
    'almoco': '🍱',
    'jantar': '🍱',
    'carne': '🥩',
    'bife': '🥩',
    'picanha': '🥩',
    'mignon': '🥩',
    'costela': '🥩',
    'grelhado': '🥩',
    'sopa': '🍲',
    'caldo': '🍲',
    'feijoada': '🥘',
    'baião': '🥘',
    'salada': '🥗',
    'fit': '🥗',
    'saudavel': '🥗',
    'vegetariano': '🥦',
    'vegano': '🌱',
    'peixe': '🐟',
    'frutos do mar': '🦐',
    'camarao': '🦐',

    # Comida Oriental e Japonesa
    'sushi': '🍣',
    'sashimi': '🍣',
    'temaki': '🍱',
    'japones': '🍱',
    'oriental': '🥢',
    'yakisoba': '🥢',
    'poke': '🥗',
    'gyoza': '🥟',
    'harumaki': '🥟',
    'chines': '🥡',

    # Sobremesas, Bolos e Doces
    'sobremesa': '🍰',
    'doce': '🍬',
    'torta': '🥧',
    'bolo': '🎂',
    'confeitaria': '🎂',
    'brownie': '🍫',
    'chocolate': '🍫',
    'sorvete': '🍨',
    'gelato': '🍨',
    'picole': '🍦',
    'acai': '🍧',
    'pudim': '🍮',
    'brigadeiro': '🍬',
    'trufa': '🍬',
    'churros': '🥖',
    'donut': '🍩',
    'cookie': '🍪',

    # Bebidas
    'bebida': '🥤',
    'refrigerante': '🥤',
    'refri': '🥤',
    'suco': '🥤',
    'agua': '💧',
    'cerveja': '🍺',
    'chope': '🍺',
    'chopp': '🍺',
    'vinho': '🍷',
    'espumante': '🍾',
    'drink': '🍹',
    'cocktail': '🍹',
    'coquetel': '🍹',
    'caipirinha': '🍹',
    'gin': '🍸',
    'cafe': '☕',
    'cappuccino': '☕',
    'cha': '🍵',
    'energetico': '⚡',

    # Padaria e Café da Manhã
    'pao': '🥐',
    'padaria': '🥐',
    'croissant': '🥐',
    'waffle': '🥞',

    # Combos e Promos
    'combo': '🔥',
    'promocao': '🏷️',
    'oferta': '🎉',
    'familia': '👨‍👩‍👧‍👦',
    'mais pedido': '⭐',
    'especial': '⭐',
    'tradicional': '🍕',
    'premium': '👑',
    'gourmet': '👑',
}


def normalize_text(text: str) -> str:
    """Remove acentos e pontuações para correspondência semântica."""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text)
    unaccented = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return unaccented.lower().strip()


def has_leading_emoji(text: str) -> bool:
    """Verifica se o texto já possui um emoji ou símbolo visual no início."""
    if not text or not text.strip():
        return False
    first = text.strip()[0]
    category = unicodedata.category(first)
    # Categorias Unicode de símbolos ou pictogramas
    if category in ('So', 'Sk', 'Sm') or ord(first) > 0x2000:
        return True
    return False


def format_category_name_with_icon(name: str) -> str:
    """
    Formata o nome da categoria garantindo que ela SEMPRE possua um ícone/emoji representativo.
    Se o usuário já colocou um ícone próprio, mantém intacto.
    Se não colocou, detecta o ícone correspondente através das palavras-chave.
    """
    if not name or not name.strip():
        return name

    cleaned = name.strip()
    if has_leading_emoji(cleaned):
        return cleaned

    norm = normalize_text(cleaned)

    # 1. Busca melhor correspondência nas palavras-chave
    best_icon = None
    for kw, icon in CATEGORY_KEYWORD_ICONS.items():
        # Testa se a palavra-chave está contida no nome normalizado
        if re.search(r'\b' + re.escape(kw), norm) or kw in norm:
            best_icon = icon
            break

    # 2. Ícone fallback elegante caso nenhuma palavra-chave case
    if not best_icon:
        best_icon = '🍽️'

    return f"{best_icon} {cleaned}"


# Catálogo mestre de categorias completas prontas para uso em todos os segmentos
MASTER_CATEGORIES_PRESETS = [
    # 1. Pizzas & Massas
    {"name": "🍕 Pizzas Tradicionais", "order": 1, "description": "Pizzas consagradas e clássicas feitas com molho artesanal."},
    {"name": "⭐ Pizzas Especiais", "order": 2, "description": "Receitas autorais e combinações exclusivas da casa."},
    {"name": "👑 Pizzas Premium & Gourmet", "order": 3, "description": "Ingredientes nobres, queijos finos e toque especial do chef."},
    {"name": "🍫 Pizzas Doces", "order": 4, "description": "Deliciosas pizzas doces para fechar o pedido com chave de ouro."},
    {"name": "🥟 Calzones & Fogazas", "order": 5, "description": "Massa assada crocante e super recheada."},
    {"name": "🥖 Bordas Recheadas", "order": 6, "description": "Bordas de Catupiry, Cheddar, Nutella e Chocolate."},
    {"name": "🍝 Massas & Espaguetes", "order": 7, "description": "Massas frescas artesanais com molhos tradicionais italianos."},
    {"name": "🫓 Lasanhas & Nhoques", "order": 8, "description": "Lasanhas gratinadas no forno e nhoques com queijo derretido."},

    # 2. Hambúrgueres & Lanches
    {"name": "🍔 Hambúrgueres Artesanais", "order": 10, "description": "Burgers artesanais suculentos no pão brioche amanteigado."},
    {"name": "🥓 Smash Burgers", "order": 11, "description": "Burgers prensados na chapa ultra crocantes com queijo derretido."},
    {"name": "🌭 Hot Dogs & Cachorro-Quente", "order": 12, "description": "Hot dogs caprichados completos no pão macio."},
    {"name": "🥪 Lanches & Sanduíches", "order": 13, "description": "Mistos quentes, beirutes, baurus e sanduíches naturais."},
    {"name": "🌯 Wraps & Tapiocas", "order": 14, "description": "Opções leves, wraps finos e tapiocas crocantes e recheadas."},

    # 3. Petiscos & Porções
    {"name": "🍟 Batatas Fritas & Porções", "order": 20, "description": "Porções crocantes e sequinhas perfeitas para compartilhar."},
    {"name": "🍗 Frangos & Coxinhas", "order": 21, "description": "Frango frito crocante, tulipas e coxinhas gourmets."},
    {"name": "🥟 Salgados & Pastéis", "order": 22, "description": "Pastéis crocantes e salgados assados e fritos na hora."},
    {"name": "🧀 Tábua de Frios & Petiscos", "order": 23, "description": "Queijos selecionados, azeitonas, salames e embutidos nobres."},
    {"name": "🍢 Espetinhos & Churrasco", "order": 24, "description": "Carnes selecionadas na brasa com farofa e vinagrete."},

    # 4. Refeições & Marmitas
    {"name": "🍱 Marmitas & Prato Feito (PF)", "order": 30, "description": "Refeições completas, caseiras e balanceadas com gostinho de casa."},
    {"name": "🥩 Carnes & Grelhados", "order": 31, "description": "Picanha, filé mignon, maminha e cortes nobres preparados no ponto."},
    {"name": "🍲 Sopas & Caldos", "order": 32, "description": "Caldos quentinhos e sopas nutritivas reconfortantes."},
    {"name": "🥘 Feijoada & Pratos Típicos", "order": 33, "description": "A autêntica feijoada completa com todos os acompanhamentos."},
    {"name": "🥗 Saladas & Comida Saudável", "order": 34, "description": "Saladas frescas, bowls funcionais e opções fit saudáveis."},
    {"name": "🥦 Opções Vegetarianas & Veganas", "order": 35, "description": "Pratos 100% livres de carne com muito sabor e criatividade."},
    {"name": "🦐 Peixes & Frutos do Mar", "order": 36, "description": "Iscas de peixe, camarões empanados e moquecas aromáticas."},

    # 5. Comida Japonesa & Oriental
    {"name": "🍣 Sushis & Sashimis", "order": 40, "description": "Combinados de salmão fresco, sashimis, uramakis e hossomakis."},
    {"name": "🍱 Temakis & Combos Japoneses", "order": 41, "description": "Temakis crocantes e barcas especiais completas."},
    {"name": "🥢 Yakisobas & Pratos Quentes", "order": 42, "description": "Yakisobas tradicionais de carne, frango e legumes."},

    # 6. Sobremesas, Doces & Bolos
    {"name": "🍰 Sobremesas & Tortas", "order": 50, "description": "Fatias de tortas artesanais, mousses e cheesecakes."},
    {"name": "🎂 Bolos & Confeitaria", "order": 51, "description": "Bolos caseiros, bolos de pote e bolos recheados confeitados."},
    {"name": "🍧 Açaí no Copo & Tigelas", "order": 52, "description": "Açaí cremoso batido com frutas, leite condensado e coberturas."},
    {"name": "🍨 Sorvetes & Picolés", "order": 53, "description": "Sorvetes artesanais cremosos de massa e picolés refrescantes."},
    {"name": "🍫 Chocolates & Brownies", "order": 54, "description": "Brownies quentinhos com calda, cookies e chocolates."},
    {"name": "🍮 Pudins & Doces Caseiros", "order": 55, "description": "Pudim de leite condensado, quindins e doces tradicionais."},
    {"name": "🍬 Brigadeiros & Trufas", "order": 56, "description": "Brigadeiros gourmet de colher, beijinhos e trufas recheadas."},

    # 7. Bebidas
    {"name": "🥤 Refrigerantes & Sucos", "order": 60, "description": "Refrigerantes em lata e 2L, sucos naturais e néctares."},
    {"name": "💧 Águas & Isotônicos", "order": 61, "description": "Água mineral com e sem gás, isotônicos e energéticos."},
    {"name": "🍺 Cervejas & Chopes", "order": 62, "description": "Cervejas long neck, latão e cervejas artesanais trincando de geladas."},
    {"name": "🍷 Vinhos & Espumantes", "order": 63, "description": "Cartela selecionada de vinhos tintos, brancos e espumantes."},
    {"name": "🍹 Drinks & Coquetéis", "order": 64, "description": "Caipirinhas, gin tônicas e drinks preparados na hora."},
    {"name": "☕ Cafés & Chás", "order": 65, "description": "Espressos aromáticos, cappuccinos cremosos e chás reconfortantes."},

    # 8. Café da Manhã & Padaria
    {"name": "🥐 Pães & Croissants", "order": 70, "description": "Pães de queijo quentinhos, croissants folhados e baguetes."},
    {"name": "🥞 Panquecas & Waffles", "order": 71, "description": "Panquecas americanas com mel e waffles doces e salgados."},

    # 9. Combos & Promoções
    {"name": "🔥 Combos & Promoções", "order": 80, "description": "Combos completos com super desconto especial."},
    {"name": "👨‍👩‍👧‍👦 Tamanho Família", "order": 81, "description": "Opções econômicas generosas para toda a família e amigos."},
    {"name": "🎉 Ofertas do Dia", "order": 82, "description": "Os melhores preços do dia selecionados para você."}
]


def seed_store_categories(store) -> int:
    """
    Popula o catálogo de categorias padrão para a loja especificada.
    Garante que categorias existentes sejam preservadas e não duplicadas.
    Retorna o número de novas categorias criadas.
    """
    from .models import Category

    existing_names = set(
        normalize_text(name)
        for name in Category.objects.filter(store=store).values_list('name', flat=True)
    )

    created_count = 0
    for preset in MASTER_CATEGORIES_PRESETS:
        norm_preset = normalize_text(preset['name'])
        # Se já existe uma categoria com nome semelhante (ex: 'Pizzas Tradicionais'), pula
        already_exists = False
        for ex in existing_names:
            if norm_preset in ex or ex in norm_preset:
                already_exists = True
                break

        if not already_exists:
            Category.objects.create(
                store=store,
                name=preset['name'],
                order=preset['order'],
                description=preset['description'],
                is_active=True
            )
            existing_names.add(norm_preset)
            created_count += 1

    return created_count
