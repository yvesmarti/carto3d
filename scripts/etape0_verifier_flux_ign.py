#!/usr/bin/env python3
"""Étape 0 — vérification des flux WMTS IGN (Géoplateforme) avant d'écrire l'application.

Ce que fait le script (bibliothèque standard Python uniquement, rien à installer) :
  1. lit le GetCapabilities WMTS et affiche, pour la couche de relief et la couche
     d'orthophoto : nom exact, formats, style, TileMatrixSet, niveaux min/max, taille de tuile ;
  2. télécharge une tuile de relief au-dessus de NCPA (Cabourg, terre + mer), la décode
     en float32 little-endian, affiche min/max/moyenne et cherche la valeur « pas de donnée » ;
  3. compare le découpage WGS84G au GeographicTilingScheme de Cesium (niveau 0 = 2 × 1) ;
  4. vérifie l'en-tête CORS renvoyé quand la requête annonce venir de http://localhost:8000.

Usage :  python scripts/etape0_verifier_flux_ign.py [dossier_de_sortie]
Les tuiles téléchargées et un aperçu PNG du relief sont écrits dans le dossier de sortie
(par défaut : ./etape0_sorties).
"""

import math
import os
import struct
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from collections import Counter

WMTS = "https://data.geopf.fr/wmts"
COUCHE_RELIEF = "ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES"
COUCHE_ORTHO = "ORTHOIMAGERY.ORTHOPHOTOS"
ORIGINE_LOCALE = "http://localhost:8000"

# Point test : front de mer de Cabourg (une tuile qui contient à la fois terre et mer).
POINT_TEST = {"lon": -0.1170, "lat": 49.2880}

NS = {"wmts": "http://www.opengis.net/wmts/1.0", "ows": "http://www.opengis.net/ows/1.1"}

# Constantes de la norme WMTS : taille de pixel « standard » (0,28 mm) et mètres par degré.
PIXEL_STANDARD_M = 0.00028
METRES_PAR_DEGRE = 2 * math.pi * 6378137 / 360


def telecharger(url, origine=None):
    """Renvoie (statut, en-têtes, contenu). Ajoute un en-tête Origin pour tester le CORS."""
    entetes = {"User-Agent": "carte3d-ncpa-etape0"}
    if origine:
        entetes["Origin"] = origine
    req = urllib.request.Request(url, headers=entetes)
    try:
        with urllib.request.urlopen(req, timeout=60) as rep:
            return rep.status, dict(rep.headers), rep.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def texte(elem, chemin):
    trouve = elem.find(chemin, NS)
    return trouve.text.strip() if trouve is not None and trouve.text else None


def lire_capacites(xml_bytes):
    racine = ET.fromstring(xml_bytes)
    contenu = racine.find("wmts:Contents", NS)
    couches = {}
    for couche in contenu.findall("wmts:Layer", NS):
        ident = texte(couche, "ows:Identifier")
        liens = []
        for lien in couche.findall("wmts:TileMatrixSetLink", NS):
            limites = []
            for lim in lien.findall("wmts:TileMatrixSetLimits/wmts:TileMatrixLimits", NS):
                limites.append({k: texte(lim, f"wmts:{k}") for k in
                                ("TileMatrix", "MinTileRow", "MaxTileRow", "MinTileCol", "MaxTileCol")})
            liens.append({"tms": texte(lien, "wmts:TileMatrixSet"), "limites": limites})
        couches[ident] = {
            "titre": texte(couche, "ows:Title"),
            "formats": [f.text for f in couche.findall("wmts:Format", NS)],
            "styles": [texte(s, "ows:Identifier") for s in couche.findall("wmts:Style", NS)],
            "bbox": (texte(couche, "ows:WGS84BoundingBox/ows:LowerCorner"),
                     texte(couche, "ows:WGS84BoundingBox/ows:UpperCorner")),
            "liens": liens,
            "resource_urls": [r.attrib for r in couche.findall("wmts:ResourceURL", NS)],
        }
    jeux = {}
    for tms in contenu.findall("wmts:TileMatrixSet", NS):
        matrices = {}
        for tm in tms.findall("wmts:TileMatrix", NS):
            matrices[texte(tm, "ows:Identifier")] = {
                "echelle": float(texte(tm, "wmts:ScaleDenominator")),
                "coin": [float(v) for v in texte(tm, "wmts:TopLeftCorner").split()],
                "tuile": (int(texte(tm, "wmts:TileWidth")), int(texte(tm, "wmts:TileHeight"))),
                "matrice": (int(texte(tm, "wmts:MatrixWidth")), int(texte(tm, "wmts:MatrixHeight"))),
            }
        jeux[texte(tms, "ows:Identifier")] = {"crs": texte(tms, "ows:SupportedCRS"), "matrices": matrices}
    return couches, jeux


def afficher_couche(nom, couches, jeux):
    print(f"\n=== Couche {nom} ===")
    if nom not in couches:
        proches = [c for c in couches if c.split(".")[0] == nom.split(".")[0]]
        print("  ABSENTE du GetCapabilities. Couches de la même famille :", proches[:30])
        return None
    c = couches[nom]
    print("  Titre      :", c["titre"])
    print("  Formats    :", c["formats"])
    print("  Styles     :", c["styles"])
    print("  Emprise    :", c["bbox"])
    for lien in c["liens"]:
        niveaux = [l["TileMatrix"] for l in lien["limites"]]
        print(f"  TileMatrixSet {lien['tms']} : niveaux {niveaux[0] if niveaux else '?'}"
              f" → {niveaux[-1] if niveaux else '?'} ({len(niveaux)} niveaux)")
        jeu = jeux.get(lien["tms"])
        if jeu and niveaux:
            tailles = {jeu["matrices"][n]["tuile"] for n in niveaux if n in jeu["matrices"]}
            print("    Taille des tuiles (px) :", tailles, "| SRS :", jeu["crs"])
    return c


def comparer_wgs84g(jeu):
    """Compare WGS84G au GeographicTilingScheme de Cesium : niveau n = 2^(n+1) × 2^n tuiles de 180/2^n degrés."""
    print("\n=== WGS84G vs GeographicTilingScheme de Cesium ===")
    print("  SRS :", jeu["crs"])
    ecarts = []
    for ident, m in sorted(jeu["matrices"].items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        largeur_deg = m["echelle"] * PIXEL_STANDARD_M * m["tuile"][0] / METRES_PAR_DEGRE
        if ident.isdigit():
            n = int(ident)
            attendu_deg = 180 / 2 ** n
            attendu_mat = (2 ** (n + 1), 2 ** n)
            ok = abs(largeur_deg - attendu_deg) / attendu_deg < 1e-6 and m["matrice"] == attendu_mat
            if not ok:
                ecarts.append(ident)
        else:
            ok = None
        if ident in ("0", "1", "2") or not ok or ident.isdigit() and int(ident) % 4 == 0:
            print(f"  niveau {ident:>3} : matrice {m['matrice']}, tuile {m['tuile']} px, "
                  f"{largeur_deg:.10f}° par tuile, coin {m['coin']}"
                  + ("" if ok is None else ("  ✔ conforme" if ok else "  ✘ DIFFÉRENT")))
    print("  Niveaux non conformes :", ecarts or "aucun")
    return jeu


def tuile_contenant(jeu, niveau, lon, lat):
    m = jeu["matrices"][str(niveau)]
    largeur_deg = m["echelle"] * PIXEL_STANDARD_M * m["tuile"][0] / METRES_PAR_DEGRE
    # En EPSG:4326, l'ordre des axes du coin est (latitude, longitude) : on détecte le cas.
    a, b = m["coin"]
    lat0, lon0 = (a, b) if abs(a) == 90 else (b, a)
    return int((lon - lon0) // largeur_deg), int((lat0 - lat) // largeur_deg), largeur_deg, (lon0, lat0)


def url_gettile(couche, style, tms, niveau, ligne, col, fmt):
    params = {"SERVICE": "WMTS", "REQUEST": "GetTile", "VERSION": "1.0.0", "LAYER": couche,
              "STYLE": style, "TILEMATRIXSET": tms, "TILEMATRIX": str(niveau),
              "TILEROW": str(ligne), "TILECOL": str(col), "FORMAT": fmt}
    return WMTS + "?" + urllib.parse.urlencode(params)


def ecrire_png_gris(chemin, largeur, hauteur, octets):
    """Petit écrivain PNG (niveaux de gris 8 bits) pour visualiser la tuile sans bibliothèque."""
    def bloc(type_, donnees):
        return (struct.pack(">I", len(donnees)) + type_ + donnees
                + struct.pack(">I", zlib.crc32(type_ + donnees) & 0xFFFFFFFF))
    brut = b"".join(b"\x00" + bytes(octets[y * largeur:(y + 1) * largeur]) for y in range(hauteur))
    with open(chemin, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, hauteur, 8, 0, 0, 0, 0))
                + bloc(b"IDAT", zlib.compress(brut, 9)) + bloc(b"IEND", b""))


def analyser_tuile_relief(contenu, largeur, hauteur, sortie, suffixe):
    n = largeur * hauteur
    print(f"  Taille reçue : {len(contenu)} octets (attendu pour {largeur}×{hauteur} float32 : {n * 4})")
    if len(contenu) != n * 4:
        print("  Début du contenu :", contenu[:300])
        return None
    for ordre, libelle in (("<", "little-endian"), (">", "big-endian")):
        valeurs = struct.unpack(f"{ordre}{n}f", contenu)
        frequentes = Counter(round(v, 3) for v in valeurs).most_common(5)
        suspectes = Counter(v for v in valeurs if not math.isfinite(v) or v < -100 or v > 5000)
        valides = [v for v in valeurs if math.isfinite(v) and -100 <= v <= 5000]
        print(f"  Lecture {libelle} :")
        if valides:
            print(f"    valeurs plausibles : {len(valides)}/{n}, min {min(valides):.2f} m, "
                  f"max {max(valides):.2f} m, moyenne {sum(valides) / len(valides):.2f} m")
        print(f"    valeurs aberrantes (candidates « pas de donnée ») : {dict(suspectes.most_common(5))}")
        print(f"    valeurs les plus fréquentes : {frequentes}")
        if ordre == "<":
            retenues = valeurs
    # Aperçu : noir = pas de donnée / mer, blanc = point le plus haut.
    valides = [v for v in retenues if math.isfinite(v) and -100 <= v <= 5000]
    if valides:
        bas, haut = min(valides), max(valides)
        gris = [0 if not (math.isfinite(v) and -100 <= v <= 5000)
                else int(30 + 225 * (v - bas) / max(haut - bas, 1e-6)) for v in retenues]
        chemin = os.path.join(sortie, f"apercu_relief_{suffixe}.png")
        ecrire_png_gris(chemin, largeur, hauteur, gris)
        print("  Aperçu écrit :", chemin)
    return retenues


def main():
    sortie = sys.argv[1] if len(sys.argv) > 1 else "etape0_sorties"
    os.makedirs(sortie, exist_ok=True)

    print("Lecture du GetCapabilities…")
    statut, entetes, xml_bytes = telecharger(WMTS + "?SERVICE=WMTS&REQUEST=GetCapabilities")
    print(f"  HTTP {statut}, {len(xml_bytes)} octets, Content-Type {entetes.get('Content-Type')}")
    with open(os.path.join(sortie, "getcapabilities.xml"), "wb") as f:
        f.write(xml_bytes)
    couches, jeux = lire_capacites(xml_bytes)
    print(f"  {len(couches)} couches, TileMatrixSets : {sorted(jeux)}")

    relief = afficher_couche(COUCHE_RELIEF, couches, jeux)
    ortho = afficher_couche(COUCHE_ORTHO, couches, jeux)

    if "WGS84G" in jeux:
        comparer_wgs84g(jeux["WGS84G"])

    # --- Tuiles de relief au-dessus de NCPA ---
    if relief:
        lien = next((l for l in relief["liens"] if l["tms"] == "WGS84G"), relief["liens"][0])
        jeu = jeux[lien["tms"]]
        niveaux = [int(l["TileMatrix"]) for l in lien["limites"]]
        fmt = next((f for f in relief["formats"] if "bil" in f), relief["formats"][0])
        style = relief["styles"][0] if relief["styles"] else "normal"
        for niveau in sorted({min(max(niveaux), 11), max(niveaux)}):
            col, ligne, largeur_deg, origine = tuile_contenant(jeu, niveau, POINT_TEST["lon"], POINT_TEST["lat"])
            ouest = origine[0] + col * largeur_deg
            nord = origine[1] - ligne * largeur_deg
            print(f"\n=== Tuile de relief niveau {niveau} (col {col}, ligne {ligne}) ===")
            print(f"  Emprise : lon {ouest:.5f} → {ouest + largeur_deg:.5f}, lat {nord - largeur_deg:.5f} → {nord:.5f}")
            url = url_gettile(COUCHE_RELIEF, style, lien["tms"], niveau, ligne, col, fmt)
            print("  URL :", url)
            statut, entetes, contenu = telecharger(url, ORIGINE_LOCALE)
            print(f"  HTTP {statut}, Content-Type {entetes.get('Content-Type')}")
            print(f"  CORS : Access-Control-Allow-Origin = {entetes.get('Access-Control-Allow-Origin')}")
            with open(os.path.join(sortie, f"relief_z{niveau}_{col}_{ligne}.bil"), "wb") as f:
                f.write(contenu)
            w, h = jeu["matrices"][str(niveau)]["tuile"]
            analyser_tuile_relief(contenu, w, h, sortie, f"z{niveau}")

    # --- Tuile d'orthophoto au-dessus de Cabourg (TileMatrixSet PM = Web Mercator) ---
    if ortho:
        lien = next((l for l in ortho["liens"] if l["tms"] == "PM"), ortho["liens"][0])
        niveau = 15
        n = 2 ** niveau
        col = int((POINT_TEST["lon"] + 180) / 360 * n)
        lat_r = math.radians(POINT_TEST["lat"])
        ligne = int((1 - math.asinh(math.tan(lat_r)) / math.pi) / 2 * n)
        fmt = "image/jpeg" if "image/jpeg" in ortho["formats"] else ortho["formats"][0]
        style = ortho["styles"][0] if ortho["styles"] else "normal"
        url = url_gettile(COUCHE_ORTHO, style, lien["tms"], niveau, ligne, col, fmt)
        print(f"\n=== Tuile d'orthophoto niveau {niveau} (col {col}, ligne {ligne}) ===")
        print("  URL :", url)
        statut, entetes, contenu = telecharger(url, ORIGINE_LOCALE)
        est_jpeg = contenu[:3] == b"\xff\xd8\xff"
        print(f"  HTTP {statut}, Content-Type {entetes.get('Content-Type')}, {len(contenu)} octets,"
              f" JPEG valide : {est_jpeg}")
        print(f"  CORS : Access-Control-Allow-Origin = {entetes.get('Access-Control-Allow-Origin')}")
        with open(os.path.join(sortie, f"ortho_z{niveau}_{col}_{ligne}.jpg"), "wb") as f:
            f.write(contenu)

    print("\nTerminé. Fichiers dans :", os.path.abspath(sortie))


if __name__ == "__main__":
    main()
