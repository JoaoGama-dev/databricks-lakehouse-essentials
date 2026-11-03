# 0011. Deploy de produção só pelo GitHub Actions, com OIDC

- **Status:** aceita
- **Data:** 2026-10-30 (registrada em 2026-11-03)

## Contexto

A produção roda no Azure Databricks do cliente. Um deploy feito da máquina de alguém
não deixa registro de quem implantou o quê, pode levar código que não passou pelo CI e
exige um token de produção guardado em algum lugar. O repositório é público.

## Decisão

1. **Produção só pelo workflow `deploy.yml`**, nunca por comando local: `bundle validate`
   e `bundle deploy -t prod` no **environment `prod`** do GitHub, que pede aprovação
   manual. Por ora o disparo é manual; o deploy automático na `main` está comentado no
   workflow.
2. **Login por OIDC** (`DATABRICKS_AUTH_TYPE: github-oidc`): o GitHub emite um token de
   curta duração para o job, e o Databricks o aceita pela **federation policy** do
   service principal de produção para este repositório. Nenhum segredo de produção fica
   no GitHub; host e client ID são variáveis do environment.
3. O bundle roda em prod como o **service principal** (`run_as`), e o host não fica no
   repositório.
4. Localmente, qualquer comando com `-t prod` é negado (`.claude/settings.json`) e
   bloqueado pelo hook `proteger_comandos.py`.

## Alternativas consideradas

- **Token pessoal de acesso (PAT) como segredo do repositório:** credencial longa,
  ligada a uma pessoa e que vaza junto com o segredo.
- **Segredo do service principal (OAuth M2M) no GitHub:** melhor que PAT, mas ainda é
  um segredo de longa duração para girar e proteger.
- **Deploy manual pela CLI:** sem trilha de auditoria nem aprovação.

## Consequências

- Todo deploy de produção tem PR, CI verde, aprovação e registro no GitHub Actions.
- A configuração inicial no cliente é mais trabalhosa (federation policy, environment,
  variáveis), descrita em `docs/levando-ao-azure.md`.
- O Free Edition não oferece service principal com OIDC: o dev e o `ci` usam token de
  usuário, com validade de 90 dias, que precisa ser renovado.
