# Des musiques qui suivent les images

ORBITE conserve la synthèse douce de la première version et propose désormais
une composition générative par image. Tout fonctionne en local avec NumPy,
SciPy et FFmpeg, sans téléchargement de modèle ni banque de sons.

## Écouter et choisir

Dans **Studio → Musique** :

1. Choisir **Générative par image** et une ambiance.
2. Cliquer **Générer l’écoute · audio seul**. Le programme crée le morceau
   complet au rythme du film, sans calculer les images de la vidéo.
3. Cliquer **Écouter le dernier MP3** pour ouvrir le lecteur de l’ordinateur.
   Pour un dossier d’images, ce bouton ouvre le dernier morceau du lot.
4. **Autre variation** augmente le numéro de variation. Régénérer l’écoute
   pour comparer, puis exporter la vidéo quand le choix convient.

Même géométrie, réglages, durée et version du moteur : même composition.
Changer les titres, les couleurs ou le fond ne relance pas une loterie musicale.
Les paramètres sont conservés dans les projets et les configurations
d’animation. Les thèmes visuels restent consacrés à l’apparence.

### Ambiances

| Ambiance | Intention et différences |
| --- | --- |
| **Orbite** | Arpèges doux, nappes discrètes, continuité avec le style initial |
| **Brume** | Moins de notes, tempo plus lent, nappes plus présentes et notes longues |
| **Cristal** | Notes plus légères, petite touche de troisième harmonique, tempo plus allant |
| **Classique original** | Synthétiseur et motif de la première vidéo ; seul le réglage de niveau s’applique |

Les ambiances génératives font varier le rythme et les timbres. Elles gardent
la même famille harmonique pour préserver l’identité de la série.

### Réglages

| Réglage | Effet |
| --- | --- |
| Variation | Une autre composition pour la même forme, reproductible par son numéro |
| Tempo | `0` : automatique ; sinon de 48 à 120 BPM |
| Densité | Probabilité de jouer les notes secondaires ; les phrases gardent des respirations |
| Brillance | Présence des harmoniques et fréquence du filtre ; pas un bouton de volume |
| Espace / écho | Trois réflexions discrètes, sans boucle de rétroaction |
| Niveau cible | −18 LUFS par défaut ; de −26 (discret) à −14 (plus présent) |

Un premier essai conseillé : **Orbite**, densité 55 %, brillance 35 %,
espace 35 %, niveau −18 LUFS. **Brume** fonctionne aussi à densité 35 % et
brillance 20 %. Le niveau est un choix éditorial ; −18 LUFS n’est pas présenté
comme une obligation de Shorts, Reels ou TikTok.

## Méthodes connues et choix retenus

La **sonification par correspondance de paramètres** associe des propriétés des
données à des dimensions sonores. Ce cadre est présenté dans le
[Sonification Handbook, chapitre 15, Grond et Berger, 2011](https://sonification.de/handbook/chapters/chapter15/).
La revue de [Dubus et Bresin, PLOS ONE, 2013](https://doi.org/10.1371/journal.pone.0082491)
étudie les stratégies utilisées dans ce domaine. Ces travaux donnent un cadre
pour concevoir les correspondances ; ils ne garantissent pas qu’un morceau
particulier sera agréable ou captivant.

La **composition probabiliste sous contraintes** est une autre famille bien
établie : les choix peuvent varier, tout en respectant des règles musicales.
Voir [Ames, *The Markov Process as a Compositional Model*, 1989](https://www.charlesames.net/references/CharlesAmes/markov.html)
et [Fernández et Vico, *AI Methods in Algorithmic Composition: A Comprehensive Survey*, JAIR 2013](https://arxiv.org/abs/1402.0585).

L’implémentation d’ORBITE est une adaptation pratique de ces idées. Elle emploie
des probabilités conçues à la main, conditionnées par la note précédente, la
forme et de petits motifs. Elle n’entraîne pas un modèle sur des chansons et
ne reproduit pas l’algorithme complet de l’un de ces articles.

### Comment l’image intervient

| Donnée | Utilisation dans le moteur |
| --- | --- |
| Géométrie normalisée et état du crayon | Empreinte stable qui initialise le générateur pseudo-aléatoire |
| Répartition de l’énergie de Fourier | Complexité qui nuance le tempo automatique |
| Hauteur du point pendant le dessin | Cible mélodique, ramenée à des notes autorisées |
| Position horizontale | Position stéréo légère, jamais un va-et-vient extrême |
| Premières amplitudes de Fourier X/Y | Couleur des nappes et texture harmonique très discrète |
| Étapes de construction | Petits accents accordés et entrée progressive de la texture |
| Fin de la construction | Retour vers la tonique et arrêt de la mélodie avant le fondu final |

Ces correspondances sont des **choix artistiques**. Le moteur ne reconnaît pas
le sujet, ses émotions ou sa signification. Deux extractions différentes d’une
même image peuvent donner des compositions différentes.

### Ce qui encadre l’aléatoire

- Une gamme pentatonique majeure commune à la mélodie et aux accords.
- Des mouvements mélodiques limités à sept demi-tons, hors retour final à la tonique.
- Pas de séries de trois notes identiques dans la mélodie générée.
- Des motifs de phrase récurrents, modulés par la forme, et plusieurs rythmes
  possibles avec des notes omises plutôt qu’un arpège identique en boucle.
- Des voix d’accompagnement qui choisissent l’octave proche de la voix précédente.
- Des accords plus stables à la fin et une note de résolution explicite.

Cela donne une cohérence contrôlable, pas une garantie universelle de consonance
ou de préférence musicale : le goût et le contexte d’écoute restent déterminants.

### Douceur et niveau sonore

Les sons sont synthétisés avec des sinusoïdes et quelques harmoniques faibles,
sans bruit blanc ni percussion agressive. Chaque note a une attaque et une
sortie progressives. Un filtre atténue les graves inutiles et les hautes
fréquences ; le morceau possède aussi un fondu initial et final.

Le traitement final mesure le signal et le normalise en **deux passes**, avec
un plafond de **−2 dBTP** avant compression en AAC/MP3. Il utilise le filtre
[loudnorm de FFmpeg](https://www.ffmpeg.org/ffmpeg-filters.html#loudnorm), qui
s’appuie sur les mesures de sonie et de crêtes vraies. La mesure de sonie est
définie par [ITU-R BS.1770](https://www.itu.int/rec/R-REC-BS.1770).
Le rapport indique la sonie obtenue et le type de normalisation utilisé.
Le volume d’écoute dépend ensuite du téléphone, du casque et de la plateforme.

## Configuration JSON et ligne de commande

Dans un projet ou un JSON d’animation :

```json
"music": {
  "mode": "generative",
  "style": "orbital",
  "variation": 0,
  "tempo": 0,
  "density": 0.55,
  "brightness": 0.35,
  "space": 0.35,
  "target_lufs": -18
}
```

`style` accepte `orbital`, `ambient` ou `crystalline`. `mode` accepte
`generative` ou `classic`. Un objet partiel complète les valeurs par défaut.
Les anciens projets reçoivent ces réglages par défaut ; sélectionner Classique
original pour retrouver l’ancien motif. La variation est un entier de 0 à
2147483647. Densité, brillance et espace vont de 0 à 1.

```sh
python orbite.py mon_image.png --config mon_animation.json --audio-only
```

Cette commande produit un WAV et un MP3, ainsi qu’un rapport JSON avec les
notes, les accords, le tempo, la tonalité et les mesures de niveau. Elle
réutilise l’extraction de contours en cache. Elle ne crée ni PNG ni MP4.
Sans `--audio-only`, la même configuration musicale accompagne la vidéo.
La durée d’un morceau change avec celle du film ; modifier les étapes ou leur
durée peut aussi changer la composition.

## Exemples et contrôles

Les tests contrôlent la reproductibilité, les changements par image et
variation, les contraintes de notes, les fondus, les variations de signal,
l’énergie dans les aigus, la compatibilité stéréo, la normalisation mesurée
indépendamment et le chemin audio seul. L’interface est également testée avec
sauvegarde, rechargement, génération et ouverture simulée du lecteur audio.
Ces contrôles techniques ne remplacent pas ton écoute pour choisir l’ambiance.
