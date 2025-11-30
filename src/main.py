import os
import asyncio
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI
import uvicorn
from src.analyzer import Analyzer

# ------------------------------------------------------------
# Configuração de logs
# ------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = FastAPI()
analyzer = Analyzer()

# ------------------------------------------------------------
# Scheduler diário (executa sempre às 09:00)
# ------------------------------------------------------------
async def daily_scheduler():
    await asyncio.sleep(10)
    logger.info("⏳ Scheduler diário iniciado (executa sempre às 09:00).")

    while True:
        now = datetime.now()
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)

        # Se já passou das 09:00 de hoje, agenda para amanhã
        if now >= target:
            target = target + timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        logger.info(f"⏰ Aguardando até às 09:00 (faltam {wait_seconds/3600:.2f} horas).")

        # Espera até o horário definido
        await asyncio.sleep(wait_seconds)

        try:
            logger.info("🚀 Executando análise diária (09:00)...")
            analyzer.run_daily_analysis()
            logger.info("✅ Análise diária concluída.")
        except Exception as e:
            logger.error(f"Erro no scheduler diário: {e}")

# ------------------------------------------------------------
# Startup da aplicação
# ------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    asyncio.create_task(daily_scheduler())

# ------------------------------------------------------------
# Endpoint manual de trigger (para testes)
# ------------------------------------------------------------
@app.get("/run")
async def run_analysis():
    analyzer.run_daily_analysis()
    return {"status": "ok", "message": "Análise diária executada manualmente. Verifique o Telegram."}

# ------------------------------------------------------------
# Execução local direta
# ------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("src.main:app", host="0.0.0.0", port=port, log_level="info")
