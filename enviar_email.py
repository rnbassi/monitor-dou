#!/usr/bin/env python3
"""Envia o relatório do dia por e-mail pelo Gmail.

Configuração (segredos do repositório, nunca em arquivos):
  GMAIL_USUARIO    – endereço Gmail que envia (também recebe uma cópia)
  GMAIL_SENHA_APP  – senha de app do Google (16 letras)
  DESTINATARIOS    – outros e-mails, separados por vírgula

Uso: python enviar_email.py AAAA-MM-DD
Códigos de saída: 0 enviado · 1 nada a enviar · 2 Gmail não configurado · 3 falha no envio
"""
import html
import json
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

NOMES = {"1": "Seção 1 – Atos normativos", "2": "Seção 2 – Atos de pessoal",
         "3": "Seção 3 – Contratos, licitações e editais", "9": "Outros"}


def num_secao(o):
    m = re.search(r"Seção (\d)", o.get("secao", ""))
    return m.group(1) if m else "9"


def montar(r):
    ocs = sorted(r["ocorrencias"], key=lambda o: (num_secao(o), "Extra" in o.get("secao", "")))
    grupos = {}
    for o in ocs:
        grupos.setdefault(num_secao(o), []).append(o)
    contagem = " · ".join(f"Seção {s}: {len(v)}" for s, v in grupos.items() if s != "9")
    assunto = f"DOU {r['data_br']} – {r['total_ocorrencias']} ocorrência(s)"

    e = html.escape
    h = ['<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;max-width:760px">',
         f'<h2 style="margin:0 0 4px">Monitor DOU – {e(r["data_br"])}</h2>',
         f'<p style="margin:0 0 4px">{r["total_ocorrencias"]} ocorrência(s) ({e(contagem)})</p>',
         f'<p style="margin:0 0 16px;color:#666">Palavras: {e(", ".join(r["palavras"]))}</p>']
    t = [f"Monitor DOU – {r['data_br']}", f"{r['total_ocorrencias']} ocorrência(s) ({contagem})", ""]
    if r.get("mensagem"):
        h.append(f'<p style="background:#fff4e5;padding:8px"><b>Atenção:</b> {e(r["mensagem"])}</p>')
        t += [f"Atenção: {r['mensagem']}", ""]

    for s, itens in grupos.items():
        h.append(f'<h3 style="border-bottom:2px solid #1351b4;padding-bottom:4px;margin-top:24px">'
                 f'{e(NOMES.get(s, s))} ({len(itens)})</h3>')
        t += ["", f"== {NOMES.get(s, s)} ({len(itens)}) ==", ""]
        for o in itens:
            extra = " (extra)" if "Extra" in o.get("secao", "") else ""
            link = o.get("link") or o.get("link_pdf") or ""
            palavras = ", ".join(o["palavras"])
            trecho = o["trechos"][0] if o["trechos"] else ""
            if s == "1":
                trecho = trecho[:350]
                orgao = o["orgao"]
            else:
                trecho = trecho[:180]
                orgao = o["orgao"].split("/")[-1] if o["orgao"] else ""
            titulo = f'<a href="{e(link)}">{e(o["titulo"])}</a>' if link else e(o["titulo"])
            h.append('<div style="margin:0 0 14px">'
                     f'<b>{titulo}</b>{e(extra)} <span style="color:#666">· p. {e(o["pagina"])}</span><br>'
                     f'<span style="color:#444">{e(orgao)} · <i>{e(palavras)}</i></span>'
                     + (f'<div style="color:#555;font-size:13px;margin-top:3px">{e(trecho)}</div>' if trecho else "")
                     + "</div>")
            t += [f"- {o['titulo']}{extra} (p. {o['pagina']}) — {orgao} · {palavras}",
                  f"  {trecho}", f"  {link}", ""]
    h.append('<p style="color:#888;font-size:12px;margin-top:24px">Enviado automaticamente pelo Monitor DOU.</p></div>')
    return assunto, "\n".join(t), "\n".join(h)


def main():
    data = sys.argv[1]
    arq = Path(__file__).resolve().parent / "resultados" / f"{data}.json"
    if not arq.exists():
        return 1
    r = json.loads(arq.read_text(encoding="utf-8"))
    if r["status"] == "sem_edicao" or (r["total_ocorrencias"] == 0 and not r.get("mensagem")):
        return 1

    usuario = os.environ.get("GMAIL_USUARIO", "").strip()
    senha = os.environ.get("GMAIL_SENHA_APP", "").replace(" ", "").strip()
    if not usuario or not senha:
        print("Gmail não configurado; usando o aviso do GitHub.")
        return 2
    outros = [x.strip() for x in re.split(r"[,;\s]+", os.environ.get("DESTINATARIOS", "")) if x.strip()]
    destinos = [usuario] + [x for x in outros if x.lower() != usuario.lower()]

    assunto, texto, corpo_html = montar(r)
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = f"Monitor DOU <{usuario}>"
    msg["To"] = ", ".join(destinos)
    msg.set_content(texto)
    msg.add_alternative(corpo_html, subtype="html")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=60) as s:
            s.login(usuario, senha)
            s.send_message(msg)
    except Exception as ex:
        print(f"Falha ao enviar pelo Gmail: {type(ex).__name__}: {ex}")
        return 3
    print(f"E-mail enviado para {len(destinos)} destinatário(s).")  # endereços não aparecem no log público
    return 0


if __name__ == "__main__":
    sys.exit(main())
