import os
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Database ka address env variable se aata hai. Set nahi hai toh purani guftagu.db hi chalegi.
# Tests alag database use karte hain, taaki aapka asli data kabhi na chhuye.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///guftagu.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(20), unique=True, nullable=False)
    password_hash = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=utc_now)
    last_seen = Column(DateTime)  # aakhri baar kab online tha


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    is_group = Column(Boolean, default=False, nullable=False)
    name = Column(String(40))  # sirf group ke liye, private chat mein khaali
    created_at = Column(DateTime, default=utc_now)


class Participant(Base):
    __tablename__ = "participants"

    conversation_id = Column(Integer, ForeignKey("conversations.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    last_read_id = Column(Integer, default=0, nullable=False)  # is chat ka kaun sa message tak padh liya
    last_delivered_id = Column(Integer, default=0, nullable=False)  # kaun sa message tak is user ke paas pahunch gaya


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True, nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now)