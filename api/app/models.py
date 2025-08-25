from sqlalchemy import Column, String, DateTime, text
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from .db import Base

class Client(Base):
    __tablename__ = "clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
