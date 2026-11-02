# Monitor DOU

Todo dia útil, ao meio-dia (horário de Brasília), o GitHub Actions procura as palavras de `palavras.txt` no Diário Oficial da União do dia, em todas as seções e edições extras. O resultado fica em `resultados/AAAA-MM-DD.md` e `.json`.

Às 13h49, a tarefa agendada do Claude lê esse resultado, escreve um resumo de cada ato e envia por e-mail e notificação.

## Duas fontes, escolhidas automaticamente

| Fonte | Precisa de conta? | Como funciona |
|---|---|---|
| **Busca do site do DOU** (padrão) | Não | Usa a mesma busca pública de in.gov.br, uma consulta por palavra, e depois abre cada ato encontrado para pegar o texto e o link oficial. |
| **INLABS** (opcional) | Sim, gratuita | Baixa a edição completa em XML, o serviço oficial da Imprensa Nacional para downloads automáticos. Se cair, o script volta sozinho para a busca do site. |

Se os segredos do INLABS não estiverem cadastrados, o script usa a busca do site. Quando eles estiverem cadastrados, passa a usar o INLABS.

## Configuração

1. **Crie um repositório no GitHub** (pode ser público: só guarda o código e os resultados do DOU, que são públicos) e envie estes arquivos.
2. **Teste:** na aba *Actions*, abra **Monitor DOU** e clique em *Run workflow*. Em cerca de 1 a 2 minutos, um arquivo novo aparece em `resultados/`.
3. **(Opcional, quando o INLABS voltar)** Crie sua conta em https://inlabs.in.gov.br e cadastre, em *Settings → Secrets and variables → Actions → New repository secret*:
   - `INLABS_EMAIL`
   - `INLABS_SENHA`

## Mudar as palavras

Edite `palavras.txt` direto no GitHub (ícone de lápis). Cada linha é uma palavra ou expressão, e você pode listar variações na mesma linha, separadas por vírgula. Na busca do site, cada variação vira uma consulta, então evite listas muito longas.

## Rodar no seu computador (opcional)

```
pip install requests
python dou_monitor.py                 # hoje, busca do site
python dou_monitor.py 2026-10-29      # outra data
python dou_monitor.py --modo inlabs   # força INLABS (precisa de INLABS_EMAIL e INLABS_SENHA)
```
