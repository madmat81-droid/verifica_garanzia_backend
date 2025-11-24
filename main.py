from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, Optional
import json
from html.parser import HTMLParser
import string

from auth import get_auth  # auth.py deve essere nella stessa repo

app = FastAPI(
    title="Backend verifica garanzia",
    version="6.1.0",
)


class VerificaRequest(BaseModel):
    telaio: str


# ============================
# SESSIONE PORTALE
# ============================

PORTAL_SESSION = None
PORTAL_AUTHENTICATE = None
PORTAL_LOGGED_IN = False

GARANZIE_TOKEN_NAME: Optional[str] = None
GARANZIE_TOKEN_VALUE: Optional[str] = None

GARANZIE_URL = "https://hub.fordtrucks.it/index.php/garanzie"


class HiddenInputsParser(HTMLParser):
    """Parser per tutti gli <input type="hidden"> in una pagina HTML."""

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


def get_portal_session():
    """
    Usa auth.get_auth():
      - crea una requests.Session
      - authenticate(session) esegue il login
    """
    global PORTAL_SESSION, PORTAL_AUTHENTICATE, PORTAL_LOGGED_IN

    if PORTAL_SESSION is None or PORTAL_AUTHENTICATE is None:
        sess, authenticate = get_auth()
        PORTAL_SESSION = sess
        PORTAL_AUTHENTICATE = authenticate

    if not PORTAL_LOGGED_IN:
        PORTAL_AUTHENTICATE(PORTAL_SESSION)
        PORTAL_LOGGED_IN = True

    return PORTAL_SESSION


def ensure_garanzie_csrf():
    """
    Dopo il login, legge la pagina /garanzie e recupera
    il token CSRF di Joomla per le chiamate AJAX di garanzia.

    Cerca un <input type="hidden" name="<32 hex>" value="1">.
    """
    global GARANZIE_TOKEN_NAME, GARANZIE_TOKEN_VALUE

    if GARANZIE_TOKEN_NAME and GARANZIE_TOKEN_VALUE:
        return

    session = get_portal_session()

    resp = session.get(
        GARANZIE_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=20,
    )
    resp.raise_for_status()

    parser = HiddenInputsParser()
    parser.feed(resp.text)
    hidden = parser.hidden_inputs

    # Heuristica: token Joomla = nome esattamente 32 char hex, value = "1"
    token_name = None
    token_value = None
    for name, value in hidden.items():
        if len(name) == 32 and all(c in string.hexdigits for c in name):
            token_name = name
            token_value = value or "1"
            break

    if not token_name:
        raise RuntimeError(
            f"Impossibile trovare il token CSRF in /garanzie. Hidden trovati: {list(hidden.keys())[:10]}"
        )

    GARANZIE_TOKEN_NAME = token_name
    GARANZIE_TOKEN_VALUE = token_value


# ============================
# CHIAMATE AL PORTALE
# ============================

def chiamata_anagrafica(telaio: str) -> Dict[str, Any]:
    """
    Prima chiamata:
    task=warranty.getclaimwarrantyinfo
    -> restituisce targa, rag_sociale, P.IVA, indirizzo, paese...
    """
    session = get_portal_session()
    ensure_garanzie_csrf()

    url = (
        "https://hub.fordtrucks.it/index.php/index.php"
        "?option=com_fordtrucks"
        "&view=warranty"
        "&task=warranty.getclaimwarrantyinfo"
    )

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://hub.fordtrucks.it",
        "Referer": GARANZIE_URL,
    }

    form_data = {
        "option": "com_fordtrucks",
        "view": "warranty",
        "task": "warranty.getclaimwarrantyinfo",
        "jform[telaio]": telaio,
    }

    # aggiungi token CSRF dinamico
    if GARANZIE_TOKEN_NAME and GARANZIE_TOKEN_VALUE:
        form_data[GARANZIE_TOKEN_NAME] = GARANZIE_TOKEN_VALUE

    resp = session.post(url, headers=headers, data=form_data, timeout=20)
    resp.raise_for_status()

    data = resp.json()

    # in alcuni casi status può essere "1"/"0" come stringa
    status_val = data.get("status")
    if not status_val or str(status_val) not in ("1", "true", "True", True):
        raise RuntimeError(f"Portale anagrafica status non OK: {data}")

    payload: Dict[str, Any] = data.get("data") or {}

    cliente_veicolo = {
        "targa": payload.get("targa"),
        "telaio": payload.get("telaio"),
        "rag_sociale": payload.get("rag_sociale"),
        "piva_prop": payload.get("piva_prop"),
        "indirizzo": payload.get("indirizzo"),
        "paese": payload.get("paese"),
    }

    return {
        "parsed": cliente_veicolo,
        "raw": data,
    }


def chiamata_copertura(telaio: str) -> Dict[str, Any]:
    """
    Seconda chiamata:
    task=warranty_telaio_search&format=json
    -> restituisce struttura con HAS_WARRANTY e WARRANTY_LIST.
    """
    session = get_portal_session()
    ensure_garanzie_csrf()

    url = "https://hub.fordtrucks.it/index.php/index.php"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://hub.fordtrucks.it",
        "Referer": GARANZIE_URL,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    form_data = {
        "option": "com_fordtrucks",
        "view": "warranty",
        "task": "warranty_telaio_search",
        "format": "json",
        "telaio": telaio,
    }

    # token CSRF dinamico
    if GARANZIE_TOKEN_NAME and GARANZIE_TOKEN_VALUE:
        form_data[GARANZIE_TOKEN_NAME] = GARANZIE_TOKEN_VALUE

    resp = session.post(url, headers=headers, data=form_data, timeout=20)
    resp.raise_for_status()

    outer = resp.json()

    status_val = outer.get("status")
    if not status_val or str(status_val) not in ("1", "true", "True", True):
        # qui vedi subito eventuali "Invalid Token"
        raise RuntimeError(f"Portale copertura status non OK: {outer}")

    data_str = outer.get("data", "")
    if not data_str:
        raise RuntimeError(f"Copertura: JSON interno vuoto. outer={outer}")

    inner = json.loads(data_str)

    data_section: Dict[str, Any] = inner.get("Data") or {}
    warranty_list = data_section.get("WARRANTY_LIST") or []
    first = warranty_list[0] if warranty_list else {}

    result = {
        "HAS_WARRANTY": data_section.get("HAS_WARRANTY"),
        **first,
    }

    return {
        "parsed": result,
        "raw_outer": outer,
        "raw_inner": inner,
    }


# ============================
# ENDPOINTS FASTAPI
# ============================

@app.post("/verifica")
def verifica_garanzia(request: VerificaRequest) -> Dict[str, Any]:
    telaio = request.telaio.strip()

    if not telaio:
        return {"success": False, "error": "Telaio mancante"}

    try:
        anag = chiamata_anagrafica(telaio)
        cop = chiamata_copertura(telaio)

        return {
            "success": True,
            "cliente_veicolo": anag["parsed"],
            "copertura": cop["parsed"],
            "debug": {
                "anagrafica_raw": anag["raw"],
                "copertura_outer": cop["raw_outer"],
                "copertura_inner": cop["raw_inner"],
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Backend verifica garanzia attivo"}
