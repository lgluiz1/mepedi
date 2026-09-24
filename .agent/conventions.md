# Convenções de Código e Padrões - IA-Pedidos

## Python & Django
- **PEP 8**: Nomes de variáveis e funções em `snake_case`, classes em `PascalCase`, constantes em `UPPER_SNAKE_CASE`.
- **Modelos**:
  - Toda tabela deve ter `created_at` e `updated_at` (herdar de `core.models.TimeStampedModel`).
  - Utilizar `verbose_name` e `verbose_name_plural` em português para painel administrativo amigável.
  - Campos monetários devem utilizar `DecimalField` (max_digits=10, decimal_places=2), nunca `FloatField`.
  - Definir `__str__` claro e informativo em todos os modelos.
  - Definir `indexes` e `constraints` explicitamente para garantir integridade e performance.
- **Consultas & Queries**:
  - Sempre usar `select_related` e `prefetch_related` para evitar problemas de N+1 queries.
  - Queries de multi-tenancy devem sempre filtrar explicitamente por `store=...` ou `store_id=...`.
- **Validação e Regras de Negócio**:
  - Lógica de negócio pesada fica em camada de serviços (`services.py`) ou métodos do modelo, NUNCA espalhada em templates ou controllers gordos.
  - Todo cálculo de preço/carrinho/total de pedido é recalculado estritamente no backend.

## Frontend & Estilo
- **HTML Semântico**: Uso de `<header>`, `<nav>`, `<main>`, `<section>`, `<article>`, `<footer>`.
- **Design System**: Vanilla CSS moderno, variáveis CSS (`--primary`, `--surface`, `--text`, etc.), design mobile-first e responsivo.
- **Acessibilidade & UX**: Labels claros, micro-animações suaves, feedback visual imediato para ações do usuário (adicionar ao carrinho, status da loja).
- **Sem frameworks JS pesados no MVP**: JavaScript modular vanilla para manipulação do DOM e carrinho de compras local/sessão.

## Git & Commits
- Mensagens claras em português ou inglês no formato conventional commits:
  - `feat: ...`
  - `fix: ...`
  - `refactor: ...`
  - `docs: ...`
  - `test: ...`

## Testes Automatizados
- Todo módulo deve possuir testes unitários e de integração em `tests/` ou `tests.py`.
- Casos essenciais obrigatórios:
  - Criação de usuário e autenticação.
  - Criação de loja e geração automática de slug único.
  - Isolamento de dados entre lojas (Loja A vs Loja B).
  - Integridade de cálculo de pedidos.
