import os, time, random
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import OperationalError

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user1:Titangs%23%211@79.174.88.140:19410/db1")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))

@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except:  # noqa
        s.rollback()
        raise
    finally:
        s.close()

@contextmanager
def session_scope_serializable(retries: int = 5, base_sleep: float = 0.03):
    """
    Транзакция SERIALIZABLE с ретраями на 40001 (serialization failure).
    Используйте для массовых/критичных операций (импорт/replace).
    """
    attempt = 0
    while True:
        s = SessionLocal()
        try:
            s.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            yield s
            s.commit()
            return
        except OperationalError as oe:
            s.rollback()
            pgcode = getattr(getattr(oe, "orig", None), "pgcode", "")
            if pgcode == "40001" and attempt < retries - 1:
                time.sleep(base_sleep * (2 ** attempt) + random.random() * base_sleep)
                attempt += 1
                continue
            raise
        finally:
            s.close()

def advisory_xact_lock(session, key_bigint: int):
    """Advisory-lock на время текущей транзакции."""
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": int(key_bigint)})
