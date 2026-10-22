# Changer d’identité visuelle

Un thème JSON règle uniquement l’apparence : couleurs, image de fond, signature
et polices, ainsi que les marges de protection des plateformes. Les fréquences,
la forme, la disposition interne et le rythme restent dans la
configuration d’animation. Il n’est pas nécessaire de modifier le code Python.

## Les trois thèmes inclus

| Nom à utiliser | Apparence |
| --- | --- |
| `cosmos` | ORBITE d’origine : ciel étoilé, montagnes, cyan et violet |
| `aurore` | Fond bleu profond uni, menthe, corail et tracé ivoire |
| `papier` | Fond crème, encre sombre, pétrole et terre cuite |

```sh
python orbite.py --list-themes
```

Vérifier un thème sur une image ou un dossier **sans générer d’image, de son ou
de vidéo** :

```sh
python orbite.py mon_image.png --theme papier --check
python orbite.py mes_images/ --theme aurore --check
```

Le mode `--check` lit les sources, les paramètres, le fond et les polices ; il ne
vectorise pas l’image et ne lance aucun encodeur. Il ne crée pas de dossier de
sortie. Ce contrôle ne remplace pas un contrôle visuel du résultat.

Quand tu souhaiteras produire les vidéos, retirer `--check` :

```sh
python orbite.py mon_image.png --theme papier
```

## Créer ton identité

Créer un modèle complet, prêt à éditer :

```sh
python orbite.py --init-theme mon_theme.json
```

Ou partir d’un autre thème :

```sh
python orbite.py --theme aurore --init-theme mon_theme.json
```

Le fichier existant n’est jamais écrasé par cette commande. Les chemins du modèle
sont adaptés à son emplacement. Pour l’utiliser après modification :

```sh
python orbite.py mon_image.png --theme mon_theme.json --check
```

Exemple de thème partiel (un vrai fichier `fond.jpg` doit se trouver à côté) :

```json
{
  "version": 1,
  "name": "Mon univers",
  "brand": "MON UNIVERS",
  "tagline": "LES FORMES EN MOUVEMENT",
  "colors": {
    "background": "#08121c",
    "trace": "#ffe0a3",
    "x": "#7fe5d3",
    "y": "#c4a1ff"
  },
  "background": "fond.jpg",
  "background_opacity": 0.35
}
```

Les valeurs omises reprennent celles de Cosmos. Un thème partiel peut donc
changer seulement deux couleurs, ou seulement le fond.

## Paramètres

| Clé | Fonction |
| --- | --- |
| `name` | Nom de l’identité, utilisé pour distinguer ses sorties |
| `brand` | Signature de marque dans la vidéo |
| `tagline` | Sous-titre de la série |
| `colors.background` | Couleur de base derrière l’image de fond |
| `colors.ink` | Titres et points brillants |
| `colors.muted` | Textes secondaires |
| `colors.trace` | Trait qui dessine la figure |
| `colors.x`, `colors.y` | Couleurs des deux chaînes et des graphiques |
| `background` | Image de fond ; `""` pour utiliser seulement la couleur de base |
| `background_opacity` | Présence de l’image, entre 0 et 1 |
| `background_dimming.top`, `.bottom` | Assombrissement du fond, entre 0 et 1 |
| `fonts.sans`, `.bold`, `.serif` | Fichiers de polices TTF/OTF pour chaque rôle |
| `safe_area.enabled` | Activer le cadrage protégé ; `false` retrouve le cadrage original |
| `safe_area.top`, `.bottom`, `.right`, `.left` | Marges en pixels logiques 1080 × 1920 |

Toutes les couleurs s’écrivent `#RRGGBB`. Les chemins d’images et de polices sont
relatifs au fichier de thème, même quand le programme est lancé depuis un autre
dossier. Les chemins absolus sont également acceptés. Les polices DejaVu sont
incluses ; pour une police personnelle, fournir son fichier avec ton thème.

Pour un fond clair parfaitement uni, comme Papier :

```json
{
  "background": "",
  "background_opacity": 0,
  "background_dimming": {"top": 0, "bottom": 0}
}
```

Les clés inconnues, couleurs mal formées, fichiers manquants ou opacités hors
limites sont refusés avant de lancer le rendu. Un thème n’accepte pas les
paramètres d’animation comme `steps` ou `durations` : utiliser `--config` pour eux.

## Réglages ponctuels

Sans modifier de JSON :

```sh
python orbite.py image.png --theme cosmos --background mon_fond.jpg --background-opacity 0.3 --brand "MA SÉRIE" --check
python orbite.py image.png --theme aurore --background "" --check
```

La priorité est : paramètres par défaut → préréglage d’animation → `--config` →
`--theme` explicite → `--brand`, `--background`, `--background-opacity`.
Un thème explicite remplace donc l’identité visuelle d’une ancienne configuration,
tout en conservant son animation. Les options ponctuelles passent en dernier.

Le moteur avancé accepte aussi les thèmes :

```sh
python render_social.py --config examples/portrait_grand.json --theme papier --check
```

## Variantes et cache

Les sorties se trouvent dans :

```text
output/series/
  image-empreinte/
    traces/…/strokes.svg
    variants/
      cosmos-empreinte/episode.json
      papier-empreinte/episode.json
```

Les variantes conservent des dossiers distincts ; modifier une palette ou le
contenu d’un fichier de fond produit une autre variante. Les extractions sont
partagées tant que l’image et les réglages de tracé restent identiques. Chaque
variante référence son extraction précise, ce qui permet de tester aussi plusieurs
niveaux de détail sans modifier les anciens épisodes.

## Vérifications effectuées

```sh
python -m unittest -v test_themes test_pipeline test_trace_image
```

22 tests couvrent les thèmes, leur transmission au moteur, les variantes, le cache,
la validation des fichiers, les calculs de Fourier et l’extraction des traits.
Les tests de thèmes bloquent les appels au rendu et à FFmpeg : aucune nouvelle
vidéo ni aucun aperçu n’a été produit pour cette mise à jour.

## Zone protégée des plateformes

Le fond reste à bord perdu. Les marges sont **désactivées par défaut**.
En les activant, la composition utile est placée dans un cadre protégé,
en conservant les proportions des cercles. Réglages par défaut :

```json
"safe_area": {
  "enabled": false,
  "top": 240,
  "bottom": 440,
  "right": 180,
  "left": 48
}
```

Ce champ peut figurer dans un thème ou dans la configuration d’animation.
Un objet partiel conserve les autres marges par défaut. Les marges sont
proportionnelles à la résolution et modifiables dans Studio, onglet Animation.
Elles doivent laisser au moins la moitié de la largeur et de la hauteur.
Les interfaces des plateformes varient ; vérifier une publication test.
