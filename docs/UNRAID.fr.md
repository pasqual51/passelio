# Essayer Passelio sur Unraid, sans déploiement Internet

Ces fichiers sont préparés pour une **nouvelle installation de test**, séparée d’Erugo et de la prévisualisation locale. Aucune installation n’est lancée automatiquement. L’image alpha.16 analysée est figée par son empreinte :

```text
ghcr.io/pasqual51/passelio@sha256:5ad6f418db8bed898da0992e34a2a843c4f2bace5246821cf01956c6dab99d24
```

Deux conteneurs sont nécessaires : `passelio` pour le site et `passelio-worker` pour les emails, le nettoyage et les sauvegardes planifiées. Ils partagent les mêmes dossiers. Les modèles sont dans [deploy/unraid](../deploy/unraid/).

## 1. Accès à l’image publique

Dans le terminal Unraid, quand tu seras prêt :

```sh
docker pull ghcr.io/pasqual51/passelio:0.1.0-alpha.16
```

L’image est publique : aucun compte GitHub, `docker login` ou jeton n’est nécessaire. Les modèles Unraid utilisent une empreinte figée ; cette référence est également téléchargeable sans connexion.

## 2. Préparer un espace de test neuf

Choisir un pool local pour la base SQLite. L’exemple utilise `/mnt/cache/appdata/passelio` ; si ton pool ne s’appelle pas `cache`, remplacer son nom dans le script et dans **les deux modèles**. Éviter `/mnt/user` et un emplacement déplacé par Mover pendant l’exécution. Garder appdata sur le pool choisi ; ne pas utiliser NFS/SMB pour la base.

Copier [prepare.sh](../deploy/unraid/prepare.sh) sur Unraid, le lire, puis lancer :

```sh
sh prepare.sh
```

Pour un autre pool local existant :

```sh
PASSELIO_APPDATA=/mnt/nom_du_pool/appdata/passelio sh prepare.sh
```

Le script refuse d’écraser un dossier existant. Il prépare uniquement `data`, `backups` et `secrets`, avec les droits UID/GID **10001**, puis génère un mot de passe initial aléatoire dans `secrets/admin_password.txt`. Le mot de passe n’est pas affiché. Aucun serveur web ni worker n’est démarré. Le dossier `appdata` du pool doit déjà exister.

Ne pas ajouter de variables PUID/PGID : cette image utilise directement UID/GID 10001. Ne pas partager le dossier `secrets` sur SMB.

## 3. Installer les deux modèles quand tu souhaiteras démarrer l’essai

Copier `my-passelio.xml` et `my-passelio-worker.xml` dans :

```text
/boot/config/plugins/dockerMan/templates-user/
```

Dans **Docker → Ajouter un conteneur**, choisir le modèle `passelio`. Renseigner :

- **Adresse administrateur** : ton adresse de connexion pour cette installation neuve.
- **URL LAN exacte** : par exemple `http://192.168.1.20:8099`, avec la véritable IP et le port du serveur.
- **Port Web LAN** : `8099` par défaut, à changer s’il est déjà utilisé.
- Les trois chemins du pool si celui-ci ne s’appelle pas `cache`.

Le secret doit être un fichier existant, monté en lecture seule. Démarrer le serveur web et attendre qu’il soit sain, puis ajouter `passelio-worker` avec **la même image, la même adresse, la même URL et les mêmes chemins**. Le worker n’expose aucun port.

Le port Web d’un conteneur bridge peut être accessible sur les interfaces du serveur. Ne pas créer de redirection de port sur le routeur ni de proxy public pour cet essai ; utiliser le LAN de confiance ou un VPN. HTTP et `SECURE_COOKIES=false` sont réservés à cet essai privé. Pour une future exposition, prévoir HTTPS, `SECURE_COOKIES=true` et la revue indépendante.

## 4. Première connexion et vérifications

Ouvrir l’URL configurée. L’identifiant est l’adresse administrateur saisie dans le modèle. Consulter le fichier `admin_password.txt` dans le terminal privé Unraid, puis changer le mot de passe depuis le profil. Ne pas coller son contenu dans un message ou une capture d’écran. Modifier le fichier initial ne réinitialise pas un compte déjà créé.

Vérifier avec des fichiers factices :

1. Connexion administrateur, langue, menu vertical et création d’un utilisateur de test.
2. Dépôt, téléchargement, protection par mot de passe, expiration et révocation d’un partage.
3. Configuration SMTP, puis test vers ta propre adresse et suivi dans l’historique ; le worker doit être démarré.
4. Création d’une sauvegarde complète, vérification et restauration dans un **autre** dossier de test.
5. Redémarrage des deux conteneurs et conservation des comptes et fichiers.

L’état Docker « sain » confirme seulement la réponse HTTP. Vérifier aussi les journaux du worker. Les sauvegardes dans le même pool ne constituent pas une copie hors serveur. Ne pas activer S3/SFTP ni changer leur destination sans fichiers de test et vérification des accès.

Pour arrêter l’essai, arrêter les deux conteneurs en conservant appdata. Ne pas supprimer les dossiers ou le fichier secret pendant une mise à jour. Conserver l’image précédente et une sauvegarde vérifiée avant tout changement de version.

## État de validation

Les modèles ont été utilisés pour une installation privée sur Unraid le 25 novembre 2026. La sauvegarde complète, sa vérification, une restauration isolée et la migration alpha.13 vers alpha.14 avec retour arrière ont été testées. L’image alpha.15 ci-dessus a passé 84 tests, l’analyse de sécurité bloquante et trois séries de six initialisations concurrentes sur Unraid. Le serveur web et le worker ont été mis à jour ensemble après sauvegarde vérifiée. Voir les [notes alpha.15](RELEASE-alpha15.md).

Ces contrôles portent sur un petit jeu de données local. Ils ne constituent pas un audit indépendant et ne valident pas les fournisseurs SMTP, S3/SFTP ou OIDC de chaque installation. Le [rapport sécurité alpha.14](security/HIGH-FINDINGS-TRIAGE-2026-11-19.md) reste un historique distinct.

Références : [gestion des conteneurs Unraid](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/), [authentification Docker](https://docs.docker.com/reference/cli/docker/login), [gestionnaire de modèles officiel Unraid](https://github.com/unraid/webgui/blob/master/emhttp/plugins/dynamix.docker.manager/include/CreateDocker.php).
