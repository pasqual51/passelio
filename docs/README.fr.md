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

Cette alpha n'est pas prête pour la production. Il n'y a pas encore de reprise après interruption, dossiers/ZIP, demandes de dépôt, quotas par utilisateur, S3, MFA ou antivirus. La parité complète avec Erugo n'est pas atteinte.

La limite de téléchargements compte chaque requête de fichier, pas les personnes ni les partages complets. Une coupure pendant l'envoi impose de recommencer. Un arrêt brutal du serveur peut laisser une réservation à examiner manuellement. Le quota ne remplace pas la surveillance de l'espace disque réel.

Le développement de Passelio n'altère pas l'instance Erugo existante. Le nom et la licence doivent être validés avant une publication publique.


## Administration

Ouvrir /admin avec un compte administrateur. Six rubriques sont disponibles : vue d'ensemble, utilisateurs, tous les partages, stockage, journal d'activité et paramètres. Il est possible d'ajouter des utilisateurs, de modifier leurs rôles, de désactiver/réactiver leurs comptes, de révoquer les partages et d'ajuster les quotas.

Les changements de rôle ou d'état ferment les sessions du compte concerné. Il n'est pas possible de retirer son propre rôle administrateur ni de désactiver son propre compte. Désactiver un utilisateur ne révoque pas automatiquement ses anciens liens.

Les quotas sont exprimés en Gio dans l'interface et persistent dans la base ; ils ne changent pas la taille du disque. L'administration affiche au maximum 200 utilisateurs/partages et les 200 derniers événements. Les notifications SMTP et CC/CCI sont disponibles dans Messagerie. La personnalisation et les contrôles antivirus restent à développer.


## Notifications e-mail

Dans Administration → Messagerie, enregistrer le serveur SMTP, le port, STARTTLS ou SSL/TLS, l'identifiant et le mot de passe si nécessaire, puis l'adresse de l'expéditeur. Le mot de passe enregistré n'est jamais réaffiché. Une valeur vide le conserve ; une case permet de le retirer explicitement. Activer les notifications puis utiliser le formulaire de test : il envoie uniquement à l'adresse indiquée, sans CC/CCI.

Après un partage, ou depuis son bouton de notification dans l'historique, saisir jusqu'à 20 destinataires et choisir la langue du message. Un mail séparé est envoyé à chacun, avec les CC/CCI définies par l'administrateur. Les CCI sont absentes des en-têtes du message. Aucun mot de passe de partage n'est envoyé.

L'historique distingue attente, en cours, accepté par SMTP et échec. Une acceptation SMTP ne garantit pas la présence dans la boîte du destinataire. Une relance manuelle peut créer un doublon, notamment après une acceptation partielle ou une interruption.


## Paramètres du système

Général configure le nom, l'URL utilisée dans les liens et les mails, le message de connexion et la langue de repli. Modifier l'URL ne crée pas d'enregistrement DNS et ne configure pas HTTPS. L'origine de déploiement BASE_URL reste également autorisée pour les protections CSRF, afin de garder l'accès à l'administration lors d'une modification.

Partage configure l'expiration par défaut/maximale, la limite de téléchargements et le mot de passe obligatoire (8 caractères minimum pour un partage). Les règles sont appliquées par le serveur aux nouveaux partages. Les quotas restent distincts de l'espace libre physique.

Notifications regroupe les CC/CCI automatiques ; SMTP contient la connexion et le test. Authentification règle la durée des sessions. Une réduction raccourcit les sessions existantes ; une augmentation ne les prolonge pas.

Sauvegarde de la base télécharge une copie SQLite cohérente de 32 Mio maximum. Elle contient des données sensibles et ne comprend ni les fichiers partagés ni le mot de passe SMTP séparé. Elle ne remplace pas la sauvegarde complète du volume. La restauration depuis l'interface et les sauvegardes planifiées restent à développer.


## Identité visuelle

Importer des logos, favicons et fonds PNG, JPEG ou WebP (5 Mio, 20 mégapixels maximum). Ils sont redimensionnés, réencodés en PNG et débarrassés de leurs métadonnées. Les SVG importés, vidéos et animations ne sont pas acceptés. Utiliser un logo/favicon depuis sa carte, ou revenir aux éléments d'origine. Sélectionner jusqu'à huit fonds et une durée de rotation ; les animations réduites désactivent la rotation.

Dix-sept thèmes sont proposés : les trois thèmes Passelio et les quatorze palettes Erugo adaptées avec attribution MIT. Les thèmes personnalisés utilisent uniquement des couleurs hexadécimales contrôlées. Le contraste des couleurs principales est contrôlé. Un fichier JSON importé remplit l'éditeur ; cliquer ensuite sur Appliquer le thème pour l'activer. Aucun CSS ni script importé n'est exécuté.

Les éléments visuels sont publics lorsqu'on connaît leur URL et ne doivent contenir aucune donnée confidentielle. Ils ont un budget séparé de 12 fichiers et 32 Mio, sur le même volume physique. La suppression d'une image est définitive et réinitialise ses sélections actives. Sauvegarder tout le volume pour conserver les images ; l'export SQLite seul ne les inclut pas.


## Palettes Erugo adaptées

Les choix intégrés sont Erugo, Erugo 2026, Heather, Sakura, Aqua, Colbolt, Dracula, Github Light, Tropical Sunset, Parma Violet, CyberNeon Flux, Amethyst, Galaxy et Cave Dweller. Les trois thèmes Passelio restent disponibles.

Les thèmes sombres règlent aussi le texte, les champs, les cartes et les tableaux. Les dégradés sont générés à partir de couleurs validées. Certaines teintes sont ajustées pour le contraste ; il s'agit d'une adaptation à Passelio, pas d'une reproduction pixel à pixel. L'import/export conserve les rôles de couleur étendus. Voir third_party/README.md et sa licence MIT.
