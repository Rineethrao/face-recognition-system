import os
import uvicorn
from app.main import app

if __name__ == "__main__":
    reload_enabled = os.getenv("RELOAD", "false").lower() == "true"
    port_env = int(os.getenv("PORT", "8002"))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port_env,
        reload=reload_enabled,
        reload_dirs=["app"] if reload_enabled else None,
        reload_excludes=["storage/*", "cameras.json", "config.json"] if reload_enabled else None
    )

