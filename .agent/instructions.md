# Instruções do Agente - IA-Pedidos

Este documento contém as diretrizes e regras operacionais fundamentais para qualquer agente de IA ou desenvolvedor trabalhando neste projeto.

## Papel
Você atua como **Arquiteto + Desenvolvedor Principal + Mantenedor de Contexto**.

## Fluxo Obrigatório de Desenvolvimento
Antes de qualquer alteração no código:

1. **ETAPA A — ENTENDER**:
   - Identifique claramente o que foi solicitado.
   - Identifique os módulos, modelos, APIs, telas e regras de negócio impactadas.

2. **ETAPA B — ANALISAR**:
   - Consulte `.agent/instructions.md`, `.agent/architecture.md`, `.agent/conventions.md` e `.agent/tasks.md`.
   - Consulte a documentação específica em `docs/`.
   - Procure implementações existentes para reutilização (evite duplicação a todo custo).
   - Verifique dependências e isolamento entre lojas (multi-tenancy).

3. **ETAPA C — PLANEJAR**:
   - Trace internamente uma estratégia enxuta e coesa.
   - Para mudanças estruturais ou de grande impacto, registre em `docs/decisions/`.

4. **ETAPA D — IMPLEMENTAR**:
   - Implemente com código limpo, sustentável e seguindo os padrões do Django.
   - Garanta isolamento de loja (multi-tenancy via `store_id`).
   - Valide regras de negócio no servidor (nunca confie exclusivamente no cliente).

5. **ETAPA E — VALIDAR**:
   - Execute migrações e testes automatizados.
   - Valide integridade de imports, rotas, endpoints e permissões.
   - Garanta que testes de isolamento entre lojas passem.

6. **ETAPA F — DOCUMENTAR**:
   - Atualize `.agent/tasks.md` e os arquivos pertinentes em `docs/`.
   - Mantenha o histórico vivo.

## Regras Críticas
- **Multi-tenancy Lógico**: Toda entidade associada a uma loja deve possuir chave estrangeira para `Store`. Toda consulta no painel e operações de pedido/cliente deve ser filtrada por loja. Loja A NUNCA acessa dados da Loja B.
- **Não Antecipar Complexidade Excessiva**: Siga o princípio YAGNI e KISS. Não crie microsserviços, múltiplos bancos ou frameworks SPA sem necessidade.
- **Validação Server-Side**: Preços, adicionais e totais de pedidos devem SEMPRE ser recalculados no backend com base no banco de dados.
- **Identificador do Cliente**: O telefone é o identificador chave do cliente por loja. Não forçar criação de senha no fluxo de pedidos do MVP.
