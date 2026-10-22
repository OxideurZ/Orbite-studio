# ORBITE Studio

Une interface Python locale pour la pipeline existante. Les trois styles inclus
sont **Cosmos**, **Aurore** et **Papier**. Les fichiers et vidéos restent sur votre ordinateur.

## Installation et ouverture

Installation simple et mises à jour : voir [INSTALLATION.md](INSTALLATION.md).
Pour utiliser les sources, installer Python 3.10+ avec Tkinter, puis :

```sh
python -m pip install -r requirements.txt
python studio.py
```

Tkinter est fourni avec les distributions classiques de Python pour Windows et
macOS : inclure Tcl/Tk lors de l’installation. Sous Debian/Ubuntu, installer
`python3-tk` si nécessaire. L’application nécessite un bureau graphique.
Le double-clic sur `Lancer_Studio.bat` sous Windows, ou `./lancer_studio.sh`
sous Linux/macOS, lance aussi l’éditeur lorsque les dépendances sont installées.
Les raccourcis Ctrl+O et Ctrl+S ouvrent et enregistrent un projet.

## Premier projet

1. **Contenu** : choisir un dessin, un SVG, une photo ou un dossier. Modifier le
   titre, la signature et les petites descriptions. Un titre vide reprend le nom
   du fichier ; un épisode numérique s’incrémente dans les lots.
2. **Détection** : choisir un profil portrait, silhouette ou photo. Comparer la source
   et les traits détectés ; vérifier les yeux et les détails intérieurs avant la vidéo.
   [Guide des seuils, contrôles manuels et SVG](DETECTION.md).
3. **Style** : choisir une base. Les textes et l’animation sont conservés.
   Choisir éventuellement une image de fond : une palette est proposée
   automatiquement. Chaque couleur reste modifiable par son code hexadécimal ou
   son sélecteur. Désactiver l’adaptation automatique pour garder sa palette.
4. Observer l’**aperçu**, puis choisir Construction, Image finale ou Ouverture.
   Sans source, un portrait de démonstration montre le style. Pour un dossier,
   l’aperçu représente la première image seulement.
5. Cliquer **Vérifier** pour contrôler les paramètres et sources sans rendu.
   **Images fixes** produit trois images de contrôle. **Vidéo test** produit un
   MP4 540 × 960 avec le rythme et le son. **Exporter** utilise la résolution
   choisie. Ouvrir les résultats avec le bouton à droite.

Le journal contient les diagnostics détaillés. Les traitements tournent en
arrière-plan ; **Annuler** arrête le traitement et ses sous-processus. Les
modifications faites pendant un export s’appliquent au prochain lancement.

## Marges pour Shorts, Reels et TikTok

Les marges sociales sont **désactivées par défaut** dans les nouveaux projets
et les thèmes inclus. Dans **Animation → Zone protégée**, le bouton **Activer
les marges recommandées** active un cadre de 240 px en haut, 440 px en bas,
180 px à droite et 48 px à gauche à 1080 × 1920. Ces valeurs restent modifiables
et sont proportionnelles en master et en aperçu. Lorsque la protection est activée :
Le fond couvre toujours le cadre entier ; textes, cercles, graphiques et dessin
se placent dans la zone utile, avec une réduction uniforme qui garde les
cercles ronds. Les quatre dispositions et les plans initial/final l’utilisent.
Les éléments dépassant exceptionnellement cette zone sont limités à son cadre.

La case **Voir les marges · aperçu uniquement** teinte les zones réservées en
rose et délimite la zone utile. Ces repères ne figurent jamais dans l’export.
Désactiver la zone protégée supprime toute réservation sociale. Le bouton
d’activation recharge les valeurs recommandées ci-dessus. Ces réglages sont enregistrés
avec les projets et les thèmes et apparaissent dans le contrôle Vérifier.
Un ancien projet ou thème reçoit la protection désactivée si le champ est absent.
Les projets personnels qui demandent explicitement `enabled: true` gardent ce choix.

Il s’agit d’un cadrage prudent, ajustable : les boutons, descriptions et panneaux
supplémentaires varient selon la plateforme, l’appareil et les options de
l’application. Contrôler un premier envoi dans l’application utilisée.

## Tous les réglages

- **Contenu** : source, sous-dossiers, titre, marque, sous-titre, épisode, texte
  final multiligne, descriptions des trois phases et crédit de provenance.
- **Style** : base ou thème JSON personnel, nom et description du thème,
  fond uni ou image, opacité, assombrissement haut/bas, six couleurs et trois
  polices. Le format de thème est la version 1.
- **Animation** : activation et quatre marges de protection, quatre dispositions existantes, tous les contours ou le
  contour principal, identifiant SVG facultatif, échantillonnage, ouverture,
  plan final, zoom final et tableau des cercles/durées. Sélectionner une étape,
  changer les valeurs, puis **Appliquer**. On peut ajouter, supprimer ou
  rétablir les étapes. Les nombres de cercles restent croissants ; augmenter
  les échantillons pour utiliser davantage de cercles.
- **Musique** : activation, mode génératif ou classique, ambiance, variation,
  tempo, densité, brillance, espace et niveau cible. Générer une écoute audio
  seule, puis ouvrir le lecteur audio. Voir [MUSIQUE.md](MUSIQUE.md).
- **Export** : extraction automatique/dessin/photo, niveau de détails,
  1080 × 1920 ou master 1440 × 2560 avec version 1080, cadence automatique ou
  personnalisée entre 1 et 120 images/s et dossier de sortie.
- **JSON avancé** : configuration complète du moteur, y compris les champs
  supplémentaires. **Actualiser depuis les champs** remplit l’éditeur ;
  **Appliquer le JSON** valide ses changements et actualise les formulaires.
  Les modifications du texte JSON ne prennent effet qu’après ce bouton.
  On peut importer directement les anciens JSON d’animation. Les chemins
  relatifs saisis dans cet éditeur partent du dossier du programme ; ceux d’un
  fichier importé partent du dossier de ce fichier.

Les dispositions gardent leur géométrie définie dans le moteur. Un nouveau
placement libre des éléments demanderait de modifier le moteur. Tous les
paramètres actuellement exposés dans les JSON sont pilotables dans Studio.
L’aperçu est une vraie image du moteur, calculée en petite résolution ; il ne
joue pas l’animation. Les dessins au trait et SVG donnent les contours les plus
prévisibles. Pour une photo, ajuster l’extraction avec les images fixes.

## Projet ou thème ?

**Enregistrer le projet** conserve les sources, la destination, les textes,
l’animation, l’identité visuelle et les options d’export dans un JSON réouvrable.
Les chemins y sont relatifs ; conserver les images et polices à côté du projet
ou à leur emplacement d’origine. Le projet n’embarque pas une copie des médias.

**Enregistrer le thème**, dans Style, exporte seulement l’identité visuelle
compatible avec `--theme mon_theme.json`. Les durées, les sources et les textes
propres au sujet restent dans le projet. Les fichiers sont interchangeables
avec la ligne de commande décrite dans [THEMES.md](THEMES.md).

La palette automatique extrait les teintes dominantes et propose des couleurs
avec un contraste adapté au fond uni de base. Vérifier le contraste sur une
photo très chargée ; opacité et assombrissement permettent de l’ajuster.

## Vérifications techniques

```sh
python -m unittest -v test_themes test_pipeline test_trace_image test_studio_model test_studio_gui test_safe_area test_music
```

Le test graphique est ignoré sans écran. Il exerce la sélection d’image, les
styles, la palette, les étapes, le JSON, les sauvegardes, le rechargement et la
vérification du moteur, la génération audio et le bouton de lecture
(lecteur simulé pour le test), sans exporter de vidéo. L’interface a aussi été
contrôlée en 1060 × 760 et 1240 × 930.

## V2 : cadrage et performances

Dans **Animation → Disposition**, choisir **Classique · grands cercles** (mode par
défaut des nouveaux projets). Ce mode conserve la disposition d’origine :
cercles bien visibles au-dessus et à gauche, fonctions sinus et cosinus, et deux
projections droites qui se croisent exactement au point du dessin. Les cercles
et le sujet partagent la même échelle ; le dessin reste plus petit si nécessaire
pour garder cet équilibre. Les plans de début et de fin sont centrés sur le tracé
visible avec un padding ; le zoom final reste réglable.
Les anciens projets gardent la disposition qu’ils ont enregistrée.

Dans **Export → Calcul et cache**, **Auto** traite au plus deux images d’un dossier
simultanément si la machine possède au moins quatre processeurs logiques. Choisir
**1** pour réduire l’usage mémoire, ou **3/4** sur une machine bien équipée.
Une image seule utilise un seul traitement. Ce mécanisme utilise des processus
compatibles avec macOS, Windows et Linux ; il ne nécessite pas de GPU.

Relancer exactement le même export réutilise ses sorties terminées. Une interruption,
un fichier manquant ou modifié entraîne un nouveau calcul. Cocher **Forcer** pour
tout recalculer. Une modification de source, thème, texte, cadence, résolution ou
moteur crée un résultat distinct. Les exports existants ne sont pas supprimés.
Le premier export après migration sera recalculé pour appliquer les corrections.

Les textes et couleurs de l’aperçu peuvent être ajustés sans refaire l’analyse SVG
et Fourier. Le rendu réutilise les couches fixes ; l’audio seul évite la préparation
graphique. Le gain réel dépend du dessin, de la résolution et de l’ordinateur.
