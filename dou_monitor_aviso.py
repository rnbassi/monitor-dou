#!/usr/bin/env python3
"""Monta o texto do aviso diário (issue do GitHub, que o GitHub envia por e-mail).
Imprime: 1ª linha = título; resto = corpo. Sai com código 1 se não houver nada a enviar."""
import json
import sys
from pathlib import Path

data, dono = sys.argv[1], sys.argv[2]
arq = Path(__file__).resolve().parent / "resultados" / f"{data}.json"
if not arq.exists():
    sys.exit(1)
r = json.loads(arq.read_text(encoding="utf-8"))
if r["status"] == "sem_edicao" or (r["total_ocorrencias"] == 0 and not r.get("mensagem")):
    sys.exit(1)  # sem edição (feriado/fim de semana) ou nada encontrado: não envia

print(f"DOU {r['data_br']} – {r['total_ocorrencias']} ocorrência(s)")
linhas = [f"@{dono} relatório do Monitor DOU de **{r['data_br']}** "
          f"({', '.join(r['secoes_lidas'])}; palavras: {', '.join(r['palavras'])}).", ""]
if r.get("mensagem"):
    linhas += [f"⚠️ **Atenção:** {r['mensagem']}", ""]
for i, o in enumerate(r["ocorrencias"], 1):
    linhas.append(f"### {i}. {o['titulo']}")
    linhas.append(f"**{o['orgao']}** · {o['secao']}, p. {o['pagina']} · palavras: {', '.join(o['palavras'])}")
    for t in o["trechos"][:2]:
        linhas.append(f"> {t[:450]}")
        linhas.append("")
    if o.get("link"):
        linhas.append(f"🔗 {o['link']}")
    linhas.append("")
corpo = "\n".join(linhas)
if len(corpo) > 60000:
    corpo = corpo[:60000] + "\n\n…(relatório cortado; veja a lista completa na pasta resultados do repositório)"
print(corpo)
