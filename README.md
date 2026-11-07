# WORLDLY — Tout le monde, tout en un !

Plateforme Flask (actualités, météo, traduction écrite et vocale, PWA, notifications push, espace publicitaires, administration).
Données persistantes dans **Supabase PostgreSQL**, hébergement **Render**.

## État du projet (testé par `python tests/test_smoke.py`)
| Module | Branché à un vrai système | Remarque |
|---|---|---|
| Actualités | GDELT DOC 2.0, stockées en base, doublons éliminés (URL + titre) | Titre, source, date, image (lien) et lien d'origine uniquement : aucun texte d'article copié |
| Météo | Open-Meteo (géocodage, actuel, horaire, 7 jours, lever/coucher) | Les « alertes » sont **calculées** depuis les prévisions (Open-Meteo n'a pas d'alertes officielles) |
| Traduction écrite | MyMemory (défaut) ou LibreTranslate, détection de langue, historique local | Quota gratuit limité : renseigner `MYMEMORY_EMAIL` ou passer à LibreTranslate |
| Traduction vocale | Web Speech API (reconnaissance + lecture) → /api/translate | Chrome/Edge/Safari récents. **À valider sur vos téléphones** (micro impossible à tester en CI) |
| Push | PWA + Service Worker + VAPID + pywebpush, catégories, centre, historique, expirés supprimés | Envoi **non testé avec de vrais navigateurs** ici (simulé) |
| Admin | Actus, catégories, sources, pubs, notifications, messages, erreurs, paramètres | Chemin secret `ADMIN_PATH`, session + CSRF, limitation des essais |
| Publicités | Demande → approbation → paiement confirmé → campagne, **2 max** visibles | Le paiement passe par un **lien de prestataire** (ex. Stripe Payment Link) que l'admin colle dans Paramètres ; pas d'API de paiement intégrée |
| Pages légales | FAQ, CGU, confidentialité, mentions, contact, 404 | Textes **modèles à faire relire/compléter** |

## Déploiement
1. **Supabase** : créez un projet, copiez la chaîne de connexion Postgres (`DATABASE_URL`, avec `?sslmode=require`).
2. Générez vos secrets en local :
   - `python gen_vapid.py` → `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY`
   - `python gen_admin_hash.py` → `ADMIN_PASSWORD_HASH`
3. **Render** : « New → Blueprint » sur ce dépôt (`render.yaml`), puis renseignez les variables marquées `sync: false`.
   Les deux Cron Jobs actualisent les actualités (30 min) et envoient les alertes météo (3 h).
4. Premier démarrage : les tables sont créées automatiquement (sans jamais supprimer de données). Puis exécutez `supabase_rls.sql` dans l'éditeur SQL Supabase (active RLS : l'API publique ne peut rien lire).
5. Connectez-vous sur `https://votre-site/gestion-wl/login` (ou votre `ADMIN_PATH`).

## Local
```
pip install -r requirements.txt
cp .env.example .env   # puis export des variables (ou: set -a; source .env; set +a)
python app.py          # SQLite local si DATABASE_URL est vide
python tests/test_smoke.py
```

## À savoir
- Render gratuit met le service en veille : les Cron Jobs le réveillent, mais les notifications restent plus fiables sur une offre payante.
- Limitation de débit en mémoire (par processus) : suffisant pour démarrer, à remplacer par Redis à grande échelle.
- Pas de comptes utilisateurs (donc pas de table de préférences) : les préférences sont liées à l'abonnement push ou au navigateur.
- Ne jamais commiter `.env`. Les annonceurs ne doivent jamais envoyer de données bancaires (rappelé sur le formulaire).
