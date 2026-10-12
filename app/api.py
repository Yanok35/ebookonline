import json
import math
import os
import tempfile
import threading

from config import Config
from pathlib import Path

from flask import Blueprint, Flask, jsonify, request, send_from_directory

# =========================================================
# CONFIGURATION
# =========================================================

# Following is current directory
# BASE_DIR = Path(__file__).resolve().parent
# STATE_FILE = BASE_DIR / "reader_states.json"

# Catch STATE_FILE location from Flask project config.py file
STATE_FILE = Path(Config.STATE_FILE)
BASE_DIR = STATE_FILE.parent

api = Blueprint('api', __name__)

# Protège les lectures et écritures du fichier JSON
# entre les requêtes traitées par ce processus Python.
state_lock = threading.Lock()


# =========================================================
# GESTION DU FICHIER JSON
# =========================================================

def load_states():
    """
    Charge tous les états enregistrés.

    Si le fichier n'existe pas encore, retourne un
    dictionnaire vide.
    """

    if not STATE_FILE.exists():
        return {}

    with STATE_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Le fichier des états doit contenir un objet JSON.")

    return data


def save_states(states):
    """
    Enregistre les états dans un fichier temporaire,
    puis remplace le fichier précédent.

    Cette méthode évite qu'une interruption pendant
    l'écriture laisse un fichier JSON partiellement écrit.
    """

    fd, temporary_name = tempfile.mkstemp(
        prefix="reader_states_",
        suffix=".tmp",
        dir=str(BASE_DIR),
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(
                states,
                file,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )

            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary_name, STATE_FILE)

    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


# =========================================================
# VALIDATION DES DONNÉES
# =========================================================

def is_finite_number(value):
    """
    Vérifie qu'une valeur est un nombre JSON fini.
    Les booléens sont refusés, bien qu'ils soient
    techniquement des entiers en Python.
    """

    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )

def validate_state(data):
    """
    Vérifie les champs indispensables avant sauvegarde.
    """

    if not isinstance(data, dict):
        return None, "Le corps de la requête doit être un objet JSON."

    document_id = data.get("documentId")
    document_name = data.get("documentName")

    if (
        not isinstance(document_id, str)
        or not document_id.strip()
        or len(document_id) > 200
    ):
        return None, "documentId est invalide."

    if (
        not isinstance(document_name, str)
        or not document_name.strip()
        or len(document_name) > 500
    ):
        return None, "documentName est invalide."

    page_number = data.get("pageNumber")

    if (
        not isinstance(page_number, int)
        or isinstance(page_number, bool)
        or page_number < 1
    ):
        return None, "pageNumber doit être un entier positif."

    position_x = data.get("positionX")
    position_y = data.get("positionY")
    zoom = data.get("zoom")

    if not is_finite_number(position_x):
        return None, "positionX doit être un nombre fini."

    if not is_finite_number(position_y):
        return None, "positionY doit être un nombre fini."

    if (
        not is_finite_number(zoom)
        or not 0.4 <= zoom <= 2.5
    ):
        return None, "zoom doit être compris entre 0.4 et 2.5."

    updated_at = data.get("updatedAt")

    if updated_at is not None and (
        not isinstance(updated_at, str)
        or len(updated_at) > 100
    ):
        return None, "updatedAt est invalide."

    state = {
        "documentId": document_id,
        "documentName": document_name,
        "pageNumber": page_number,
        "positionX": position_x,
        "positionY": position_y,
        "zoom": zoom,
        "updatedAt": updated_at,
    }

    return state, None


# =========================================================
# API : RÉCUPÉRER UN ÉTAT
# =========================================================

@api.route("/api/reader/state/<document_id>", methods=['GET'])
def get_reader_state(document_id):
    """
    Retourne le dernier état enregistré pour un document.
    """

    try:
        with state_lock:
            states = load_states()
            state = states.get(document_id)

    except (OSError, ValueError, json.JSONDecodeError):
        api.logger.exception(
            "Impossible de lire le fichier des états."
        )

        return jsonify({
            "error": "Impossible de lire les états enregistrés."
        }), 500

    if state is None:
        return jsonify({
            "error": "Aucun état enregistré pour ce document."
        }), 404

    return jsonify(state)


# =========================================================
# API : SAUVEGARDER UN ÉTAT
# =========================================================

@api.put("/api/reader/state")
def put_reader_state():
    """
    Reçoit l'état du lecteur et l'enregistre dans le JSON.
    """

    data = request.get_json(silent=True)

    state, validation_error = validate_state(data)

    if validation_error:
        return jsonify({
            "error": validation_error
        }), 400

    try:
        with state_lock:
            states = load_states()

            # Un état par identifiant de document.
            states[state["documentId"]] = state

            save_states(states)

    except (OSError, ValueError, json.JSONDecodeError):
        api.logger.exception(
            "Impossible de sauvegarder l'état du lecteur."
        )

        return jsonify({
            "error": "Impossible d'enregistrer l'état."
        }), 500

    return jsonify({
        "success": True,
        "message": "État du lecteur enregistré.",
        "state": state,
    }), 200
