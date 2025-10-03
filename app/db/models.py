from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, BigInteger, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()

class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, default=1)
    base_dir = Column(Text, nullable=False, default="")
    auto_save_dir = Column(Text, nullable=False, default="")
    temp_save_dir = Column(Text, nullable=False, default="")
    cancel_password = Column(String(255), nullable=False, default="admin123")
    printer_settings = Column(JSONB, nullable=False, default=dict)
    collectors_list = Column(JSONB, nullable=False, default=list)
    inspectors_list = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class Article(Base):
    __tablename__ = "articles"
    id = Column(BigInteger, primary_key=True)
    code = Column(String(255), nullable=False, unique=True, index=True)

class Shift(Base):
    __tablename__ = "shifts"
    id = Column(BigInteger, primary_key=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at = Column(DateTime(timezone=True))
    status = Column(String(20), nullable=False, default="open", index=True)
    task_items = relationship("TaskItem", back_populates="shift", cascade="all, delete-orphan")

class TaskItem(Base):
    __tablename__ = "task_items"
    id = Column(BigInteger, primary_key=True)
    shift_id = Column(BigInteger, ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False, index=True)
    article_id = Column(BigInteger, ForeignKey("articles.id", ondelete="RESTRICT"), nullable=False, index=True)
    total_copies = Column(Integer, nullable=False)
    remaining_copies = Column(Integer, nullable=False)
    shift = relationship("Shift", back_populates="task_items")
    article = relationship("Article")
    __table_args__ = (UniqueConstraint("shift_id", "article_id", name="uq_taskitem_shift_article"),)

class CollectorHistory(Base):
    __tablename__ = "collector_history"
    id = Column(BigInteger, primary_key=True)
    shift_id = Column(BigInteger, ForeignKey("shifts.id", ondelete="SET NULL"), index=True)
    article_id = Column(BigInteger, ForeignKey("articles.id", ondelete="SET NULL"), index=True)
    collector = Column(String(255), nullable=False)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    copies = Column(Integer, nullable=False, default=1)
    shift = relationship("Shift")
    article = relationship("Article")

class CheckHistory(Base):
    __tablename__ = "check_history"
    id = Column(BigInteger, primary_key=True)
    shift_id = Column(BigInteger, ForeignKey("shifts.id", ondelete="SET NULL"), index=True)
    article_id = Column(BigInteger, ForeignKey("articles.id", ondelete="SET NULL"), index=True)
    inspector = Column(String(255), nullable=False)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    shift = relationship("Shift")
    article = relationship("Article")
