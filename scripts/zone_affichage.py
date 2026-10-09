#!/usr/bin/env python3
"""Zone d'affichage de la carte 3D : contour de NCPA élargi d'une marge (10 km par défaut).

L'application n'affiche et ne télécharge le relief et l'orthophoto qu'à l'intérieur de cette zone.

Lit data/epci.geojson (produit par etape1_communes.py) et écrit data/zone.geojson :
  - zone tampon calculée en Lambert-93 (EPSG:2154), donc en vrais mètres ;
  - contour simplifié à 50 m près (une centaine de sommets suffit pour découper l'affichage) ;
  - coordonnées en EPSG:4326 à 6 décimales.

Prérequis : python -m pip install -r scripts/requirements.txt  (shapely, pyproj)
Usage, depuis la racine du projet :
    python scripts/zone_affichage.py [--marge-km 10]
"""

import argparse
import json
import os

import shapely
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.geometry.polygon import orient

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOLERANCE_M = 50


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--marge-km", type=float, default=10, help="largeur de la marge autour de NCPA (km)")
    args = parser.parse_args()

    with open(os.path.join(RACINE, "data", "epci.geojson"), encoding="utf-8") as f:
        epci = shape(json.load(f)["features"][0]["geometry"])

    vers_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    vers_wgs84 = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
    projeter = lambda geom, t: shapely.transform(geom, lambda xy: list(zip(*t.transform(*xy.T))))  # noqa: E731

    zone = projeter(epci, vers_l93).buffer(args.marge_km * 1000, quad_segs=16).simplify(TOLERANCE_M)
    surface_km2 = zone.area / 1e6
    zone = orient(projeter(zone, vers_wgs84), 1.0)          # anneau extérieur anti-horaire (RFC 7946)

    geom = mapping(zone)
    geom["coordinates"] = [[[round(x, 6), round(y, 6)] for x, y in anneau] for anneau in geom["coordinates"]]
    chemin = os.path.join(RACINE, "data", "zone.geojson")
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"marge_km": args.marge_km}, "geometry": geom}]},
            f, ensure_ascii=False, separators=(",", ":"))
    print(f"data/zone.geojson : NCPA + {args.marge_km:g} km, {surface_km2:.0f} km², "
          f"{len(zone.exterior.coords)} sommets, emprise {[round(v, 4) for v in zone.bounds]}")


if __name__ == "__main__":
    main()
