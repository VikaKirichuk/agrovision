from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String(100), nullable=False)
    email           = Column(String(255), unique=True, index=True, nullable=False)
    company         = Column(String(200), default="")
    phone           = Column(String(20), default="")
    hashed_password = Column(String, nullable=False)
    is_active       = Column(Boolean, default=True)
    is_admin        = Column(Boolean, default=False)   # ← НОВЕ
    created_at      = Column(DateTime, default=datetime.utcnow)
    last_login      = Column(DateTime, nullable=True)

    analyses = relationship("Analysis", back_populates="user", cascade="all, delete-orphan")


class Analysis(Base):
    __tablename__ = "analyses"

    id                = Column(Integer, primary_key=True, index=True)
    user_id           = Column(Integer, ForeignKey("users.id"), nullable=False)
    image_filename    = Column(String, nullable=False)   # ключ у S3
    original_filename = Column(String, nullable=False)
    anomalies_count   = Column(Integer, default=0)
    result_json       = Column(Text, default="[]")
    threshold         = Column(String(10), default="0.4")
    created_at        = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="analyses")