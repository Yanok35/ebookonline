import json
import math
import os

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from app import is_read_only
from app.auth import api_login_required, current_user_key
from srcs.users.journal import append_event

# =========================================================
# CONFIGURATION
# =========================================================

def state_file():
    """
    The reading positions common to all the users, before userdata.db:
    STATE_FILE setting of the application (relative to the current
    directory). Read once, to give a copy to each user (see
    import_common_data()); no longer written.
    """
    return Path(current_app.config["STATE_FILE"])

api = Blueprint('api', __name__)


def log_reader_event(state):
    """
    Append a line to the journal of the reader events (READER_EVENTS_FILE):
    {"t": time of the server (UTC, ISO 8601), "doc": documentId (the sha1
    of the book), "page": pageNumber, "user": user name}. Nothing when the
    setting is empty. A failure is logged, the state is still saved.

    The reader saves its state 500 ms after each move (scroll, page, zoom)
    and at the opening of a book: the journal is the base of a reading
    history (sessions, reading time). Appended only, never rewritten.
    """
    events_file = current_app.config.get("READER_EVENTS_FILE")
    if not events_file:
        return
    try:
        append_event(events_file, state["documentId"], state["pageNumber"], current_user_key())
    except OSError as e:
        current_app.logger.warning("Reader event not logged in %s: %s", events_file, e)

# =========================================================
# GESTION DU FICHIER JSON
# =========================================================

def load_states():
    """
    Charge tous les états enregistrés.

    Si le fichier n'existe pas encore, retourne un
    dictionnaire vide.
    """

    path = state_file()
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Le fichier des états doit contenir un objet JSON.")

    return data


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
@api_login_required
def get_reader_state(document_id):
    """
    The reading position of the logged in user in a document (userdata.db),
    or 404.
    """
    state = current_app.userdata.state(current_user_key(), document_id)
    if state is None:
        return jsonify({
            "error": "Aucun état enregistré pour ce document."
        }), 404
    return jsonify(state)


# =========================================================
# API : SAUVEGARDER UN ÉTAT
# =========================================================

@api.put("/api/reader/state")
@api_login_required
def put_reader_state():
    """
    The reading position of the logged in user, saved in userdata.db (in
    memory only in read-only mode), and appended to the journal of the
    reader events.
    """

    data = request.get_json(silent=True)

    state, validation_error = validate_state(data)

    if validation_error:
        return jsonify({
            "error": validation_error
        }), 400

    try:
        current_app.userdata.set_state(current_user_key(), state)
    except OSError:
        current_app.logger.exception(
            "Impossible de sauvegarder l'état du lecteur."
        )

        return jsonify({
            "error": "Impossible d'enregistrer l'état."
        }), 500

    if is_read_only():
        return jsonify({
            "success": True,
            "readOnly": True,
            "message": "Lecture seule : état du lecteur conservé en mémoire "
                       "seulement, il sera perdu au redémarrage.",
            "state": state,
        }), 200

    log_reader_event(state)

    return jsonify({
        "success": True,
        "message": "État du lecteur enregistré.",
        "state": state,
    }), 200

# # Useful to debug reverse proxy configurations
# =========================================================
# NOTES IN THE MARGIN (userdata.db)
# =========================================================

@api.route("/api/notes/<sha1>", methods=["GET"])
@api_login_required
def get_notes(sha1):
    """ JSON {"notes": [...]}: the notes of the logged in user on a book """
    return jsonify(notes=current_app.userdata.notes(current_user_key(), sha1))


@api.route("/api/notes/<sha1>", methods=["PUT"])
@api_login_required
def put_notes(sha1):
    """
    JSON {"notes": [{id, page, ratio, quote, text}]}: all the notes of the
    logged in user on a book (CSRF token in the X-CSRFToken header).
    Answers {"notes": [...]} as kept (with created and updated), or {error}
    with 400 (invalid), 404 (unknown book). In read-only mode, kept in
    memory only.
    """
    from flask_wtf.csrf import validate_csrf
    from wtforms.validators import ValidationError

    try:
        validate_csrf(request.headers.get("X-CSRFToken"))
    except ValidationError:
        return jsonify(error="Jeton de sécurité invalide : recharger la page."), 400
    if current_app.bookdir.find_book_by_sha1(sha1) is None:
        return jsonify(error="Livre inconnu."), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Objet JSON attendu."), 400
    from srcs.users.userdata import UserDataError

    try:
        kept = current_app.userdata.set_notes(current_user_key(), sha1, data.get("notes"))
    except UserDataError as e:
        return jsonify(error=f"Notes refusées : {e}"), 400
    except OSError as e:
        current_app.logger.warning("Notes of %s not saved: %s", sha1, e)
        return jsonify(error="Notes non enregistrées sur le serveur."), 500
    return jsonify(notes=kept)


def move_user_data(old_sha1, new_sha1, page_offset=0):
    """
    The data of the users on a book whose file was replaced in place
    (BookDir.transform(), restore_original()): their notes, reading
    positions and pins move to its new sha1, the pages moved by page_offset
    (a cover page added: +1). A failure is logged: they stay under the old
    sha1.
    """
    try:
        current_app.userdata.move_book(old_sha1, new_sha1, page_offset)
    except OSError as e:
        current_app.logger.warning("Data of the users on %s not moved to %s: %s",
                                   old_sha1, new_sha1, e)


def import_common_data(app):
    """
    The reading positions (reader_states.json) and pins (book.db) common to
    all the users before userdata.db: a copy for each user of CREDENTIALS
    who has none yet (see UserData.import_common()). Not done when the
    positions can not be read (done at a next start).
    """
    with app.app_context():
        try:
            states = load_states()
        except (OSError, ValueError) as e:
            app.logger.warning("Common reading positions not imported, %s unreadable: %s",
                               state_file(), e)
            return
    pins = [b.sha1 for b in app.bookdir.get_all_books() if b.bookmarked]
    given = app.userdata.import_common(list(app.config["CREDENTIALS"]), states, pins)
    if given:
        app.logger.info("Common reading positions (%d) and pins (%d) copied to the users: %s",
                        len(states), len(pins), ", ".join(given))


# @api.route("/debug-proxy", methods=['GET'])
# def debug_proxy():
#     return {
#         "remote_addr": request.remote_addr,
#         "x_forwarded_for": request.headers.get("X-Forwarded-For"),
#         "x_forwarded_proto": request.headers.get("X-Forwarded-Proto"),
#     }
