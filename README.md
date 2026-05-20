# Smart City Flood Alert

Smart City Flood Alert est un système automatisé de surveillance et de régulation des inondations conçu pour sécuriser des zones urbaines sensibles. En associant une gestion physique (capteurs de niveau d'eau et pompes de drainage gérés par microcontrôleur) et une interface logicielle (serveur Flask et alertes Telegram), le projet permet de visualiser l'état des zones à risques en temps réel et d'intervenir rapidement en cas d'urgence.

Le système gère trois zones distinctes (Z1, Z2, Z3) et assure leur mise en sécurité de manière coordonnée.

---

## Architecture du Système

Le projet est structuré en trois composants principaux :

1. **Couche embarquée (Arduino Mega)** : Réalise les mesures physiques de niveau d'eau à l'aide de capteurs à ultrasons HC-SR04. Elle applique des filtres de stabilisation (debounce) pour éviter les fausses alertes et pilote des relais pour activer les pompes. Elle dispose également d'indicateurs visuels physiques (LEDs verte/rouge).
2. **Serveur Middleware (Python & Flask)** : Assure la liaison série à 115200 bauds avec l'Arduino, traite les données reçues, exécute les scripts d'automatisation intelligente (compte à rebours avant pompage) et envoie des notifications en direct sur un canal Telegram.
3. **Tableau de bord (Web)** : Une interface en temps réel (HTML5, CSS3, JavaScript natif) permettant de suivre graphiquement la hauteur de l'eau, de surveiller l'état de connexion de la carte, de consulter le journal des événements (logs) et d'envoyer des commandes manuelles ou d'urgence.

---

## Matériel Requis et Câblage

Le logiciel embarqué est configuré par défaut pour un **Arduino Mega**. Les affectations des broches sont les suivantes :

* **Capteurs Ultrasons (TRIG / ECHO)** : 
  * Zone 1 : Pins 22 / 23
  * Zone 2 : Pins 24 / 25
  * Zone 3 : Pins 26 / 27
* **Relais de puissance des pompes (Z1 / Z2 / Z3)** : Pins 8 / 9 / 10
* **Indicateurs LED (Rouge / Verte)** :
  * Zone 1 : Pins 2 / 3
  * Zone 2 : Pins 4 / 5
  * Zone 3 : Pins 6 / 7

---

## Installation et Démarrage Rapide

### 1. Configuration de la carte Arduino
1. Ouvrez le fichier `flood_city.ino` dans l'IDE Arduino.
2. Connectez votre Arduino Mega à votre ordinateur et sélectionnez le bon port.
3. Téléversez le programme sur la carte.

### 2. Configuration du serveur Python
Le serveur nécessite une installation de **Python 3.8** ou supérieur.

1. Créez un environnement virtuel et activez-le :
   ```bash
   python -m venv env
   # Sur Windows (PowerShell) :
   .\env\Scripts\Activate.ps1
   # Sur Linux / macOS :
   source env/bin/activate
   ```
2. Installez les paquets requis :
   ```bash
   pip install -r requirements.txt
   ```
3. Modifiez, si nécessaire, les configurations par défaut :
   * **Port série** : Dans `app.py`, ajustez le port de communication COM (ex : `COM6` sous Windows, `/dev/ttyACM0` sous Linux).
   * **Notifications Telegram** : Pour recevoir les alertes sur votre téléphone, renseignez votre jeton API de bot (`token`) et l'identifiant de discussion (`chat_id`) directement dans le constructeur de la classe `SerialManager` (dans `serial_manager.py`).

### 3. Lancement de l'application
1. Démarrez le serveur Flask en exécutant la commande suivante :
   ```bash
   python app.py
   ```
2. Accédez à l'interface d'administration depuis votre navigateur web à l'adresse suivante : [http://localhost:5000](http://localhost:5000)

---

## Logique de Fonctionnement et Sécurités

Le système propose deux modes de fonctionnement ainsi qu'une sécurité d'urgence :

### Mode Automatique (AUTO)
* Lorsqu'un capteur détecte un niveau supérieur au seuil critique (par défaut 30 %), l'Arduino le signale au serveur Python.
* Un compte à rebours de sécurité de 8 secondes se déclenche, accompagné d'une notification d'alerte Telegram.
* Si le niveau d'eau reste supérieur au seuil à la fin du compte à rebours, la pompe s'active.
* Dès que l'eau redescend sous le seuil (avec une marge d'hystérésis de 15 % pour éviter les micro-oscillations), la pompe est automatiquement coupée.
* **Contrainte hydraulique** : Une seule pompe peut fonctionner à la fois afin de préserver l'alimentation électrique et la tuyauterie.
* **Sécurité matérielle** : L'Arduino coupe automatiquement toute pompe active si celle-ci fonctionne en continu depuis plus de 15 secondes.

### Mode Manuel (MANUAL)
* La gestion automatique des pompes par le script Python est suspendue.
* L'opérateur prend le contrôle total et peut allumer/éteindre chaque pompe individuellement depuis le panneau droit du tableau de bord.
* Les alertes Telegram restent actives pour notifier l'équipe technique en cas de franchissement de seuil, mais aucune action corrective automatique n'est lancée.

### Arrêt d'urgence (STOP ALL)
* Un clic sur le bouton d'arrêt d'urgence coupe immédiatement l'ensemble des relais et active un verrou logiciel. Tant que le système n'est pas repassé explicitement en mode automatique ou manuel, aucune pompe ne peut démarrer.

---

## API REST du Middleware

Pour l'intégration ou la communication avec d'autres systèmes, le serveur Flask expose les endpoints suivants :

* `GET /api/state` : Fournit l'état en temps réel des capteurs, des pompes, de la connexion série, du service Telegram et renvoie les dernières lignes du journal d'événements.
* `POST /api/command` : Envoie une commande série brute à la carte (ex : `{"cmd": "PUMP Z1 ON"}`).
* `POST /api/demo/fill` : Simule de fausses variations de l'eau sur le tableau de bord (idéal pour les démonstrations sans matériel connecté).
* `POST /api/test-telegram` : Envoie instantanément un message de test pour valider la configuration du Bot Telegram.
