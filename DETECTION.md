# Détection : conserver les détails avant Fourier

ORBITE 2.1 utilise les mêmes réglages pour l’aperçu, les images fixes et la vidéo.
Commencer dans **Détection**, avant de régler la musique ou d’exporter un MP4.

## Choisir la bonne méthode

| Source | Profil conseillé | Résultat suivi par les cercles |
| --- | --- | --- |
| Portrait dessiné, traits noirs, Jean-Paul II | Portrait / dessin au trait | Centre de chaque ligne, pupilles conservées |
| Silhouette noire, logo plein, personnages sur une colline | Silhouette / logo plein | Contours extérieurs et trous intérieurs |
| Photographie | Photo · détails fins | Variations de contraste, avec réglage du bruit |
| SVG | Tous les traits SVG | Sous-tracés vectoriels, sans détection bitmap |

**Appliquer le profil** règle les paramètres d’extraction, sans modifier les titres,
les durées, les couleurs ou la musique. Le profil automatique privilégie le trait
sur le papier clair et passe aux contours sur les aplats épais. Il reste possible
de choisir explicitement une méthode si l’automatisme se trompe.
Un damier visible dans un JPEG est une partie de l’image, pas de la transparence.
Le seuil automatique sépare les aplats noirs des cases claires ; un damier sombre
ou coloré peut demander un seuil manuel et/ou des zones à ignorer.

## Trouver à quelle étape les détails disparaissent

1. **Voir la source** : inspecter le fichier d’entrée. Cet aperçu reste disponible
   même si aucun trait n’est détecté.
2. **Voir les traits** : inspecter la conversion avant Fourier. **Superposer**
   affiche les traits en bleu sur la source. Le nombre de traits, la méthode et le
   seuil effectifs sont affichés sous l’aperçu.
3. **Image finale** : inspecter la reconstruction Fourier. Si les traits détectés
   sont bons mais la reconstruction manque de finesse, essayer **Plus de détails
   Fourier** : au moins 1 536 cercles à la dernière étape et 65 536 échantillons,
   sans allonger les durées. L’erreur affichée est une distance RMS en pixels
   logiques, pas une garantie de reconnaissance visuelle.

Pour les SVG, **Contour fermé principal** élimine volontairement les autres
sous-tracés, donc souvent les yeux, les trous et l’intérieur des lettres. Cliquer
**Conserver tous les traits SVG** pour retirer ce filtre et l’identifiant SVG.
Les nouvelles images bitmap utilisent toujours tous leurs traits extraits.

## Réglages fins

- **Seuil automatique** : Otsu adapte la séparation au contraste du dessin.
- **Seuil manuel** : augmenter le seuil pour inclure des traits gris pâles ; le
  réduire pour éliminer un fond gris. Le réglage concerne les traits sombres,
  après l’éventuelle inversion de polarité.
- **Seuil local** : utile sur papier photographié avec éclairage irrégulier.
  **Contraste local** règle la différence minimale au fond local.
- **Couleur des traits** : forcer sombre/clair si la détection du fond se trompe.
- **Résolution d’analyse** : augmenter pour des détails fins dans une grande
  image. Aucun agrandissement artificiel des petites sources.
- **Surface/longueur minimales** : diminuer pour conserver cils, rides, lettres
  et points isolés ; augmenter pour supprimer du bruit.
- **Lissage/simplification** : commencer faible. Une valeur élevée peut gommer
  une petite courbe. Ces réglages sont exprimés dans les pixels de l’analyse.
- **Refermer les coupures** : commencer à 0 ; augmenter seulement pour des traits
  cassés, car cette opération peut aussi fusionner deux éléments proches.
- **Préserver les pupilles** : conserve les petits accents pleins qui pourraient
  disparaître lors de l’amincissement des traits.
- **Limite des traits** : 0 conserve tous les traits. Une limite manuelle garde
  les plus longs ; les suppressions sont indiquées dans le rapport.
- **Contours photo** : flou et sélectivité règlent les gradients conservés ; 0
  reprend la valeur automatique du niveau de détail photo.

Le profil **Ancien tracé · seuil 180** reprend les principaux paramètres du premier
portrait pour faciliter une comparaison avec les anciens résultats.

## Correction manuelle et retouche

Activer **Dessiner un rectangle**, puis glisser sur l’aperçu des traits pour retirer
un élément parasite, un bord ou un filigrane. Les rectangles rouges sont des repères
non exportés. **Annuler la dernière zone** et **Tout rétablir** rendent l’opération
réversible. Les zones sont des coordonnées relatives enregistrées avec le projet ;
sélectionner une autre source les efface pour éviter d’effacer un autre sujet.
Dans un dossier, les mêmes zones s’appliquent à toutes les images : utiliser cette
option seulement si les éléments à retirer ont la même position.

**Exporter le tracé SVG** permet de retoucher ou d’ajouter des traits dans Inkscape,
puis de choisir ce SVG comme nouvelle source. Il n’y a alors plus de détection
bitmap. Un SVG d’entrée est copié tel quel par ce bouton.

Tous les réglages sont dans `config.trace` des projets et dans `trace` des fichiers
d’animation. Par exemple :

```json
{
  "trace": {
    "threshold_method": "global",
    "threshold": 210,
    "min_component": 3,
    "min_stroke": 2,
    "smoothing": 0.5,
    "simplify": 0.2,
    "max_strokes": 0,
    "exclude_regions": []
  }
}
```

La méthode (`mode`) et le détail photo sont enregistrés avec le projet. En CLI :
`python orbite.py image.jpg --mode outline --config episode.json --stills`.
Pour extraire uniquement le SVG :
`python trace_image.py image.jpg --mode outline --output dessin.svg`.
Le fichier `.trace.json` adjacent contient les réglages effectifs et les nombres
de traits, utiles pour diagnostiquer un résultat.

La V2.1 invalide les anciennes conversions en cache. Modifier un réglage recalcule
le tracé ; **Forcer** recalcule également la détection, même si ses sorties existent.
Les anciens projets restent lisibles et reçoivent les réglages manquants par défaut.
