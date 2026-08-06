# Triage labels

Vocabulário de etiquetas de triagem de `FredericoXX/Projeto-Final`. Esta tabela
mapeia cada função para a etiqueta real usada no repositório. As regras de
quando aplicar estão no [`AGENTS.md`](../../AGENTS.md).

| Função | Label |
| --- | --- |
| Aguardar triagem | `needs-triage` |
| Aguardar informação | `needs-info` |
| Pronto para agente | `ready-for-agent` |
| Aguardar decisão humana | `ready-for-human` |
| Fora do âmbito | `wontfix` |

Quando um pedido mencionar uma função (por exemplo, "aplicar a etiqueta de pronto
para agente"), usar a etiqueta correspondente desta tabela.

## Regras

- `ready-for-agent` é aplicada **apenas depois** da aprovação humana da spec ou
  dos tickets, nunca no mesmo passo em que o conteúdo é apresentado.
- Estas cinco são as únicas etiquetas de triagem. Não existem etiquetas com
  prefixos próprios de ferramentas.
- Nenhum agente cria nem modifica etiquetas no GitHub sem autorização explícita
  do utilizador. Se uma etiqueta necessária não existir, apresentar o comando e
  esperar.

## Criar as etiquetas em falta

Verificar o que existe:

```powershell
gh label list -R FredericoXX/Projeto-Final --limit 100
```

Criar uma etiqueta em falta (só depois de o utilizador autorizar):

```powershell
gh label create needs-triage `
  -R FredericoXX/Projeto-Final `
  --description "Precisa de avaliação do responsável" `
  --color "D93F0B"
```

```powershell
gh label create needs-info `
  -R FredericoXX/Projeto-Final `
  --description "À espera de mais informação" `
  --color "FBCA04"
```

```powershell
gh label create ready-for-human `
  -R FredericoXX/Projeto-Final `
  --description "Requer implementação ou decisão humana" `
  --color "1D76DB"
```
