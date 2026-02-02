from sqlalchemy import Column, String, Integer, Float, Boolean, Decimal, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
import datetime

Base = declarative_base()

class Node(Base):
    __tablename__ = "nodes"
    id = Column(String, primary_key=True)
    api_key = Column(String, unique=True, index=True)
    balance = Column(Decimal(12, 2), default=100.0)
    reputation_score = Column(Float, default=1.0)
    strikes = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Skill(Base):
    __tablename__ = "skills"
    id = Column(String, primary_key=True)
    provider_id = Column(String, ForeignKey("nodes.id"))
    label = Column(String)
    price_tck = Column(Decimal(10, 2))
    metadata_json = Column(JSON)
    provider = relationship("Node")

class Escrow(Base):
    __tablename__ = "escrows"
    id = Column(String, primary_key=True)
    buyer_id = Column(String, ForeignKey("nodes.id"))
    seller_id = Column(String, ForeignKey("nodes.id"))
    amount = Column(Decimal(10, 2))
    status = Column(String, default="PENDING") # PENDING, SETTLED, DISPUTED
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
