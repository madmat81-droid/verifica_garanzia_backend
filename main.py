from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, Optional
import json

from auth import get_auth  # auth.py deve essere nella stessa repo

app = FastAPI(
    title="Backend verifica garanzia",
    version="6.0.0",
)


class VerificaRequest(BaseModel):
    telaio: str


# ============================
# SESSIONE PORTALE
# ============================

PORTAL_SESSION = None
PORTAL_AUTHENTICATE = None
PORTAL_LOGGED_IN = False


def get_portal_session():
    global PORTAL_SESSION, PORTAL_AUTHENTICATE, PORTAL_LOGGED_IN

    if PORTAL_SESSION is None or PORTAL_AUTHENTICATE is None:
        sess, authenticate = get_auth()
        PORTAL_SESSION = sess
        PORTAL_AUTHENTICATE = authenticate

    if not PORTAL_LOGGED_IN:
        PORTAL_AUTHENTICATE(PORTAL_SESSION)
        PORTAL_LOGGED_IN = True

    return PORTAL_SESSION


# ============================
# CHIAMATE AL PORTALE
# ============================

def chiamata_anagrafica(telaio: str) -> Dict[str, Any]:
    session = get_portal_session()

    url = (
        "https://hub.fordtrucks.it/index.php/index.php"
        "?option=com_fordtrucks"
        "&view=warranty"
        "&task=warranty.getclaimwarrantyinfo"
        "&619b2f60e46095f3ba7b1d334bb20bec=1"
    )

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://hub.fordtrucks.it",
        "Referer": "https://hub.fordtrucks.it/index.php/garanzie",
    }

    form_data = {
        "option": "com_fordtrucks",
        "view": "warranty",
        "task": "warranty.getclaimwarrantyinfo",
        "619b2f60e46095f3ba7b1d334bb20bec": "1",
        "jform[telaio]": telaio,
    }

    resp = session.post(url, headers=headers, data=form_data, timeout=20)
    resp.raise_for_status()

    data = resp.json()

    if not data.get("status"):
        raise RuntimeError(f"Portale anagrafica status=false: {data}")

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
    session = get_portal_session()

    url = "https://hub.fordtrucks.it/index.php/index.php"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://hub.fordtrucks.it",
        "Referer": "https://hub.fordtrucks.it/index.php/garanzie",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    form_data = {
        "option": "com_fordtrucks",
        "view": "warranty",
        "task": "warranty_telaio_search",
        "format": "json",
        "619b2f60e46095f3ba7b1d334bb20bec": "1",
        "telaio": telaio,
    }

    resp = session.post(url, headers=headers, data=form_data, timeout=20)
    resp.raise_for_status()

    outer = resp.json()
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
