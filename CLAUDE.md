# Carte 3D interactive de NCPA — Brief de projet

## Qui est l'utilisateur

- Yves, chargé de mission déchets / SIG à la Communauté de Communes Normandie-Cabourg-Pays d'Auge. Toujours écrire « NCPA » (jamais « la NCPA »).
- Bon niveau SIG (QGIS) mais pas développeur : expliquer les notions qui sembleraient évidentes à un développeur, en quelques phrases courtes. Pas de longs paragraphes.
- Répondre en français.

## Objectif

Application web 3D, hébergée en fichiers statiques (aucun serveur applicatif), pour explorer le relief des 38 communes de NCPA (Calvados).

### Fonctionnalités attendues (V1)

1. Relief réel issu de l'IGN (RGE ALTI via flux), chargé progressivement selon le zoom.
2. Orthophotographie IGN drapée sur le relief.
3. Navigation libre : zoom, rotation, inclinaison, déplacement.
4. Limites des 38 communes : surbrillance + nom au survol, panneau d'info au clic (nom, code INSEE), puis vol caméra vers la commune.
5. Bouton « Vue NCPA » : retour à la vue générale inclinée de l'EPCI.
6. Curseur d'exagération du relief (le Pays d'Auge a des reliefs modestes ; défaut ≈ 2).
7. Mention des sources visible (« © IGN – Géoplateforme »).
8. Rendu fluide et soigné sur écran d'ordinateur (pas d'optimisation mobile exigée).

## Décisions déjà prises (ne pas remettre en cause sans en parler)

- CesiumJS, chargé depuis un CDN (jsDelivr), version exacte épinglée : choisir une version stable publiée depuis plus de deux semaines.
- Aucune clé API. Ne pas utiliser Cesium Ion : désactiver les couches et services par défaut (`baseLayer: false`, `baseLayerPicker: false`, `geocoder: false`, etc.).
- Relief : flux WMTS IGN `ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES` (RGE ALTI) sur `https://data.geopf.fr/wmts`, lu par un `CustomHeightmapTerrainProvider` (module de « traduction » tuiles IGN → Cesium).
- Orthophoto : flux WMTS IGN `ORTHOIMAGERY.ORTHOPHOTOS` sur `https://data.geopf.fr/wmts` (TileMatrixSet `PM`, JPEG) via `WebMapTileServiceImageryProvider`.
- Plan B (seulement si le relief IGN s'avère inexploitable après investigation) : Cesium World Terrain avec un jeton Ion. En parler à Yves avant de basculer.

## Contexte vérifié sur les sources (octobre 2026)

- geoservices.ign.fr est fermé depuis le 26/03/2026 ; documentation désormais sur cartes.gouv.fr. Ignorer les tutoriels qui citent `wxs.ign.fr` ou geoservices.
- Le WMTS et le TMS de la Géoplateforme ne sont pas soumis au rate limiting (le WMS-Raster l'est : 40 req/s par IP).
- Données IGN sous Licence Ouverte Etalab 2.0 → mention de la source obligatoire.
- LiDAR HD (MNT 50 cm) : hors périmètre V1, piste pour une V2.

## Structure des fichiers à produire

```
carte3d-ncpa/
├── CLAUDE.md               ← ce fichier
├── index.html              ← application complète (HTML + CSS + JS dans un seul fichier)
├── data/
│   ├── communes.geojson    ← 38 communes, EPSG:4326, champs `insee` et `nom`
│   └── epci.geojson        ← contour fusionné de NCPA
├── scripts/                ← scripts de préparation des données (Python de préférence)
└── README.md               ← sources, licences, lancement local, déploiement
```

(Dans ce dépôt, `carte3d-ncpa/` correspond à la racine du dépôt `carto3d`.)

## Méthode de travail — étapes, dans cet ordre

Après chaque étape : résumé court à Yves (ce qui est fait, ce qui a été vérifié, ce qui reste incertain), puis attendre son feu vert avant l'étape suivante.

### Étape 0 — Vérifier les flux IGN AVANT d'écrire l'application

1. Lire le GetCapabilities WMTS (`https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetCapabilities`) et confirmer pour la couche de relief : nom exact, format(s) proposés (attendu : `image/x-bil;bits=32`), TileMatrixSet (attendu : `WGS84G`), niveaux min/max, taille des tuiles. Faire de même pour l'orthophoto.
2. Télécharger une tuile de relief au-dessus de NCPA, la décoder (float32 little-endian) et vérifier que les valeurs sont plausibles (de 0 à environ 200 m). Identifier la valeur « pas de donnée » (mer, hors France) : elle devra être remplacée par 0.
3. Vérifier que le découpage `WGS84G` correspond au `GeographicTilingScheme` de Cesium (niveau 0 = 2 × 1 tuiles). Sinon, établir la correspondance des niveaux.
4. Vérifier que les flux répondent bien depuis une page servie en local (en-têtes CORS).
5. Présenter les résultats à Yves. Hypothèses à confirmer, pas des faits.

### Étape 1 — Données communales

- Récupérer les communes de NCPA via l'API officielle `geo.api.gouv.fr` (trouver l'EPCI par son nom, puis ses communes avec `geometry=contour`). À défaut : ADMIN EXPRESS COG (IGN).
- Contrôle obligatoire : exactement 38 communes. Sinon, s'arrêter et montrer la liste à Yves.
- Simplifier légèrement les géométries (objectif < 1 Mo), coordonnées à 6 décimales, ne garder que `insee` et `nom`. Produire `epci.geojson` par fusion. Script reproductible dans `scripts/`.

### Étape 2 — Prototype relief seul

- Cesium + relief IGN + fond neutre. Tester l'affichage sur NCPA.
- Altitudes IGN = altitudes au-dessus du niveau de la mer (IGN69) ; Cesium attend des hauteurs ellipsoïdales → ajouter un décalage constant (ondulation du géoïde ≈ 45–50 m en Normandie), à documenter dans le code.
- Surveiller les coutures entre tuiles (les tuiles IGN ne partagent pas leurs bords). Si elles sont visibles, proposer une correction ; sinon les jupes (« skirts ») de Cesium peuvent suffire.

### Étape 3 — Orthophoto drapée

### Étape 4 — Communes

- Remplissage semi-transparent posé au sol (clampé au relief) pour permettre survol et clic.
- Contours en polylignes clampées au sol (les contours de polygones clampés ne s'affichent pas dans Cesium).
- Survol : surbrillance + infobulle (nom). Clic : panneau d'info + vol vers la commune.
- Contour de NCPA plus marqué.

### Étape 5 — Interface et finitions

- Bouton « Vue NCPA », curseur d'exagération (`scene.verticalExaggeration`), mention des sources.
- Performance : `requestRenderMode`, réglage de `maximumScreenSpaceError`, niveau max raisonnable pour le relief. Pas de chargement global des données haute résolution.
- Esthétique sobre et lisible (panneaux discrets, typographie propre).

### Étape 6 — Documentation (README.md)

- Sources exactes (noms de couches, URL des flux, licences, date de vérification).
- Confirmation qu'aucune clé API n'est nécessaire.
- Lancement local pas à pas pour un débutant (`python -m http.server` dans le dossier, puis `http://localhost:8000`) et pourquoi le double-clic sur `index.html` ne suffit pas.
- Déploiement sur un hébergement statique (copier le dossier tel quel).

## Règles impératives

- Ne jamais affirmer que quelque chose fonctionne sans l'avoir testé dans un navigateur (capture d'écran via un navigateur automatisé si disponible ; sinon demander à Yves de tester avec une liste de contrôle précise de ce qu'il doit voir).
- Distinguer clairement : vérifié / supposé / non testé.
- Lire la console du navigateur à chaque test et traiter toutes les erreurs.
- Pas de clé API, pas de service payant, pas de serveur applicatif.
- Code commenté en français, aux endroits utiles uniquement.
- En cas de doute sur un choix structurant, poser la question plutôt que deviner.

## Liste de contrôle de la V1 (à valider avec Yves)

- [ ] La page s'ouvre sur NCPA, vue inclinée, sans erreur dans la console
- [ ] Le relief est visible (vallées de la Dives, coteaux du Pays d'Auge) et cohérent
- [ ] L'orthophoto est nette en zoomant, sans trou ni décalage avec le relief
- [ ] Pas de coutures gênantes entre tuiles
- [ ] Les 38 communes sont affichées, survol et clic fonctionnels
- [ ] Le bouton « Vue NCPA » ramène à la vue initiale
- [ ] Le curseur d'exagération agit en direct
- [ ] Navigation fluide sur un ordinateur de bureau standard
- [ ] Mention « © IGN » visible
- [ ] README complet

## Pistes V2 (ne pas développer sans demande)

- MNT LiDAR HD pour un zoom très détaillé.
- Couches métier NCPA (PAV, déchèteries) en points 3D.
- Bâtiments 3D (BD TOPO).
