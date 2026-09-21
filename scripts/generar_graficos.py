"""Regenera el grafico de actividad del perfil y las cifras del README.

Lee la actividad real de commits desde la API de GitHub (incluidos los repos
privados), la agrupa por frente de trabajo segun frentes.json, y escribe los dos
SVG (claro y oscuro) mas el bloque de cifras del README.

Corre solo desde GitHub Actions una vez por semana. No requiere intervencion.
"""

import collections
import datetime as dt
import json
import os
import pathlib
import re
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parent.parent
TOKEN = os.environ["TOKEN_REPOS"]
CORREO = os.environ.get("CORREO_AUTOR", "frncchiappe@gmail.com")
DUENIOS = {d.strip() for d in os.environ.get("DUENIOS", "fchiapped,ntldcslr").split(",")}
ANIO = dt.date.today().year

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
         "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

COLORES = {
    "claro":  {"series": ["#2563A8", "#B0571A", "#6B3FA0"],
               "tinta": "#1F2328", "suave": "#57606A"},
    "oscuro": {"series": ["#5B93CF", "#C97F42", "#A379CE"],
               "tinta": "#E6EDF3", "suave": "#8B949E"},
}


def pedir(url):
    """Una pagina de la API, con el token de solo lectura."""
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
        "User-Agent": "perfil-fchiapped",
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read()), r.headers.get("Link", "")


def paginar(url):
    """Recorre todas las paginas siguiendo el header Link."""
    while url:
        datos, link = pedir(url)
        for item in datos:
            yield item
        siguiente = re.search(r'<([^>]+)>;\s*rel="next"', link or "")
        url = siguiente.group(1) if siguiente else None


def recolectar():
    """Commits propios del anio en curso, agrupados por mes y por frente."""
    frentes = json.loads((RAIZ / "frentes.json").read_text(encoding="utf-8"))
    por_defecto = frentes["_por_defecto"]
    orden = frentes["_orden"]

    conteo = {f: collections.Counter() for f in orden}
    repos_tocados = set()

    for repo in paginar("https://api.github.com/user/repos"
                        "?per_page=100&affiliation=owner,collaborator"):
        duenio, nombre = repo["full_name"].split("/")
        if duenio not in DUENIOS:
            continue
        frente = frentes.get(nombre, por_defecto)
        url = ("https://api.github.com/repos/" + repo["full_name"] + "/commits"
               "?per_page=100&since=" + str(ANIO) + "-01-01T00:00:00Z")
        try:
            for commit in paginar(url):
                autor = (commit.get("commit", {}).get("author") or {})
                if autor.get("email") != CORREO:
                    continue
                mes = int(autor["date"][5:7])
                conteo[frente][mes] += 1
                repos_tocados.add(repo["full_name"])
        except Exception as e:      # un repo vacio o sin permiso no corta la corrida
            print("  aviso: " + repo["full_name"] + " sin commits legibles (" + str(e) + ")")

    return orden, conteo, len(repos_tocados)


def barra(x, y, ancho, alto, r, color):
    """Barra con las dos esquinas de arriba redondeadas."""
    r = min(r, alto)
    return ('<path d="M{0} {1} L{0} {2} Q{0} {3} {4} {3} '
            'L{5} {3} Q{6} {3} {6} {2} L{6} {1} Z" fill="{7}"/>').format(
        x, y + alto, y + r, y, x + r, x + ancho - r, x + ancho, color)


def dibujar(orden, conteo, meses_activos, tema, destino):
    c = COLORES[tema]
    totales = [sum(conteo[f][m] for f in orden) for m in meses_activos]
    tope = max(totales) or 1
    n = len(meses_activos)

    # Con muchos meses las barras se angostan para que el grafico no crezca
    bw = max(28, min(106, int(520 / max(n, 1)) - 16))
    gap = max(12, int(bw * 0.35))
    x0, base, alto_max = 34, 214, 132
    ancho = max(560, x0 * 2 + n * bw + (n - 1) * gap)

    p = ['<svg xmlns="http://www.w3.org/2000/svg" width="{0}" height="292" '
         'viewBox="0 0 {0} 292" '
         'font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">'.format(ancho)]
    p.append('<text x="{0}" y="20" font-size="14" font-weight="600" fill="{1}">'
             'En qué trabajé, mes a mes ({2})</text>'.format(x0, c["tinta"], ANIO))

    for i, etiqueta in enumerate(orden):
        lx = x0 + (i % 2) * 300
        ly = 42 + (i // 2) * 19
        p.append('<rect x="{0}" y="{1}" width="10" height="10" rx="2" fill="{2}"/>'
                 .format(lx, ly - 9, c["series"][i]))
        p.append('<text x="{0}" y="{1}" font-size="12" fill="{2}">{3}</text>'
                 .format(lx + 16, ly, c["suave"], etiqueta))

    for j, mes in enumerate(meses_activos):
        x = x0 + j * (bw + gap)
        acumulado = 0
        activos = [i for i, f in enumerate(orden) if conteo[f][mes] > 0]
        if not activos:
            continue
        ultimo = activos[-1]
        for i, f in enumerate(orden):
            v = conteo[f][mes]
            if v == 0:
                continue
            h = v / tope * alto_max
            y = base - (acumulado + v) / tope * alto_max
            h_vis = max(h - 2, 2)   # 2px de aire entre segmentos
            if i == ultimo:
                p.append(barra(x, y, bw, h_vis, 4, c["series"][i]))
            else:
                p.append('<rect x="{0}" y="{1}" width="{2}" height="{3:.1f}" fill="{4}"/>'
                         .format(x, y, bw, h_vis, c["series"][i]))
            acumulado += v
        y_tope = base - acumulado / tope * alto_max
        p.append('<text x="{0}" y="{1}" font-size="14" font-weight="600" '
                 'text-anchor="middle" fill="{2}">{3}</text>'
                 .format(x + bw / 2, y_tope - 9, c["tinta"], acumulado))
        marca = " *" if mes == dt.date.today().month else ""
        p.append('<text x="{0}" y="{1}" font-size="13" text-anchor="middle" '
                 'fill="{2}">{3}{4}</text>'
                 .format(x + bw / 2, base + 20, c["suave"], MESES[mes - 1], marca))

    p.append('<line x1="{0}" y1="{1}" x2="{2}" y2="{1}" stroke="{3}" '
             'stroke-width="1" opacity="0.35"/>'
             .format(x0, base + 0.5, x0 + n * bw + (n - 1) * gap, c["suave"]))
    p.append('<text x="{0}" y="{1}" font-size="12" fill="{2}">'
             '{3} commits en {4}. * mes en curso.</text>'
             .format(x0, base + 46, c["suave"], sum(totales), ANIO))
    p.append("</svg>")
    (RAIZ / destino).write_text("\n".join(p), encoding="utf-8")


def actualizar_readme(total, repos, sello):
    """Reescribe el bloque entre marcas y refresca el parametro anti-cache."""
    ruta = RAIZ / "README.md"
    texto = ruta.read_text(encoding="utf-8")

    bloque = ("{0} commits en lo que va de {1}, repartidos en {2} repositorios. "
              "El grueso está en proyectos privados: aplicaciones en producción, "
              "pipelines de datos y análisis que se usan a diario dentro de la "
              "institución.").format(total, ANIO, repos)
    texto = re.sub(r"(?s)(<!-- cifras:inicio -->).*?(<!-- cifras:fin -->)",
                   lambda m: m.group(1) + "\n" + bloque + "\n" + m.group(2), texto)

    # El proxy de imagenes de GitHub cachea por URL: sin este parametro el
    # grafico nuevo no se ve hasta que expire la cache sola.
    texto = re.sub(r"(frentes-\d{4}-(?:claro|oscuro)\.svg)(\?v=[0-9]+)?",
                   lambda m: m.group(1) + "?v=" + sello, texto)
    ruta.write_text(texto, encoding="utf-8")


def main():
    orden, conteo, repos = recolectar()
    meses_activos = sorted({m for f in orden for m in conteo[f]})
    if not meses_activos:
        print("Sin commits en el anio, no se toca nada.")
        return
    dibujar(orden, conteo, meses_activos, "claro", "frentes-{0}-claro.svg".format(ANIO))
    dibujar(orden, conteo, meses_activos, "oscuro", "frentes-{0}-oscuro.svg".format(ANIO))
    total = sum(sum(conteo[f].values()) for f in orden)
    actualizar_readme(total, repos, dt.date.today().strftime("%Y%m%d"))
    print("Listo: {0} commits, {1} repos, meses {2}".format(total, repos, meses_activos))


if __name__ == "__main__":
    main()
