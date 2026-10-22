# Installer ORBITE Studio

Un compte GitHub et Git ne sont pas nécessaires pour utiliser l’application.
L’installateur crée un environnement Python isolé et installe les dépendances,
y compris une version de FFmpeg fournie par `imageio-ffmpeg` si nécessaire.

## Windows

Installer **Python 3.10 ou plus récent** depuis [python.org](https://www.python.org/downloads/).
Conserver Tcl/Tk dans les composants installés. Ouvrir PowerShell, puis :

```powershell
curl.exe --fail --location https://raw.githubusercontent.com/OxideurZ/Orbite-studio/main/install.py -o install_orbite.py
py -3 install_orbite.py
```

L’application s’ouvre après l’installation. Pour les prochaines ouvertures,
double-cliquer sur `%LOCALAPPDATA%\ORBITEStudio\ORBITE.cmd` depuis l’Explorateur.
On peut créer un raccourci vers ce fichier.

## macOS

Installer Python 3.10+ avec Tk depuis [python.org](https://www.python.org/downloads/macos/),
puis dans Terminal :

```sh
curl --fail --location https://raw.githubusercontent.com/OxideurZ/Orbite-studio/main/install.py -o install_orbite.py
python3 install_orbite.py
```

Le lanceur se trouve dans `~/Library/Application Support/ORBITEStudio/ORBITE.command`.
Un double-clic le lance après l’installation.

## Linux

Sous Debian/Ubuntu, installer les prérequis une fois :

```sh
sudo apt install python3 python3-venv python3-tk curl
```

Puis, dans un bureau graphique :

```sh
curl --fail --location https://raw.githubusercontent.com/OxideurZ/Orbite-studio/main/install.py -o install_orbite.py
python3 install_orbite.py
```

Pour les prochaines ouvertures :

```sh
~/.local/share/ORBITEStudio/ORBITE.sh
```

Le premier téléchargement inclut les bibliothèques scientifiques et FFmpeg ;
il est donc plus long que les vérifications suivantes. Le cache de pip est
réutilisé lors des mises à jour. Aucun accès administrateur n’est nécessaire
pour installer l’application elle-même. Un accès Internet est nécessaire pour
l’installation et les mises à jour, puis le rendu fonctionne hors ligne.

## Mettre à jour

Le GUI vérifie GitHub au démarrage, au plus une fois par heure. Il ne télécharge
ni n’installe une nouvelle version sans clic sur le bouton correspondant.

1. Cliquer **Mises à jour** dans la barre du haut.
2. Utiliser **Vérifier maintenant** si nécessaire.
3. Cliquer **Mettre à jour et redémarrer**.

La session courante est enregistrée, la nouvelle version est installée dans
son propre environnement, puis l’application redémarre avec les réglages.
Terminer un rendu en cours avant de lancer une mise à jour.
Si un champ est invalide au moment du redémarrage, le GUI garde la session à
l’écran au lieu de la fermer. Corriger les champs, puis relancer.

On peut désactiver la vérification automatique dans cette fenêtre. Sans réseau,
la vérification échoue discrètement et l’éditeur continue de fonctionner.
Le bouton **Revenir à la version précédente** réactive la version conservée,
sans réinstallation. Les anciennes versions ne sont pas supprimées automatiquement.

Les mises à jour suivent les commits publiés sur `main`. Un changement de code
est détecté même si le numéro de version n’a pas changé. Le propriétaire du
dépôt doit donc y publier du code testé. Les vérifications automatiques du dépôt
aident à contrôler les changements. ORBITE ne modifie pas son propre code et ne
publie pas automatiquement de nouvelles versions : il faut continuer à publier
les améliorations sur GitHub.

## Où sont mes fichiers ?

Le dossier d’installation contient :

- `data/projects/` : destination proposée pour les projets.
- `data/themes/` : destination proposée pour les thèmes personnels.
- `data/output/` : destination d’export par défaut.
- `data/recovery/session-update.json` : session sauvegardée au redémarrage.
- `data/preferences.json` : préférences de vérification.
- `releases/` : versions du code avec leurs environnements isolés.
- `current.json` et `previous.json` : version active et version précédente.
- `launch.log` : erreurs éventuelles au lancement.

Les médias choisis ailleurs sur l’ordinateur restent à leur emplacement ; les
projets y font référence sans les copier. Les projets existants gardent leurs
chemins d’export. Les mises à jour ne remplacent aucun dossier de données.
Pour personnaliser un thème, l’enregistrer dans `data/themes/` ou dans un autre
dossier personnel, puis le charger dans Style.

Les installations Windows sont sous `%LOCALAPPDATA%\ORBITEStudio`, macOS sous
`~/Library/Application Support/ORBITEStudio`, Linux sous
`${XDG_DATA_HOME:-~/.local/share}/ORBITEStudio`. La variable `ORBITE_HOME` ou
l’option `--root CHEMIN` permet de choisir un autre emplacement. `ORBITE_DATA_DIR`
permet de choisir le dossier de données quand on utilise les sources directement.

## Dépannage

- **Tkinter manque** : sous Linux installer `python3-tk`. Sous Windows/macOS,
  utiliser une distribution Python avec Tcl/Tk.
- **venv/ensurepip manque** : sous Debian/Ubuntu installer `python3-venv`.
- **FFmpeg indisponible sur une architecture inhabituelle** : installer FFmpeg
  dans le PATH ; le programme privilégie le binaire système.
- **Installation interrompue** : relancer la commande. La version active n’est
  changée qu’après installation et contrôle des dépendances.
- **L’application ne s’ouvre pas** : consulter `launch.log` dans son dossier.
- **Limite GitHub atteinte** : attendre avant de revérifier. Aucun jeton GitHub
  n’est demandé aux utilisateurs de l’application publique.

Pour installer sans lancer immédiatement :

```sh
python3 install_orbite.py --no-launch
```

Une archive source locale peut aussi être installée dans un dossier géré :

```sh
python3 install.py --from-source . --no-launch
```

Pour développer directement dans les sources :

```sh
python3 -m venv .venv
# Activer .venv selon le système, puis :
python -m pip install -r requirements.txt
python studio.py
```
