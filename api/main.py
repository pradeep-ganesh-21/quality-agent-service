from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from services.config_service import ConfigService
from services.database_service import DatabaseService
from controllers import quality_agent_controller


config_service = ConfigService("config.yml")
db_service = DatabaseService(config_service)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up Quality Agent Service...")

    try:
        db_service.wait_for_db()
        print("Database is ready")

        config_service.load_config()
        print("Configuration loaded")

        db_service.connect()
        print("Database connected")

        db_service.create_table_from_config()
        print("Database table initialized")

        quality_agent_controller.set_database_service(db_service)
        print("Application startup complete")

    except Exception as e:
        print(f"Failed to initialize application: {str(e)}")
        raise

    yield

    print("Shutting down Quality Agent Service...")
    db_service.close()
    print("Application shutdown complete")


app = FastAPI(
    title="Quality Agent Service",
    description="Centralized service for collecting quality agent run outputs",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(quality_agent_controller.router)


@app.get("/health")
async def health_check():
    try:
        if db_service.engine:
            with db_service.engine.connect() as conn:
                conn.execute("SELECT 1")
            return {"status": "healthy", "database": "connected"}
        else:
            return {"status": "unhealthy", "database": "not initialized"}
    except Exception as e:
        return {"status": "unhealthy", "database": "error", "detail": str(e)}


@app.get("/")
async def root():
    return {
        "message": "Quality Agent Service API",
        "version": "1.0.0",
        "docs": "/docs"
    }
