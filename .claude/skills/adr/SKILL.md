---
name: adr
description: Use quando houver uma decisão de arquitetura para registrar (escolha de tecnologia, padrão, trade-off) ou quando eu pedir um ADR.
---

# Registrar uma decisão de arquitetura (ADR)

1. **Numerar:** veja o maior número em `docs/adr/` e use o próximo, com 4 dígitos
   (`0001`, `0002`...). Se a pasta não existir, crie-a e comece em `0001`.
2. **Nomear:** `docs/adr/NNNN-titulo-em-kebab-case.md`, com o título curto da decisão.
3. **Escrever** no formato abaixo, em português, com no máximo uma página:

```markdown
# NNNN. Título da decisão

- **Status:** proposta | aceita | substituída por NNNN
- **Data:** AAAA-MM-DD

## Contexto
O problema e as restrições que levaram à decisão.

## Decisão
O que foi decidido, em uma ou duas frases afirmativas.

## Alternativas consideradas
- Alternativa: por que não foi escolhida.

## Consequências
O que fica mais fácil, o que fica mais difícil e o que precisa ser acompanhado.
```

4. **Mostrar** o ADR e esperar meu OK antes de marcar como "aceita".

**Pronto quando:** o arquivo existe no formato acima, com contexto, decisão, ao menos
uma alternativa e as consequências.
