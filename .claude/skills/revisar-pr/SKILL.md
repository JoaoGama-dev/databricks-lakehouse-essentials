---
name: revisar-pr
description: Use para revisar a segurança e a qualidade de um diff ou pull request - segredos, dados pessoais, permissões, dependências, LGPD - com saída em formato fixo (bloqueante, recomendado, ok).
---

# Revisar um pull request

1. **Pegar o diff:** `git diff main...HEAD` (ou o PR indicado). Leia só o diff e os
   arquivos que ele toca; nunca abra dados reais.
2. **Checklist de segurança:**
   - segredos: tokens (`dapi`, `ghp_`, `gho_`), chaves privadas, senhas, `.env`;
   - dados pessoais: nomes, telefones, CPF, e-mails reais em código, testes, docs ou
     mensagens de commit; CSV fora de `data/agenda_exemplo_v*.csv`;
   - permissões: regras `allow` amplas no `.claude/settings.json`, `permissions:` dos
     workflows maiores que o necessário, grants amplos;
   - produção: qualquer caminho que mude prod fora do workflow `deploy.yml`;
   - dependências e actions sem versão fixa;
   - hosts, e-mails ou IDs de ambiente escritos no código.
3. **Checklist de qualidade:** nomes, dicionário de dados, testes para o comportamento
   novo (os detalhes estão na skill `revisao-qualidade`).
4. **Responder exatamente neste formato:**

```
## Bloqueante
- arquivo:linha - problema - correção sugerida
## Recomendado
- arquivo:linha - melhoria - motivo
## OK
- o que foi verificado e está certo
```

Se uma seção não tiver itens, escreva "nenhum".

**Pronto quando:** as três seções foram entregues e todo item tem arquivo e linha.
