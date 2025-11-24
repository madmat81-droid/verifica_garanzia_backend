from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, Optional
import os
import json
import requests

app = FastAPI(
    title="Backend verifica garanzia",
    version="2.0.0",
)

# Sessione HTTP riutilizzabile
SESSION = requests.Session()


class VerificaRequest(BaseModel):
    telaio: str


def _get_cookie_string() -> str:
    """Legge il cookie di sessione dalle env e lo pulisce."""
    cookie_string = os.environ.get("FORD_COOKIE", "").strip()
    if not cookie_string:
        raise RuntimeError("Variabile d'ambiente FORD_COOKIE non impostata o vuota")
    return cookie_string


def chiamata_anagrafica(telaio: str) -> Dict[str, Any]:
    """
    Prima chiamata:
    warranty.getclaimwarrantyinfo -> restituisce targa, rag_sociale, P.IVA, indirizzo, paese...
    """
    url = (
        "https://hub.fordtrucks.it/index.php/index.php"
        "?option=com_fordtrucks"
        "&view=warranty"
        "&task=warranty.getclaimwarrantyinfo"
        "&619b2f60e46095f3ba7b1d334bb20bec=1"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://hub.fordtrucks.it",
        "Referer": "https://hub.fordtrucks.it/index.php/garanzie",
        "Cookie": _get_cookie_string(),
    }

    form_data = {
        "option": "com_fordtrucks",
        "view": "warranty",
        "task": "warranty.getclaimwarrantyinfo",
        "619b2f60e46095f3ba7b1d334bb20bec": "1",
        "jform[telaio]": telaio,
    }

    resp = SESSION.post(url, headers=headers, data=form_data, timeout=20)
    resp.raise_for_status()

    data = resp.json()  # { "status": true, "data": { ... } }

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
    """
    Seconda chiamata:
    task=warranty_telaio_search&format=json
    -> restituisce struttura con HAS_WARRANTY e WARRANTY_LIST.
    """
    url = "https://hub.fordtrucks.it/index.php/index.php"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://hub.fordtrucks.it",
        "Referer": "https://hub.fordtrucks.it/index.php/garanzie",
        "Cookie": _get_cookie_string(),
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

    resp = SESSION.post(url, headers=headers, data=form_data, timeout=20)
    resp.raise_for_status()

    outer = resp.json()
    # outer = { status: true, draw: 0, recordsTotal: 1, ..., data: "<JSON come stringa>" }

    if not outer.get("status"):
        raise RuntimeError(f"Portale copertura status=false: {outer}")

    data_str = outer.get("data", "")
    try:
        inner = json.loads(data_str)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Impossibile decodificare JSON interno copertura: {e}: {data_str[:200]}")

    # inner = { "Result": {...}, "Data": { "HAS_WARRANTY": true, "WARRANTY_LIST": [ {...} ] } }
    data_section: Dict[str, Any] = inner.get("Data") or {}

    has_warranty = data_section.get("HAS_WARRANTY")
    warranty_list = data_section.get("WARRANTY_LIST") or []
    first: Optional[Dict[str, Any]] = warranty_list[0] if warranty_list else None

    copertura: Dict[str, Any] = {
        "HAS_WARRANTY": has_warranty,
    }

    if first:
        copertura.update(
            {
                "VIN": first.get("VIN"),
                "WARRANTY_TYPE": first.get("WARRANTY_TYPE"),
                "WARRANTY_TYPE_ID": first.get("WARRANTY_TYPE_ID"),
                "WARRANTY_START_DATE": first.get("WARRANTY_START_DATE"),
                "WARRANTY_END_DATE": first.get("WARRANTY_END_DATE"),
                "REGISTRATION_DATE": first.get("REGISTRATION_DATE"),
                "DEALER_CODE": first.get("DEALER_CODE"),
                "DEALER_NAME": first.get("DEALER_NAME"),
                "ENTITY_NAME": first.get("ENTITY_NAME"),
                "HAS_VEHICLE_SC": first.get("HAS_VEHICLE_SC"),
                "HAS_OILTOP": first.get("HAS_OILTOP"),
                "HAS_WEARTEAR": first.get("HAS_WEARTEAR"),
                "HAS_BATTERY": first.get("HAS_BATTERY"),
                "HAS_FUSESBULBS": first.get("HAS_FUSESBULBS"),
                "HAS_DPFFILTER": first.get("HAS_DPFFILTER"),
                "HAS_UPTIME": first.get("HAS_UPTIME"),
                "UPTIME_NAME": first.get("UPTIME_NAME"),
                "ADD_IS_OILANALYSIS": first.get("ADD_IS_OILANALYSIS"),
                "ADD_IS_VEHICLEPICKUP": first.get("ADD_IS_VEHICLEPICKUP"),
                "ADD_IS_ANNUALMOT": first.get("ADD_IS_ANNUALMOT"),
                "SC_OTHER_DESC": first.get("SC_OTHER_DESC"),
                "FREETOWING_START_DATE": first.get("FREETOWING_START_DATE"),
                "FREETOWING_END_DATE": first.get("FREETOWING_END_DATE"),
            }
        )

    return {
        "parsed": copertura,
        "raw_outer": outer,
        "raw_inner": inner,
    }


@app.post("/verifica")
def verifica_garanzia(request: VerificaRequest) -> Dict[str, Any]:
    """
    Endpoint principale: riceve { "telaio": "..." }
    -> chiama entrambi gli endpoint del portale
    -> restituisce cliente + copertura.
    """
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
        return {
            "success": False,
            "error": str(e),
        }


@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "message": "Backend verifica garanzia attivo"}
