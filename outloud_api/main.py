"""Local development API. Replace development-token auth before public deployment."""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, create_engine, event, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ProjectRecord(Base):
    __tablename__ = "projects"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    website: Mapped[str] = mapped_column(String(2048), default="")
    brand_color: Mapped[str] = mapped_column(String(20), default="Mint")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DraftRecord(Base):
    __tablename__ = "drafts"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    format: Mapped[str] = mapped_column(String(30))
    body: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BrandColor(str, Enum):
    mint = "Mint"
    lilac = "Lilac"
    peach = "Peach"
    sky = "Sky"


class DraftFormat(str, Enum):
    x_post = "X post"
    reddit = "Reddit post"
    image = "Image post"
    video = "Video brief"


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=10000)
    audience: str = Field(default="", max_length=10000)
    website: str = Field(default="", max_length=2048)
    brand_color: BrandColor = BrandColor.mint

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A product name is required")
        return value


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    format: DraftFormat
    body: str = Field(default="", max_length=100000)

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A title is required")
        return value


class DraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(max_length=100000)
    expected_revision: int = Field(ge=1)

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        return DraftCreate.trim_title(value)


class DraftRead(DraftCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    revision: int
    updated_at: datetime


def create_app(database_url: str | None = None, development_token: str | None = None) -> FastAPI:
    db_url = database_url or os.environ.get("OUTLOUD_DATABASE_URL", "sqlite:///./outloud.sqlite3")
    token = development_token if development_token is not None else os.environ.get("OUTLOUD_DEV_TOKEN", "")
    engine = create_engine(db_url, connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {})
    if db_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")

    sessions = sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if len(token) < 32:
            raise RuntimeError("Set OUTLOUD_DEV_TOKEN to a random value of at least 32 characters.")
        # Temporary schema bootstrap for local development. Production will use Alembic migrations.
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    api = FastAPI(title="Outloud development API", version="0.1.0", lifespan=lifespan,
                  description="Single-workspace local API. Cloud identity, discovery, billing and generation are not connected.")
    bearer = HTTPBearer(auto_error=False)

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials or not secrets.compare_digest(credentials.credentials.encode(), token.encode()):
            raise HTTPException(status_code=401, detail="A valid development token is required",
                                headers={"WWW-Authenticate": "Bearer"})

    def session_dependency():
        with sessions() as session:
            yield session

    protected = [Depends(authorize)]

    # The handlers intentionally use concrete Session defaults instead of resolving
    # locally scoped annotations through postponed evaluation.
    @api.get("/health")
    def health():
        return {"status": "ok", "mode": "local-development"}

    @api.get("/v1/capabilities", dependencies=protected)
    def capabilities():
        return {"projects": True, "drafts": True, "cloud_identity": False,
                "live_discovery": False, "generation": False, "billing": False}

    @api.get("/v1/projects", response_model=list[ProjectRead], dependencies=protected)
    def projects(session: Session = Depends(session_dependency)):
        return session.scalars(select(ProjectRecord).order_by(ProjectRecord.created_at.desc())).all()

    @api.post("/v1/projects", response_model=ProjectRead, status_code=201, dependencies=protected)
    def create_project(payload: ProjectCreate, session: Session = Depends(session_dependency)):
        project = ProjectRecord(**payload.model_dump())
        session.add(project)
        session.commit()
        return project

    @api.get("/v1/projects/{project_id}", response_model=ProjectRead, dependencies=protected)
    def read_project(project_id: UUID, session: Session = Depends(session_dependency)):
        project = session.get(ProjectRecord, project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        return project

    @api.get("/v1/projects/{project_id}/drafts", response_model=list[DraftRead], dependencies=protected)
    def list_drafts(project_id: UUID, session: Session = Depends(session_dependency)):
        if not session.get(ProjectRecord, project_id):
            raise HTTPException(404, "Project not found")
        return session.scalars(select(DraftRecord).where(DraftRecord.project_id == project_id)
                               .order_by(DraftRecord.updated_at.desc())).all()

    @api.post("/v1/projects/{project_id}/drafts", response_model=DraftRead, status_code=201, dependencies=protected)
    def create_draft(project_id: UUID, payload: DraftCreate, session: Session = Depends(session_dependency)):
        if not session.get(ProjectRecord, project_id):
            raise HTTPException(404, "Project not found")
        draft = DraftRecord(project_id=project_id, **payload.model_dump())
        session.add(draft)
        session.commit()
        return draft

    @api.put("/v1/drafts/{draft_id}", response_model=DraftRead, dependencies=protected)
    def update_draft(draft_id: UUID, payload: DraftUpdate, session: Session = Depends(session_dependency)):
        # Compare-and-swap in SQL, not a read-then-write race.
        result = session.execute(update(DraftRecord)
            .where(DraftRecord.id == draft_id, DraftRecord.revision == payload.expected_revision)
            .values(title=payload.title, body=payload.body, revision=DraftRecord.revision + 1, updated_at=now()))
        if result.rowcount != 1:
            session.rollback()
            if not session.get(DraftRecord, draft_id):
                raise HTTPException(404, "Draft not found")
            raise HTTPException(409, "Draft changed. Reload before saving again.")
        session.commit()
        return session.get(DraftRecord, draft_id)

    @api.delete("/v1/drafts/{draft_id}", status_code=204, dependencies=protected)
    def delete_draft(draft_id: UUID, session: Session = Depends(session_dependency)):
        draft = session.get(DraftRecord, draft_id)
        if not draft:
            raise HTTPException(404, "Draft not found")
        session.delete(draft)
        session.commit()
        return Response(status_code=204)

    return api
