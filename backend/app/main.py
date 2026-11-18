from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.future import select

from app.core.config import settings
from app.db.session import init_db, AsyncSessionLocal
from app.models.user import User
from app.models.endpoint import Endpoint
from app.models.incident import Incident, IncidentComment
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.core.security import hash_password
from app.rag.engine import SEED_KB_DOCUMENTS, rag_engine

from app.api.auth import router as auth_router
from app.api.incidents import router as incidents_router
from app.api.diagnostics import router as diagnostics_router
from app.api.remediation import router as remediation_router
from app.api.knowledge import router as knowledge_router
from app.api.agents import router as agents_router
from app.api.dashboard import router as dashboard_router
from app.api.chat import router as chat_router


async def seed_initial_data():
    async with AsyncSessionLocal() as session:
        # Check if users exist
        res = await session.execute(select(User))
        if not res.scalars().first():
            admin = User(
                name="IT Administrator",
                email="admin@college.edu",
                password_hash=hash_password("Admin@123"),
                role="admin",
                is_active=True
            )
            tech = User(
                name="Rajesh Kumar (Technician)",
                email="tech@college.edu",
                password_hash=hash_password("Tech@123"),
                role="technician",
                is_active=True
            )
            student = User(
                name="Ananya Sharma (Student)",
                email="student@college.edu",
                password_hash=hash_password("Student@123"),
                role="student",
                is_active=True
            )
            session.add_all([admin, tech, student])
            await session.flush()

            # Seed demo endpoint
            endpoint = Endpoint(
                agent_uuid="loq-agent-uuid-001",
                hostname="LAB-PC-LOQ01",
                os_name="Windows 11 Pro",
                os_version="10.0.22631",
                agent_version="1.0.0",
                owner_user_id=student.id,
                status="ONLINE"
            )
            session.add(endpoint)
            await session.flush()

            # Seed Knowledge Base Documents
            for doc_data in SEED_KB_DOCUMENTS:
                k_doc = KnowledgeDocument(
                    doc_id=doc_data["doc_id"],
                    title=doc_data["title"],
                    source_type=doc_data["source_type"],
                    category=doc_data["category"],
                    version=doc_data["version"],
                    approved=True,
                    content=doc_data["content"]
                )
                session.add(k_doc)
                await session.flush()

                # Chunk document
                chunks = rag_engine.chunk_document(doc_data["content"])
                for idx, c in enumerate(chunks):
                    k_chunk = KnowledgeChunk(
                        document_id=k_doc.id,
                        chunk_index=idx,
                        chunk_text=c,
                        metadata_json={"doc_id": k_doc.doc_id, "category": k_doc.category}
                    )
                    session.add(k_chunk)

            # Seed Demonstration Scenario Incident
            demo_inc = Incident(
                incident_number="INC-20261104-1001",
                reporter_id=student.id,
                endpoint_id=endpoint.id,
                title="My laptop is connected to the college Wi-Fi, but I cannot access anything.",
                description="I connected to Campus-Student-WiFi in the Main Library. Windows displays 'No Internet, secured'. I cannot open any web pages or intranet portals.",
                category="NETWORK",
                priority="HIGH",
                status="NEW",
                assigned_technician_id=tech.id
            )
            session.add(demo_inc)
            await session.flush()

            comment = IncidentComment(
                incident_id=demo_inc.id,
                author_id=student.id,
                author_name=student.name,
                comment="Reported via student portal.",
                is_internal=0
            )
            session.add(comment)

            # Seed a second incident: Printer spooler
            print_inc = Incident(
                incident_number="INC-20261104-1002",
                reporter_id=student.id,
                endpoint_id=endpoint.id,
                title="Lab 3 Network Printer not responding",
                description="Unable to print project report on Lab 3 HP LaserJet. Printer status says offline / spooler not running.",
                category="PRINTER",
                priority="MEDIUM",
                status="NEW"
            )
            session.add(print_inc)

            await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await seed_initial_data()
    yield
    # Shutdown


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="AISD — AI-Powered IT Incident Management System with Deterministic Rules, Ollama LLM, pgvector RAG & Endpoint Agent",
    lifespan=lifespan
)

# CORS (support localhost + any LAN client on campus/private subnets)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(auth_router, prefix="/api")
app.include_router(incidents_router, prefix="/api")
app.include_router(diagnostics_router, prefix="/api")
app.include_router(remediation_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(agents_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(chat_router)


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "database": settings.DATABASE_URL.split(":")[0],
        "ollama_model": settings.OLLAMA_MODEL,
        "mock_remediation": settings.REMEDIATION_MOCK_MODE
    }
