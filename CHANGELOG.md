# Changements

## 2.1.0 — 22 octobre 2026

- Nouvelle méthode Silhouette : suit les bords des aplats et leurs trous, au lieu
  de réduire des personnages pleins à un squelette. Détection automatique adaptée
  aux dessins anticrénelés et aux fonds clairs, y compris les damiers clairs intégrés.
- Seuil Otsu, seuil manuel/local, polarité, résolution, filtres de petits détails,
  lissage, simplification, fermeture, gradients photo et limite de traits réglables.
- Les points et pupilles isolés sont conservés. La limite de traits en photo n’est
  plus imposée silencieusement ; une limite manuelle est signalée dans les rapports.
- Correction de l’affichage des très courts passages stylo baissé.
- Nouvel onglet Détection, profils de base et comparaison source/traits avant Fourier.
  Comptage des sous-tracés et indication des filtres SVG qui excluent l’intérieur.
- Zones à ignorer au rectangle, annulation, export SVG pour retouche et bouton de
  finesse Fourier. L’export SVG fonctionne en arrière-plan.
- Réglages communs à l’aperçu, à l’export et aux clés de cache ; sauvegarde avec les
  projets. Les bitmaps n’héritent plus d’un filtre ou identifiant SVG précédent.
- Forcer recalcule également la détection ; un rapport de cache manquant est réparé.

## 2.0.1 — 22 octobre 2026

- Retour à la composition d’origine : cercles et sujet à la même échelle,
  projections droites, sans raccords en escalier. Priorité aux anneaux et à
  l’équilibre du dessin. Le centrage corrigé et les optimisations sont conservés.

## 2.0.0 — 22 octobre 2026

- Cadrage adaptatif : sujet agrandi, panneaux de cercles indépendants et disposition
  adaptée aux dessins horizontaux. L’enveloppe des cercles est bornée sur tous
  les instants pour la série finie configurée, sans déformer les anneaux.
- Ouverture et image finale centrées sur les limites du tracé visible, avec un
  padding qui évite les coupes sur les sujets asymétriques.
- Réutilisation des couches fixes et des signaux pendant le rendu ; les changements
  de texte ou de couleur dans l’aperçu gardent la préparation SVG et Fourier.
- Mode audio seul sans préparation graphique inutile.
- Cache des exports terminés : un nouveau lancement identique réutilise les fichiers
  présents ; une sortie supprimée ou modifiée est recalculée. Option Forcer.
- Dossiers : traitement parallèle portable avec processus spawn, automatique jusqu’à
  deux images ; choix de un à quatre dans le GUI. Threads FFmpeg limités par tâche.
- Projets existants conservés et mises à jour depuis la version 0.8.0.
- Les marges sociales restent désactivées par défaut. Musique, durées et thèmes conservés.

## 0.8.0

- Installation depuis un lien GitHub, sans Git ni compte pour les utilisateurs.
- Environnements isolés par version, activation après contrôle des dépendances.
- Vérification des nouveautés en arrière-plan et mise à jour depuis le GUI.
- Sauvegarde de session, redémarrage et retour à la version précédente.
- Données personnelles séparées du code de l’application.
- FFmpeg système ou binaire fourni par la dépendance imageio-ffmpeg.
- Démonstration générique dans l’aperçu, exemples et tests reproductibles.

Les fonctions existantes sont conservées : six onglets, thèmes personnalisables,
palette depuis le fond, conversion d’images/SVG, étapes de Fourier, musique
par image et export vertical. Les marges sociales sont désactivées par défaut.
