from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base
from zoneinfo import ZoneInfo

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index = True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    timezone_name = Column(String, default="UTC")

    conversations = relationship("Conversation", back_populates="owner")

    def get_local_time(self, dt):
        try:
            user_tz = ZoneInfo(self.timezone_name)
            return dt.astimezone(user_tz)
        
        except Exception:
            return dt

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    title = Column(String, default="New Session")

    owner = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete")

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key= True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    role = Column(String) #"user" or "llm"
    content = Column(Text)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    conversation = relationship("Conversation", back_populates="messages")

class Tasks(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String)
    total_time = Column(Integer, default=0) #in seconds
    mode = Column(String)
    status = Column(String, default="pending") #Entire task's current status
    created_at = Column(DateTime, default=datetime.utcnow)
   
    steps = relationship("TaskStep", backref="task", cascade="all, delete-orphan")

class TaskStep(Base):
    __tablename__ = "task_steps"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete ="CASCADE") ) # Link to parent mission
    backend_step_id = Column(String) # The "STP-XXXX" ID
    description = Column(String)
    time_allocated = Column(Integer)
    order = Column(Integer)    
    status = Column(String, default="pending")  # Individual step's current status
    artifact_content = Column(Text, nullable=True) # The content and detail about the step
    actual_duration = Column(Float, nullable=True) # Real time taken required to complete the step(useful for future reference to AI and dev)
    tool_required = Column(String)
    logic_reasoning = Column(String, nullable=True)
    
class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    file_path = Column(Text)
    user_id = Column(Integer, ForeignKey("users.id"))
    upload_date = Column(DateTime, default=datetime.utcnow)

class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    content = Column(Text) #~300 word long string
    chunk_index = Column(Integer)
    vector_id = Column(Integer)

class UserMemory(Base):
    __tablename__ = "user_memory"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    fact_key = Column(String) 
    fact_value = Column(String)
    importance = Column(Integer, default=1)
    category = Column(String, default="general")
    updated_at = Column(DateTime, default=datetime.utcnow(), onupdate=datetime.utcnow())