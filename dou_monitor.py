#!/usr/bin/env python3
"""Monitor DOU: baixa a edição do dia pelo INLABS (serviço oficial da Imprensa
Nacional), procura as palavras de palavras.txt e grava os resultados em
resultados/AAAA-MM-DD.json e resultados/AAAA-MM-DD.md.

Uso:
  INLABS_EMAIL=... INLABS_SENHA=... python dou_monitor.py            # hoje
  INLABS_EMAIL=... INLABS_SENHA=... python dou_monitor.py 2026-10-29 # outra data
  python dou_monitor.py --zips pasta_com_zips 2026-10-29             # teste offline
"""
import argparse
import html
import io
import json
import os
import re
import sys
import time
import unicodedata
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

BASE = Path(__file__).resolve().parent
URL_LOGIN = "https://inlabs.in.gov.br/logar.php"
URL_DOWNLOAD = "https://inlabs.in.gov.br/index.php?p="
SECOES = ["DO1", "DO2", "DO3", "DO1E", "DO2E", "DO3E"]
NOMES_SECAO = {"DO1": "Seção 1", "DO2": "Seção 2", "DO3": "Seção 3",
               "DO1E": "Seção 1 – Extra", "DO2E": "Seção 2 – Extra", "DO3E": "Seção 3 – Extra"}
BRT = timezone(timedelta(hours=-3))
LIMITE_TEXTO = 4000  # caracteres do texto do ato guardados para o resumo


def _base(c):
    d = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x)).lower()
    return d[0] if d else c


def normalizar(texto):
    """Remove acentos e põe em minúsculas, mantendo o mesmo comprimento do texto."""
    return "".join(_base(c) if ord(c) > 127 else c.lower() for c in texto)


def plurais(palavra):
    p = palavra
    formas = {p}
    if " " in p:
        return formas
    if p.endswith("cao"):
        formas.add(p[:-3] + "coes")
    elif p.endswith(("r", "z")):
        formas.add(p + "es")
    elif p.endswith("l"):
        formas.add(p[:-1] + "is")
    elif p.endswith("m"):
        formas.add(p[:-1] + "ns")
    else:
        formas.add(p + "s")
    return formas


def carregar_palavras(caminho):
    grupos = []
    for linha in Path(caminho).read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        termos = [t.strip() for t in linha.split(",") if t.strip()]
        formas = set()
        for t in termos:
            formas |= plurais(normalizar(t))
        alternativas = sorted((re.escape(f).replace(r"\ ", r"\s+") for f in formas), key=len, reverse=True)
        regex = re.compile(r"(?<!\w)(?:" + "|".join(alternativas) + r")(?!\w)")
        grupos.append({"nome": termos[0], "termos": termos, "regex": regex})
    return grupos


def limpar_html(texto):
    if not texto:
        return ""
    texto = re.sub(r"<\s*(br|/p|/tr|/li|/h\d)\s*/?>", "\n", texto, flags=re.I)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = html.unescape(texto)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    texto = re.sub(r"\n\s*", "\n", texto)
    return texto.strip()


def texto_de(no, tag):
    el = no.find(f".//{tag}")
    if el is None:
        return ""
    return limpar_html("".join(el.itertext()))


def ler_artigos(zip_bytes, secao):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for nome in z.namelist():
            if not nome.lower().endswith(".xml"):
                continue
            try:
                raiz = ET.fromstring(z.read(nome))
            except ET.ParseError:
                continue
            artigos = [raiz] if raiz.tag == "article" else raiz.iter("article")
            for art in artigos:
                a = art.attrib
                yield {
                    "secao": NOMES_SECAO.get(secao, secao),
                    "pagina": a.get("numberPage", ""),
                    "edicao": a.get("editionNumber", ""),
                    "data": a.get("pubDate", ""),
                    "tipo": a.get("artType", ""),
                    "orgao": a.get("artCategory", ""),
                    "id_materia": a.get("idMateria", ""),
                    "link_pdf": a.get("pdfPage", ""),
                    "titulo": texto_de(art, "Identifica") or a.get("name", ""),
                    "ementa": texto_de(art, "Ementa"),
                    "texto": texto_de(art, "Texto"),
                }


def link_busca(artigo, data_iso):
    d = datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d-%m-%Y")
    q = quote('"' + artigo["titulo"][:150] + '"')
    return f"https://www.in.gov.br/consulta/-/buscar/dou?q={q}&s=todos&exactDate=personalizado&publishFrom={d}&publishTo={d}"


def trechos(texto, regex, max_trechos=3, raio=160):
    norm = normalizar(texto)
    resultado = []
    for m in regex.finditer(norm):
        ini = max(0, m.start() - raio)
        fim = min(len(texto), m.end() + raio)
        trecho = texto[ini:fim].replace("\n", " ").strip()
        resultado.append(("…" if ini else "") + trecho + ("…" if fim < len(texto) else ""))
        if len(resultado) >= max_trechos:
            break
    return resultado


def baixar(data_iso, email, senha):
    import requests
    s = requests.Session()
    for tentativa in range(3):
        try:
            s.post(URL_LOGIN, data={"email": email, "password": senha},
                   headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=60)
            break
        except requests.exceptions.ConnectionError:
            time.sleep(10)
    cookie = s.cookies.get("inlabs_session_cookie")
    if not cookie:
        raise SystemExit("Falha no login do INLABS: verifique INLABS_EMAIL e INLABS_SENHA.")
    arquivos, ausentes = {}, []
    for secao in SECOES:
        url = f"{URL_DOWNLOAD}{data_iso}&dl={data_iso}-{secao}.zip"
        r = s.get(url, headers={"Cookie": "inlabs_session_cookie=" + cookie, "origem": "736372697074"}, timeout=180)
        if r.status_code == 200 and r.content[:2] == b"PK":
            arquivos[secao] = r.content
        else:
            ausentes.append(secao)
    return arquivos, ausentes


def zips_locais(pasta, data_iso):
    arquivos, ausentes = {}, []
    for secao in SECOES:
        p = Path(pasta) / f"{data_iso}-{secao}.zip"
        if p.exists():
            arquivos[secao] = p.read_bytes()
        else:
            ausentes.append(secao)
    return arquivos, ausentes


# ---------------------------------------------------------------------------
# Modo alternativo: busca pública do site do DOU (sem login)
# ---------------------------------------------------------------------------
URL_BUSCA = "https://www.in.gov.br/consulta/-/buscar/dou"
URL_ATO = "https://www.in.gov.br/web/dou/-/"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) monitor-dou-pessoal/1.0",
      "Accept-Language": "pt-BR,pt;q=0.9"}
SECAO_SITE = {"do1": "Seção 1", "do2": "Seção 2", "do3": "Seção 3",
              "do1e": "Seção 1 – Extra", "do2e": "Seção 2 – Extra", "do3e": "Seção 3 – Extra",
              "do1a": "Seção 1 – Extra A", "do1_extra_a": "Seção 1 – Extra A"}


def extrair_json_busca(pagina_html):
    """Lê a lista de resultados embutida na página de busca (script JSON com 'jsonArray')."""
    for m in re.finditer(r"<script[^>]*type=[\"']application/json[\"'][^>]*>(.*?)</script>", pagina_html, re.S | re.I):
        bruto = m.group(1).strip()
        if "jsonArray" not in bruto:
            continue
        try:
            return json.loads(bruto).get("jsonArray", [])
        except json.JSONDecodeError:
            continue
    return None


class _TextoDou(__import__("html.parser").parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.prof = 0
        self.partes = []

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "") or ""
        if self.prof:
            self.prof += 1 if tag not in ("br", "img", "hr", "input", "meta", "link") else 0
            if tag in ("p", "br", "tr", "li"):
                self.partes.append("\n")
        elif tag == "div" and "texto-dou" in classes.split():
            self.prof = 1

    def handle_endtag(self, tag):
        if self.prof and tag not in ("br", "img", "hr", "input", "meta", "link"):
            self.prof -= 1

    def handle_data(self, data):
        if self.prof:
            self.partes.append(data)


def extrair_texto_ato(pagina_html):
    p = _TextoDou()
    p.feed(pagina_html)
    texto = "".join(p.partes)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    return re.sub(r"\n\s*", "\n", texto).strip()


def nome_secao(pub):
    m = re.match(r"(?i)do(\d)(e)?(?:_extra_?([a-z]))?$", str(pub or "").strip())
    if not m:
        return str(pub or "")
    nome = f"Seção {m.group(1)}"
    if m.group(2) or m.group(3):
        nome += " – Extra" + (f" {m.group(3).upper()}" if m.group(3) else "")
    return nome


def numero_secao(pub):
    m = re.match(r"(?i)do(\d)", str(pub or "").strip())
    return m.group(1) if m else ""


def buscar_site(data_iso, grupos, termos_por_grupo, obter=None, max_atos_texto=600, secoes=None):
    """Faz uma busca por termo no site do DOU para a data e abre cada ato encontrado.
    `obter(url, params)` devolve o HTML; é substituível para testes."""
    if obter is None:
        import requests
        sess = requests.Session()
        sess.headers.update(UA)

        def obter(url, params=None):
            for tentativa in range(3):
                try:
                    r = sess.get(url, params=params, timeout=60)
                    if r.status_code == 200:
                        return r.text
                except requests.exceptions.RequestException:
                    pass
                time.sleep(5 * (tentativa + 1))
            raise RuntimeError(f"Falha ao acessar {url}")

    d_br = datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d-%m-%Y")
    d_pub = datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    achados, erros = {}, []
    for g in grupos:
        for termo in termos_por_grupo[g["nome"]]:
            params = {"q": f'"{termo}"', "s": "todos", "exactDate": "personalizado",
                      "publishFrom": d_br, "publishTo": d_br, "sortType": "0", "delta": "75"}
            for pagina in range(1, 30):
                try:
                    itens = extrair_json_busca(obter(URL_BUSCA, params))
                except RuntimeError as e:
                    erros.append(str(e))
                    break
                if itens is None:
                    erros.append(f"Formato inesperado na busca por '{termo}'.")
                    break
                novos = 0
                for it in itens:
                    if it.get("pubDate") and it["pubDate"] != d_pub:
                        continue
                    if secoes and numero_secao(it.get("pubName")) not in secoes:
                        continue
                    chave = it.get("urlTitle") or it.get("title")
                    if chave not in achados:
                        achados[chave] = {"item": it, "termos": set()}
                        novos += 1
                    achados[chave]["termos"].add(g["nome"])
                print(f"  busca '{termo}' pág. {pagina}: {len(itens)} itens")
                if len(itens) < int(params["delta"]):
                    break
                ultimo = itens[-1]
                params.update({"currentPage": str(pagina), "newPage": str(pagina + 1), "score": "0",
                               "id": str(ultimo.get("classPK", "")),
                               "displayDate": str(ultimo.get("displayDateSortable", ""))})
                time.sleep(1)
            time.sleep(1)

    ocorrencias = []
    for n, (chave, a) in enumerate(achados.items()):
        it = a["item"]
        link = URL_ATO + it["urlTitle"] if it.get("urlTitle") else ""
        resumo_busca = limpar_html(it.get("content", ""))
        texto = ""
        if link and n < max_atos_texto:
            try:
                texto = extrair_texto_ato(obter(link, None))
                time.sleep(1)
            except RuntimeError as e:
                erros.append(str(e))
        completo = "\n".join([limpar_html(it.get("title", "")), texto or resumo_busca])
        norm = normalizar(completo)
        confirmadas = [g["nome"] for g in grupos if g["regex"].search(norm)]
        if not confirmadas:
            if texto:
                continue  # a busca do site casou outra palavra parecida (ex.: "Suplementar")
            confirmadas = sorted(a["termos"])
        tr = []
        for g in grupos:
            if g["nome"] in confirmadas:
                for t in trechos(completo, g["regex"], max_trechos=2):
                    nucleo = t.strip("…")[40:-40] or t
                    if not any(nucleo in x for x in tr):
                        tr.append(t)
        ocorrencias.append({
            "secao": nome_secao(it.get("pubName")),
            "pagina": str(it.get("numberPage", "")),
            "edicao": str(it.get("editionNumber", "")),
            "tipo": it.get("artType", ""),
            "orgao": it.get("hierarchyStr", ""),
            "titulo": limpar_html(it.get("title", "")),
            "ementa": "",
            "link": link,
            "link_pdf": "",
            "id_materia": str(it.get("classPK", "")),
            "palavras": confirmadas,
            "trechos": tr[:4] or ([resumo_busca[:400]] if resumo_busca else []),
            "link_busca": "",
            "texto": (texto or resumo_busca)[:LIMITE_TEXTO],
        })
    return ocorrencias, erros


def montar_md(res):
    linhas = [f"# DOU de {res['data_br']} – {res['total_ocorrencias']} ocorrência(s)", ""]
    if res.get("mensagem"):
        linhas += [f"**Atenção:** {res['mensagem']}", ""]
    linhas.append(f"Fonte: {res.get('fonte', '')} · Seções: {', '.join(res['secoes_lidas']) or 'nenhuma'} · Atos analisados: {res['atos_analisados']}")
    linhas.append("")
    for m in res["ocorrencias"]:
        linhas.append(f"## {m['titulo']}")
        linhas.append(f"*{m['orgao']}* · {m['secao']}, p. {m['pagina']} · palavras: {', '.join(m['palavras'])}")
        if m["ementa"]:
            linhas.append(f"> {m['ementa']}")
        for t in m["trechos"]:
            linhas.append(f"- {t}")
        links = []
        if m.get("link"):
            links.append(f"[Ato no site do DOU]({m['link']})")
        if m.get("link_pdf"):
            links.append(f"[Página no PDF]({m['link_pdf']})")
        if m.get("link_busca"):
            links.append(f"[Buscar no site do DOU]({m['link_busca']})")
        linhas.append(" · ".join(links))
        linhas.append("")
    return "\n".join(linhas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", nargs="?", help="AAAA-MM-DD (padrão: hoje, horário de Brasília)")
    ap.add_argument("--zips", help="pasta com zips já baixados (teste offline)")
    ap.add_argument("--palavras", default=str(BASE / "palavras.txt"))
    ap.add_argument("--saida", default=str(BASE / "resultados"))
    ap.add_argument("--secoes", default=os.environ.get("SECOES", "1,2,3"),
                    help="seções a incluir, ex.: 1 ou 1,3 (edições extras vêm junto)")
    ap.add_argument("--modo", choices=["auto", "inlabs", "site"], default="auto",
                    help="auto: INLABS se houver credenciais, senão a busca do site do DOU")
    args = ap.parse_args()

    data_iso = args.data or datetime.now(BRT).strftime("%Y-%m-%d")
    grupos = carregar_palavras(args.palavras)
    secoes = {x.strip() for x in str(args.secoes).split(",") if x.strip()}

    fonte, avisos = "INLABS", []
    arquivos, ausentes = {}, []
    if args.zips:
        arquivos, ausentes = zips_locais(args.zips, data_iso)
    elif args.modo != "site":
        email, senha = os.environ.get("INLABS_EMAIL"), os.environ.get("INLABS_SENHA")
        if email and senha:
            try:
                arquivos, ausentes = baixar(data_iso, email, senha)
            except BaseException as e:  # login falhou, INLABS fora do ar etc.
                avisos.append(f"INLABS indisponível ({e}); usando a busca do site do DOU.")
        elif args.modo == "inlabs":
            raise SystemExit("Defina INLABS_EMAIL e INLABS_SENHA.")
        if not arquivos and args.modo == "auto":
            fonte = "site"

    if args.modo == "site":
        fonte = "site"

    if fonte == "site":
        termos = {g["nome"]: g["termos"] for g in grupos}
        ocorrencias, erros = buscar_site(data_iso, grupos, termos, secoes=secoes)
        avisos += erros
        ok = not erros or ocorrencias
        res = {
            "data": data_iso,
            "data_br": datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y"),
            "gerado_em": datetime.now(BRT).isoformat(timespec="seconds"),
            "fonte": "Busca pública do site do DOU (in.gov.br)",
            "status": "ok" if ok else "erro",
            "mensagem": " ".join(avisos),
            "palavras": [g["nome"] for g in grupos],
            "secoes_lidas": [f"Seção {x} (com extras)" for x in sorted(secoes)],
            "secoes_ausentes": [],
            "atos_analisados": len(ocorrencias),
            "total_ocorrencias": len(ocorrencias),
            "ocorrencias": ocorrencias,
        }
        salvar(res, args.saida, data_iso)
        print(f"{data_iso} (site): {len(ocorrencias)} ocorrência(s). Avisos: {res['mensagem'] or 'nenhum'}")
        return

    ocorrencias, total_atos = [], 0
    for secao, conteudo in arquivos.items():
        if numero_secao(secao) not in secoes:
            continue
        for art in ler_artigos(conteudo, secao):
            total_atos += 1
            completo = "\n".join([art["titulo"], art["ementa"], art["texto"]])
            norm = normalizar(completo)
            achadas = [g for g in grupos if g["regex"].search(norm)]
            if not achadas:
                continue
            tr = []
            for g in achadas:
                for t in trechos(completo, g["regex"], max_trechos=2):
                    nucleo = t.strip("…")[40:-40] or t
                    if not any(nucleo in x for x in tr):
                        tr.append(t)
            ocorrencias.append({
                **{k: art[k] for k in ("secao", "pagina", "edicao", "tipo", "orgao", "titulo", "ementa", "link_pdf", "id_materia")},
                "palavras": [g["nome"] for g in achadas],
                "trechos": tr[:4],
                "link_busca": link_busca(art, data_iso),
                "texto": art["texto"][:LIMITE_TEXTO],
            })

    if not arquivos:
        status, msg = "sem_edicao", "Nenhuma seção disponível no INLABS para esta data (fim de semana, feriado ou edição ainda não publicada)."
    else:
        status, msg = "ok", ""
    for o in ocorrencias:
        o["link"] = ""

    res = {
        "data": data_iso,
        "data_br": datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y"),
        "gerado_em": datetime.now(BRT).isoformat(timespec="seconds"),
        "fonte": "INLABS (XML oficial da Imprensa Nacional)",
        "status": status,
        "mensagem": " ".join(avisos + ([msg] if msg else [])),
        "palavras": [g["nome"] for g in grupos],
        "secoes_lidas": [NOMES_SECAO[s] for s in arquivos],
        "secoes_ausentes": ausentes,
        "atos_analisados": total_atos,
        "total_ocorrencias": len(ocorrencias),
        "ocorrencias": ocorrencias,
    }
    salvar(res, args.saida, data_iso)
    print(f"{data_iso}: {total_atos} atos lidos, {len(ocorrencias)} ocorrência(s). Status: {status}")


def salvar(res, pasta, data_iso):
    saida = Path(pasta)
    saida.mkdir(parents=True, exist_ok=True)
    (saida / f"{data_iso}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (saida / f"{data_iso}.md").write_text(montar_md(res), encoding="utf-8")


if __name__ == "__main__":
    main()
