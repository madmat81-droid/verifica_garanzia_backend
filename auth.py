"""
auth.py
-------
Gestione login al portale hub.fordtrucks.it.

Espone la funzione:

    get_auth() -> (session, authenticate)

- `session` è una requests.Session riutilizzabile.
- `authenticate(session)` esegue il login al portale (se necessario),
  gestendo CSRF e cookie, e solleva un'eccezione se il login fallisce.

Pensato per essere compatibile con:

    from auth import get_auth

    session, authenticate = get_auth()
    authenticate(session)
    # da qui in poi usare `session` per le chiamate al portale.
"""

from __future__ import annotations

from typing import Dict, Tuple
import os
import requests
from html.parser import HTMLParser


# ============================
# CONFIGURAZIONE PORTALE
# ============================

# Pagina che contiene il form di login (homepage con modulo)
LOGIN_PAGE_URL = "https://hub.fordtrucks.it/"

# Endpoint POST che esegue il login e imposta i cookie (303 -> page id=1)
LOGIN_POST_URL = "https://hub.fordtrucks.it/index.php/component/sppagebuilder/"

# Nomi dei campi input del form di login
USERNAME_FIELD = "username"
PASSWORD_FIELD = "password"

# User-Agent "normale" per evitare blocchi banali
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


# ============================
# Parser HTML per hidden fields
# ============================

class HiddenInputsParser(HTMLParser):
    """
    Parser HTML minimale per recuperare tutti gli <input type="hidden" name="..." value="...">
    dalla pagina di login (token CSRF, return, option, task, ecc.).
    """

    def __init__(self) -> None:
        super().__init__()
        self.hidden_inputs: Dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "input":
            return
        attr_dict = dict(attrs)
        if attr_dict.get("type") != "hidden":
            return
        name = attr_dict.get("name")
        value = attr_dict.get("value", "")
        if name:
            self.hidden_inputs[name] = value


# ============================
# Lettura credenziali
# ============================

def _get_env_credentials() -> Dict[str, str]:
    """
    Legge le credenziali dalle variabili d'ambiente:

        FORD_USERNAME
        FORD_PASSWORD

    Solleva un RuntimeError se mancano.
    """
    user = os.environ.get("FORD_USERNAME", "").strip()
    pwd = os.environ.get("FORD_PASSWORD", "").strip()
    if not user or not pwd:
        raise RuntimeError(
            "Credenziali non trovate: imposta le variabili d'ambiente "
            "FORD_USERNAME e FORD_PASSWORD."
        )
    return {"username": user, "password": pwd}


# ============================
# Funzione principale: get_auth
# ============================

def get_auth() -> Tuple[requests.Session, callable]:
    """
    Restituisce (session, authenticate).

    - `session` è una requests.Session *non* ancora autenticata.
    - `authenticate(session)` esegue il login e imposta i cookie.

    Uso tipico:

        session, authenticate = get_auth()
        authenticate(session)
        r = session.get("https://hub.fordtrucks.it/index.php/garanzie")
    """

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
        }
    )

    logged_flag = {"value": False}  # chiusura mutabile per ricordare se abbiamo già loggato

    def authenticate(sess: requests.Session) -> None:
        """
        Esegue il login sul portale usando la `sess` passata.

        - GET sulla pagina di login per ricavare i campi hidden
        - POST al LOGIN_POST_URL con:
            * hidden fields (option, task, return, token CSRF, ecc.)
            * username / password letti dall'ambiente
        - Verifica che nei cookie compaia joomla_user_state=logged_in
        """
        if logged_flag["value"]:
            # Già loggato in questa esecuzione
            return

        creds = _get_env_credentials()

        # 1) GET pagina di login per recuperare i campi hidden
        headers_get = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        resp_get = sess.get(LOGIN_PAGE_URL, headers=headers_get, timeout=30)
        resp_get.raise_for_status()

        parser = HiddenInputsParser()
        parser.feed(resp_get.text)
        hidden_fields = parser.hidden_inputs  # es. option, task, return, token, ...

        if not hidden_fields:
            # Non abbiamo trovato hidden: non è detto sia un errore, ma è sospetto
            # Non interrompiamo, ma logghiamo una warning se necessario
            pass

        # 2) Prepara payload del login: hidden + username/password
        form_data: Dict[str, str] = dict(hidden_fields)
        form_data[USERNAME_FIELD] = creds["username"]
        form_data[PASSWORD_FIELD] = creds["password"]

        headers_post = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": headers_get["Accept"],
            "Origin": "https://hub.fordtrucks.it",
            "Referer": LOGIN_PAGE_URL,
        }

        # 3) POST login (requests segue automaticamente il redirect 303)
        resp_post = sess.post(
            LOGIN_POST_URL,
            headers=headers_post,
            data=form_data,
            timeout=30,
        )
        resp_post.raise_for_status()

        # 4) Verifica: cerchiamo il cookie joomla_user_state=logged_in
        cookies_str = "; ".join([f"{c.name}={c.value}" for c in sess.cookies])
        if "joomla_user_state=logged_in" not in cookies_str:
            raise RuntimeError(
                "Login non riuscito: cookie 'joomla_user_state=logged_in' non trovato. "
                "Controlla username/password o eventuali cambi nel form di login."
            )

        logged_flag["value"] = True

    return session, authenticate
