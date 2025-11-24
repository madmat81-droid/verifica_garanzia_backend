from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict
import os
import requests

app = FastAPI()

# Sessione HTTP riutilizzabile
SESSION = requests.Session()


class VerificaRequest(BaseModel):
    telaio: str


def chiama_portale_ford(telaio: str) -> Dict[str, Any]:
    url = (
        "https://hub.fordtrucks.it/index.php/index.php"
        "?option=com_fordtrucks"
        "&view=warranty"
        "&task=warranty.getclaimwarrantyinfo"
        "&619b2f60e46095f3ba7b1d334bb20bec=1"
    )

    cookie_string = os.environ.get("FORD_COOKIE", "").strip()
    if not cookie_string:
        raise RuntimeError("Variabile d'ambiente FORD_COOKIE non impostata su Render")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://hub.fordtrucks.it",
        "Referer": "https://hub.fordtrucks.it/index.php/garanzie",
        "Cookie": cookie_string,
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

    try:
        return {"raw_type": "json", "raw": resp.json()}
    except ValueError:
        return {"raw_type": "text", "raw": resp.text}


@app.post("/verifica")
def verifica_garanzia(request: VerificaRequest) -> Dict[str, Any]:
    telaio = request.telaio.strip()

    if not telaio:
        return {"success": False, "error": "Telaio mancante"}

    try:
        dati_portale = chiama_portale_ford(telaio)
        return {
            "success": True,
            "data": dati_portale,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@app.get("/")
def root():
    return {"status": "ok", "message": "Backend verifica garanzia attivo"}
