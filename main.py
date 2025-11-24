from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict

app = FastAPI()


class VerificaRequest(BaseModel):
    telaio: str


@app.post("/verifica")
def verifica_garanzia(request: VerificaRequest) -> Dict[str, Any]:
    telaio = request.telaio.strip()

    if not telaio:
        return {
            "success": False,
            "error": "Telaio mancante"
        }

    # 👇 QUI in futuro chiamerai il portale Ford con `requests`
    # Per ora restituiamo dati di esempio
    fake_result = {
        "telaio": telaio,
        "garanzia_attiva": True,
        "inizio": "2023-01-10",
        "fine": "2025-01-10",
        "messaggio": "Dati di esempio (backend su Render)"
    }

    return {
        "success": True,
        "data": fake_result
    }


@app.get("/")
def root():
    return {"status": "ok", "message": "Backend verifica garanzia attivo"}
