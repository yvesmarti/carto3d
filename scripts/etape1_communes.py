#!/usr/bin/env python3
"""Étape 1 — préparation des données communales de NCPA.

Produit, à partir de l'API officielle Découpage administratif (geo.api.gouv.fr) :
  data/communes.geojson : les 38 communes, EPSG:4326, champs `insee` et `nom` uniquement ;
  data/epci.geojson     : le contour de NCPA, obtenu par fusion des communes.

Source des contours : jeu Etalab « contours administratifs », lui-même issu d'ADMIN EXPRESS (IGN),
déjà généralisé par Etalab. Ils sont donc gardés tels quels : seules les coordonnées sont arrondies
à 6 décimales (≈ 10 cm). L'option --tolerance permet malgré tout de simplifier davantage, en
conservant des limites communes identiques entre communes voisines.

Prérequis : Python 3.9+ et la bibliothèque shapely (version 2.1 ou plus) :
    python -m pip install -r scripts/requirements.txt
Usage, depuis la racine du projet :
    python scripts/etape1_communes.py [--tolerance 0.00005]
"""

import argparse
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import shapely
from shapely.geometry import mapping, shape
from shapely.geometry.polygon import orient

API = "https://geo.api.gouv.fr"
NOM_EPCI = "Normandie-Cabourg-Pays d'Auge"
NB_COMMUNES_ATTENDU = 38
DECIMALES = 6
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lire_json(chemin, **params):
    """Interroge l'API (avec quelques nouvelles tentatives en cas de coupure réseau)."""
    url = f"{API}{chemin}?{urllib.parse.urlencode(params)}"
    for tentative in range(8):
        try:
            with urllib.request.urlopen(url, timeout=60) as rep:
                return json.load(rep)
        except (urllib.error.URLError, ConnectionError, TimeoutError) as err:
            if tentative == 7:
                sys.exit(f"Échec de la requête {url} : {err}")
            time.sleep(1 + tentative)


def cle_tri(nom):
    """Tri alphabétique à la française (accents ignorés)."""
    return unicodedata.normalize("NFD", nom).encode("ascii", "ignore").decode().lower()


def arrondir(geom):
    """GeoJSON avec anneaux orientés selon la norme RFC 7946 et coordonnées à 6 décimales."""
    if geom.geom_type == "Polygon":
        geom = orient(geom, 1.0)
    else:
        geom = shapely.MultiPolygon([orient(p, 1.0) for p in geom.geoms])

    def r(c):
        return [round(c[0], DECIMALES), round(c[1], DECIMALES)] if isinstance(c[0], float) else [r(x) for x in c]

    gj = mapping(geom)
    return {"type": gj["type"], "coordinates": r(gj["coordinates"])}


def ecrire(chemin, entites):
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": entites}, f,
                  ensure_ascii=False, separators=(",", ":"))
    print(f"  {os.path.relpath(chemin, RACINE)} : {os.path.getsize(chemin) / 1024:.0f} Ko")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tolerance", type=float, default=0,
                        help="tolérance de simplification en degrés (0 = aucune, défaut)")
    args = parser.parse_args()

    # 1. Trouver l'EPCI par son nom
    epcis = lire_json("/epcis", nom=NOM_EPCI, fields="nom,code")
    epci = next((e for e in epcis if NOM_EPCI.lower() in e["nom"].lower()), None)
    if not epci:
        sys.exit(f"EPCI introuvable. Réponses de l'API : {epcis}")
    print(f"EPCI : {epci['nom']} (SIREN {epci['code']})")

    # 2. Ses communes, avec leur contour
    reponse = lire_json(f"/epcis/{epci['code']}/communes", fields="nom,code",
                        format="geojson", geometry="contour")
    entites = sorted(reponse["features"], key=lambda f: cle_tri(f["properties"]["nom"]))

    # 3. Contrôle obligatoire : exactement 38 communes, sinon on s'arrête et on montre la liste
    if len(entites) != NB_COMMUNES_ATTENDU:
        for f in entites:
            print(f"  {f['properties']['code']}  {f['properties']['nom']}")
        sys.exit(f"ARRÊT : {len(entites)} communes reçues au lieu de {NB_COMMUNES_ATTENDU}.")
    print(f"Contrôle : {len(entites)} communes ✔")

    geometries = [shape(f["geometry"]) for f in entites]
    if not all(g.is_valid for g in geometries):
        sys.exit("ARRÊT : géométrie invalide dans les données reçues.")
    # « Couverture valide » = les communes voisines partagent exactement leurs limites,
    # sans trou ni chevauchement (indispensable pour une fusion propre).
    print("Couverture sans trou ni chevauchement :", shapely.coverage_is_valid(geometries))

    if args.tolerance > 0:
        # Simplification « de couverture » : une limite commune est simplifiée une seule fois,
        # de la même façon pour les deux communes qui la partagent.
        geometries = list(shapely.coverage_simplify(geometries, args.tolerance))
        print(f"Simplification appliquée (tolérance {args.tolerance}°)")

    # 4. Écriture des communes (insee + nom uniquement)
    os.makedirs(os.path.join(RACINE, "data"), exist_ok=True)
    print("Fichiers écrits :")
    ecrire(os.path.join(RACINE, "data", "communes.geojson"), [
        {"type": "Feature",
         "properties": {"insee": f["properties"]["code"], "nom": f["properties"]["nom"]},
         "geometry": arrondir(g)}
        for f, g in zip(entites, geometries)])

    # 5. Contour de NCPA par fusion des communes
    fusion = shapely.union_all(geometries)
    ecrire(os.path.join(RACINE, "data", "epci.geojson"), [
        {"type": "Feature", "properties": {"siren": epci["code"], "nom": epci["nom"]},
         "geometry": arrondir(fusion)}])
    trous = len(fusion.interiors) if fusion.geom_type == "Polygon" else "?"
    print(f"Fusion : {fusion.geom_type}, {trous} trou(s)")


if __name__ == "__main__":
    main()
