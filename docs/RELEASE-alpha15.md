# 0.1.0-alpha.15

Serialize the complete application initialization across web and queue processes.
On a fresh Docker volume, concurrent Gunicorn workers could race while enabling
SQLite WAL or running extension migrations and fail with `database is locked`.

A separate SQLite startup lock now covers schema creation, administrator bootstrap,
and every extension migration. The lock is released on success, failure, or process
exit; normal application requests and queue processing do not hold it. Lock acquisition
waits up to 120 seconds. Existing data and backup formats are unchanged.

Regression coverage starts six independent processes against both a fresh and an
existing data directory, checks database integrity and a single administrator, and
checks recovery after a failed bootstrap.

## Mise à jour

Sauvegardez et vérifiez les données avant de recréer ensemble le serveur web et le
worker avec la même image alpha.15. Le fichier `.initialization.sqlite` est un verrou
technique recréable ; il ne contient aucune donnée utilisateur et ne doit pas être
restauré depuis une sauvegarde. Ne le supprimez pas pendant le fonctionnement des services.
