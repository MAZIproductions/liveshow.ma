# Rachid Show Clipper

L'IA regarde les épisodes du **Rachid Show (2M)** sur YouTube, reconnaît **ton visage** et ne garde que **tes passages**.

## Ce que tu obtiens (`rendu/`)

| Fichier | Contenu |
|---|---|
| `segments.csv` | Liste de tes passages : épisode, début, fin, durée, lien YouTube qui démarre pile au bon moment |
| `clips/` | Chaque passage découpé en MP4 1080p |
| `clips_9x16/` | Les mêmes en vertical pour Reels / TikTok / Shorts, recadrés sur ton visage (option `--vertical`) |
| `montage.mp4` | Tous tes passages bout à bout |
| `premiere_sequence.xml` | Séquence prête pour **Premiere Pro** avec les rushs originaux |

## Installation (une seule fois)

Il faut **Python 3.9+** ([python.org](https://www.python.org/downloads/)).

```bash
cd tools/rachid-show-clipper
pip install -r requirements.txt
pip install --no-deps face_recognition
```

> Si l'installation de `face_recognition_models` échoue : `pip install --no-build-isolation face_recognition_models`.

## Utilisation

1. Mets **3 à 10 photos de toi** dans un dossier `ref/` : de face, de profil, avec et sans lunettes, idéalement des captures d'écran de l'émission. Plus il y a de photos, meilleur est le résultat.
2. Lance une des commandes suivantes :

```bash
# Recherche automatique sur YouTube
python clipper.py --ref ref --search "رشيد شو Rachid Show 2M" --max 30 --vertical

# Ou avec les liens exacts des épisodes / de la playlist officielle 2M
python clipper.py --ref ref --url "https://www.youtube.com/playlist?list=XXXX" --vertical

# Ou avec des vidéos déjà sur ton ordinateur
python clipper.py --ref ref --local mes_episodes --vertical
```

Compte environ **5 à 10 minutes d'analyse par épisode d'une heure**. L'analyse est mise en cache : relancer avec d'autres réglages de découpe est instantané.

## Importer dans Premiere Pro

1. `Fichier > Importer…` puis choisis `rendu/premiere_sequence.xml`.
2. La séquence **« Rachid Show — mes passages »** apparaît avec tous tes passages sur la timeline, reliés aux épisodes originaux (`rendu/episodes/`).
3. Tu peux alors allonger ou raccourcir chaque passage, ajouter les sous-titres, etc.

Si Premiere signale des médias hors ligne, relie-les vers le dossier `rendu/episodes/`.

## Réglages utiles

| Problème | Solution |
|---|---|
| Des passages manquent | `--tolerance 0.55`, `--upsample 2` (visages lointains), ajoute des photos dans `ref/` |
| Des passages ne sont pas toi | `--tolerance 0.45`, `--min-hits 3` |
| Les clips coupent trop sec | `--pad 3` |
| Un passage est découpé en plusieurs morceaux | `--gap 10` |
| Tu veux juste les timecodes, sans rendu vidéo | `--no-render` |

## Droits

Les épisodes appartiennent à **2M / la production du Rachid Show**. Pour ton usage perso (portfolio, archive), aucun problème. Pour **republier** des extraits sur tes réseaux, demande une autorisation à la production. Tu peux aussi publier de courts extraits en citant et taguant l'émission, mais un contrôle Content ID reste possible.
