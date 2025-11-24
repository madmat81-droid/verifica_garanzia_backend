from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict
import os
import requests

app = FastAPI(
    title="Backend verifica garanzia",
    version="1.0.0",
)

# Sessione HTTP riutilizzabile per le chiamate al portale
SESSION = requests.Session()


class VerificaRequest(BaseModel):
    telaio: str


def chiama_portale_ford(telaio: str) -> Dict[str, Any]:
    """
    Esegue la stessa chiamata che fa il portale Ford quando clicchi 'Verifica garanzia'.
    Usa il cookie di sessione preso dalla variabile d'ambiente FORD_COOKIE.
    """

    # URL esatto preso da DevTools
    url = (
        "https://hub.fordtrucks.it/index.php/index.php"
        "?option=com_fordtrucks"
        "&view=warranty"
        "&task=warranty.getclaimwarrantyinfo"
        "&619b2f60e46095f3ba7b1d334bb20bec=1"
    )

    # Cookie della sessione (impostato come env var su Render)
    cookie_string = os.environ.get("FORD_COOKIE", "")
    cookie_string = cookie_string.strip()  # rimuove spazi e newline all'inizio/fine

    if not cookie_string:
        raise RuntimeError(
            "Variabile d'ambiente FORD_COOKIE non impostata su Render o vuota"
        )

    # Headers principali (semplificati ma sufficienti)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://hub.fordtrucks.it",
        "Referer": "https://hub.fordtrucks.it/index.php/garanzie",
        "Cookie": cookie_string,
    }

    # Dati del form (uguali al Payload visto in DevTools, tranne il telaio che cambia)
    form_data = {
        "option": "com_fordtrucks",
        "view": "warranty",
        "task": "warranty.getclaimwarrantyinfo",
        "619b2f60e46095f3ba7b1d334bb20bec": "1",
        "jform[telaio]": telaio,
    }

    # Chiamata HTTP al portale
    resp = SESSION.post(url, headers=headers, data=form_data, timeout=20)
    resp.raise_for_status()

    # Il server dichiara text/html; proviamo JSON, altrimenti ritorniamo il testo grezzo
    try:
        return {
            "raw_type": "json",
            "raw": resp.json(),
        }
    except ValueError:
        return {
            "raw_type": "text",
            "raw": resp.text,
        }


@app.post("/verifica")
def verifica_garanzia(request: VerificaRequest) -> Dict[str, Any]:
    """
    Endpoint principale: riceve un JSON tipo:
      { "telaio": "NM0KCXTP6KPK96400" }
    chiama il portale Ford e restituisce la risposta grezza.
    """
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
        # In futuro possiamo migliorare il logging,
        # per ora ritorniamo l'errore in chiaro.
        return {
            "success": False,
            "error": str(e),
        }


@app.get("/")
def root() -> Dict[str, Any]:
    """
    Endpoint di test per vedere se il backend è vivo.
    """
    return {"status": "ok", "message": "Backend verifica garanzia attivo"}
