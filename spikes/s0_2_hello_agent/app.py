"""S0.2 hello agent (DESCARTAVEL). Nao e codigo de producao.

Agente minimo: recebe uma mensagem em /invocations e responde via Unity Gateway
(model service de tres partes). Sem tools, sem dados.
"""

import os

from databricks_langchain import ChatDatabricks
from fastapi import FastAPI
from pydantic import BaseModel

MODEL = os.environ.get("ATLAS_LLM_SERVICE", "system.ai.gpt-oss-120b")

app = FastAPI(title="atlas-hello-agent")


class Ask(BaseModel):
    message: str = "Responda apenas: ok"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": MODEL}


@app.post("/invocations")
def invocations(body: Ask) -> dict[str, str]:
    llm = ChatDatabricks(model=MODEL, use_ai_gateway=True, max_tokens=32)
    return {"output": str(llm.invoke(body.message).content)}
