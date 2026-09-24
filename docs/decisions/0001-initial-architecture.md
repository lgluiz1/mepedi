# ADR 0001: Arquitetura Inicial e Multi-Tenancy

## Data
2026-09-24

## Status
Aceito

## Contexto
O projeto IA-Pedidos necessita suportar múltiplos lojistas, cada um com seus produtos, clientes, pedidos e configurações próprias, com garantia absoluta de que dados de uma loja não vazem ou sejam acessados por outra. Ao mesmo tempo, o projeto está em estágio inicial (MVP) e requer simplicidade de manutenção, baixo custo de infraestrutura e velocidade de desenvolvimento.

## Decisão
1. **Multi-Tenancy Lógico Compartilhado**:
   - Optou-se por banco de dados e schema compartilhados, com uma chave estrangeira obrigatória (`store_id` / `ForeignKey(Store)`) em todos os modelos vinculados à loja.
   - Rejeitou-se a abordagem de schemas separados (ex: `django-tenants`) ou bancos de dados isolados por loja para o MVP, pois adicionaria overhead operacional desnecessário (migrações complexas, pool de conexões caro).
2. **Framework Backend**:
   - Django 5.x com Django REST Framework. O Django fornece um ecossistema maduro para autenticação, ORM robusto com transações ACID, painel administrativo para suporte interno e facilidade de testes.
3. **Custom User Model**:
   - Criação imediata de um modelo customizado `User` em `accounts` herdando de `AbstractUser` para evitar migrações complexas posteriores no Django.
4. **PostgreSQL**:
   - Banco de dados relacional oficial de produção com suporte a transações robustas, constraints complexas e campos JSON quando necessário.
5. **Autonomia do Cliente Final**:
   - O consumidor final não cria senha no MVP. Ele se identifica pelo número de telefone, reduzindo o atrito na conversão de vendas.

## Consequências
- Todas as queries do painel do lojista precisam garantir a cláusula de filtro por loja (`filter(store=...)`).
- Deve haver testes automatizados estritos validando que a Loja A não pode acessar registros da Loja B.
