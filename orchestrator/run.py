"""Run the orchestrator service."""

import uvicorn

from orchestrator.config import OrchestratorConfig
from orchestrator.app import create_orchestrator_app

config = OrchestratorConfig()
app = create_orchestrator_app(config)

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level="info",
    )
