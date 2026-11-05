# 0005. Testes de integração num target ci isolado, destruído ao fim

- **Status:** aceita, atualizada por [0018](0018-schemas-por-camada.md) e
  [0020](0020-exemplo-sem-cargos-e-view-que-mascara.md) (o target `ci` tem quatro schemas
  `_ci_*` e não usa mais origem simulada)
- **Data:** 2026-11-03

## Contexto

Até a Fase 4, os testes eram estáticos: conferiam a configuração e o SQL gerado, mas
nenhum rodava o pipeline e olhava os dados. O plano pedia um workflow que implantasse o
bundle, carregasse a agenda fictícia v1 e a v2, conferisse os totais (determinísticos,
porque o gerador usa semente fixa) e limpasse tudo ao fim, num schema isolado do dev.

Ao planejar, apareceram quatro restrições:

- O estado do deploy fica na pasta do target. Trocar só a variável `projeto` no target
  `dev` faria o bundle renomear o pipeline e recriar os schemas do dev de quem roda.
- A fonte `cargos` lê `{catalogo}.{projeto}_origem.cadastro_cargos`; com outro projeto,
  essa origem simulada também precisa existir.
- A gold usa a função de máscara, criada pela tarefa `governanca_antes` do job; num
  deploy novo, `--validate-only` falha antes dela.
- Os schemas tinham `prevent_destroy: true` na própria definição (Fase 3), e o hook local
  bloqueia qualquer `bundle destroy`.

## Decisão

1. **Target `ci`** no `databricks.yml`: modo development, projeto `<projeto>_ci` (um teste
   confere o sufixo), pasta de estado própria, agendamento e alerta pausados. Gera
   `dev_<usuário>_<projeto>_ci` e `_ci_gold`.
   **A proteção `prevent_destroy: true` saiu da base (`resources/governanca.yml`) e fica
   declarada nos targets `dev` e `prod`**, com teste que a exige nos dois. A primeira
   versão desligava a proteção no `ci` com um override para `false`, mas a CLI antes da
   v1.22.0 ignora overrides para o valor zero (CHANGELOG oficial: "Zero-value overrides
   of `presets`, `lifecycle.prevent_destroy` ..."), e o CI usa a `setup-cli` v1.21.0: o
   destroy foi recusado na primeira execução. Com a proteção só onde ela vale, funciona em
   qualquer versão.
2. **Workflow `integracao.yml`**, só `workflow_dispatch` e `schedule` (1h, segunda a
   sexta), sem gatilho de PR; `concurrency` impede duas execuções ao mesmo tempo. Ordem:
   deploy → resumo do bundle → origem e landing vazia → `governanca_antes` →
   `--validate-only` → v1 → carga → asserções → v2 → carga → asserções → destroy e
   limpeza, estes dois **sempre** (`if: always()`).
3. **`scripts/integracao.py`** prepara a origem a partir do próprio
   `setup/00_setup_free_edition.sql`, envia os arquivos e limpa o que o destroy não leva
   (event log, origem). Ele **recusa qualquer schema que não termine em `_ci`, `_ci_gold`
   ou `_ci_origem`**, com testes de unidade, e pega os nomes reais do `bundle summary`.
4. **Asserções em `tests/integracao/`**, pelo `databricks-sdk` (versão fixa), com os totais
   esperados num arquivo só (`esperado.py`). Marcadores `unidade` e `integracao`; o
   `pytest -q` padrão roda só `unidade`.
5. **Sem testes locais com PySpark** (item opcional): exigiriam Java e ~300 MB no
   Windows, e a integração já executa as expressões geradas no Databricks.

## Alternativas consideradas

- **`-t dev` com `--var projeto=..._ci`:** recriaria os recursos do dev (mesmo estado).
- **`presets.name_prefix` próprio no ci, mantendo o projeto:** dispensaria criar a origem,
  mas o projeto do ci teria o mesmo nome do dev e o pipeline leria a origem do dev.
- **Subir a `setup-cli` para a v1.22.x e manter o override para `false`:** a v1.22.0 saiu
  em 22/10 e só passaria na regra das 2 semanas (Fase 2) em 05/11; além disso, a
  proteção dependeria da versão da CLI.
- **Rodar a integração em todo PR:** gastaria a cota do Free Edition a cada push e
  exporia o token a código de PR.

## Consequências

- Cada execução são duas cargas completas, mais o deploy e o destroy, no Free Edition:
  com a cota diária estourada, a Databricks recusa novas execuções de job e o workflow
  falha sem ser culpa do código (visto ao implementar esta fase).
- Mudança intencional nos totais (gerador, `fontes.yml`, silver) exige atualizar o
  `esperado.py` no mesmo PR.
- No dev, o agendamento do job foi pausado: a carga diária automática passa a ser
  exercitada pelo workflow de integração.
