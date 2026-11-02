#!/usr/bin/env python3
"""Monta o aviso diário (issue do GitHub, que o GitHub envia por e-mail).

Uso: python dou_monitor_aviso.py AAAA-MM-DD dono pasta_saida
Grava em pasta_saida: titulo.txt, parte1.md, parte2.md, ...
(parte1 vira o corpo da issue; as demais, comentários). Sai com código 1 se não houver nada a enviar.
"""
import json
import re
import sys
from pathlib import Path

LIMITE = 60000  # o GitHub aceita até 65.536 caracteres por issue/comentário

data, dono, pasta = sys.argv[1], sys.argv[2], Path(sys.argv[3])
arq = Path(__file__).resolve().parent / "resultados" / f"{data}.json"
if not arq.exists():
    sys.exit(1)
r = json.loads(arq.read_text(encoding="utf-8"))
if r["status"] == "sem_edicao" or (r["total_ocorrencias"] == 0 and not r.get("mensagem")):
    sys.exit(1)  # sem edição (feriado/fim de semana) ou nada encontrado: não envia


def num_secao(o):
    m = re.search(r"Seção (\d)", o.get("secao", ""))
    return m.group(1) if m else "9"


ocs = sorted(r["ocorrencias"], key=lambda o: (num_secao(o), "Extra" in o.get("secao", "")))
por_secao = {}
for o in ocs:
    por_secao.setdefault(num_secao(o), []).append(o)
NOMES = {"1": "Seção 1 – Atos normativos", "2": "Seção 2 – Atos de pessoal",
         "3": "Seção 3 – Contratos, licitações e editais", "9": "Outros"}

resumo = " · ".join(f"Seção {s}: {len(v)}" for s, v in por_secao.items() if s != "9")
cabecalho = [f"@{dono} relatório do Monitor DOU de **{r['data_br']}**: "
             f"{r['total_ocorrencias']} ocorrência(s) ({resumo}).",
             f"Palavras: {', '.join(r['palavras'])}.", ""]
if r.get("mensagem"):
    cabecalho += [f"⚠️ **Atenção:** {r['mensagem']}", ""]

blocos = []
for s, itens in por_secao.items():
    blocos.append(f"## {NOMES.get(s, s)} ({len(itens)})\n")
    detalhado = s == "1"  # Seção 1 com trechos; Seções 2 e 3 em formato compacto
    for o in itens:
        extra = " (extra)" if "Extra" in o.get("secao", "") else ""
        link = o.get("link") or o.get("link_pdf") or ""
        if detalhado:
            b = [f"**{o['titulo']}**{extra} · p. {o['pagina']}",
                 f"{o['orgao']} · palavras: {', '.join(o['palavras'])}"]
            if o["trechos"]:
                b.append(f"> {o['trechos'][0][:350]}")
            b.append(f"🔗 {link}\n")
        else:
            orgao = o["orgao"].split("/")[-1] if o["orgao"] else ""
            trecho = (o["trechos"][0][:180] if o["trechos"] else "").replace("\n", " ")
            b = [f"- **{o['titulo']}**{extra} — {orgao} · {', '.join(o['palavras'])}",
                 f"  {trecho}",
                 f"  🔗 {link}"]
        blocos.append("\n".join(b) + "\n")

partes, atual = [], "\n".join(cabecalho)
for b in blocos:
    if len(atual) + len(b) > LIMITE:
        partes.append(atual)
        atual = ""
    atual += "\n" + b
partes.append(atual)

pasta.mkdir(parents=True, exist_ok=True)
titulo = f"DOU {r['data_br']} – {r['total_ocorrencias']} ocorrência(s)"
(pasta / "titulo.txt").write_text(titulo, encoding="utf-8")
total = len(partes)
for i, p in enumerate(partes, 1):
    rotulo = f"\n\n_(parte {i} de {total})_" if total > 1 else ""
    (pasta / f"parte{i}.md").write_text(p + rotulo, encoding="utf-8")
print(f"{titulo}: {total} parte(s)")
