# Passelio — Alpha privée

Passelio est une application indépendante de partage de fichiers, avec une interface en français et en anglais, un logo propre et une installation Docker.

## Ce qui fonctionne

Connexion et déconnexion, ajout d'utilisateurs par l'administrateur, changement de mot de passe, envoi de plusieurs fichiers, liens temporaires, protection par mot de passe, révocation, limites de téléchargements et quotas globaux. Les fichiers ont une empreinte SHA-256. Un processus nettoie les fichiers expirés ou révoqués toutes les cinq minutes.

## Installation locale

1. Copier `.env.example` vers `.env` et définir `ADMIN_EMAIL`.
2. Créer `secrets/admin_password.txt` avec un mot de passe aléatoire d'au moins 14 caractères. Sous Linux : dossier `secrets` en mode 700 et fichier en mode 444, afin que le secret monté en lecture seule reste lisible par l'UID 10001 du conteneur, sans accès des autres utilisateurs au dossier hôte. Sous Windows, protéger le dossier par ACL et vérifier la lisibilité du secret dans Docker. Ne jamais publier ce fichier.
3. Exécuter `docker compose build`, puis `docker compose up -d`.
4. Ouvrir `http://localhost:8080`, se connecter avec l'adresse choisie et le mot de passe du fichier, puis changer ce mot de passe dans l'interface.

Les données sont conservées dans le volume Docker `passelio_data`. Les limites par défaut sont de 20 Gio au total et de 2 Gio par partage. Elles sont configurables en octets dans `.env`.

Pour HTTPS, le reverse proxy et les sauvegardes, consulter [DEPLOYMENT.md](DEPLOYMENT.md).

## Limites de cette version

Cette alpha n'est pas prête pour la production. Il n'y a pas encore de notifications SMTP, CC/CCI, reprise après interruption, dossiers/ZIP, demandes de dépôt, quotas par utilisateur, S3, MFA ou antivirus. La parité complète avec Erugo n'est pas atteinte.

La limite de téléchargements compte chaque requête de fichier, pas les personnes ni les partages complets. Une coupure pendant l'envoi impose de recommencer. Un arrêt brutal du serveur peut laisser une réservation à examiner manuellement. Le quota ne remplace pas la surveillance de l'espace disque réel.

Le développement de Passelio n'altère pas l'instance Erugo existante. Le nom et la licence doivent être validés avant une publication publique.


## Administration

Ouvrir /admin avec un compte administrateur. Six rubriques sont disponibles : vue d'ensemble, utilisateurs, tous les partages, stockage, journal d'activité et paramètres. Il est possible d'ajouter des utilisateurs, de modifier leurs rôles, de désactiver/réactiver leurs comptes, de révoquer les partages et d'ajuster les quotas.

Les changements de rôle ou d'état ferment les sessions du compte concerné. Il n'est pas possible de retirer son propre rôle administrateur ni de désactiver son propre compte. Désactiver un utilisateur ne révoque pas automatiquement ses anciens liens.

Les quotas sont exprimés en Gio dans l'interface et persistent dans la base ; ils ne changent pas la taille du disque. L'administration affiche au maximum 200 utilisateurs/partages et les 200 derniers événements. Les contrôles SMTP, personnalisation et antivirus restent à développer.
