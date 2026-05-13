# 🧠 AI Assistant — Full Stack LLM System

## 🚀 Overview
A full-stack AI assistant powered by a local LLM (TinyLlama via Ollama), featuring real-time streaming responses, user authentication, and persistent conversation memory.

This project is designed as a **locally hosted, privacy-first AI system** with a focus on performance, modular architecture, and real-time interaction.

---

## 🎯 Problem Statement
Most AI chat applications today:
- Depend heavily on cloud APIs  
- Lack real-time responsiveness (token streaming)  
- Do not provide full control over data and models  

This project aims to build a **self-hosted AI system** that:
- Runs locally  
- Streams responses in real-time  
- Maintains conversation memory  
- Supports secure multi-user interaction  

---

## 💡 Solution
The system is built using a **FastAPI backend + Vanilla JS frontend**, integrated with a local LLM via Ollama.

Key features:
- ⚡ Real-time token streaming (SSE)
- 🔐 JWT-based authentication
- 🧠 Context-aware conversations (memory of last messages)
- 💾 Persistent chat storage (PostgreSQL)
- 🖥️ Interactive frontend with dynamic UI/UX

---

## 🧠 Tech Stack

### Backend
- FastAPI
- PostgreSQL
- SQLAlchemy
- JWT Authentication (OAuth2)
- Ollama (TinyLlama)

### Frontend
- HTML, CSS, JavaScript (Vanilla)
- Streaming UI rendering
- Neumorphic UI design

---

## ⚙️ System Architecture
  Frontend (JS UI)
      ->
  FastAPI Backend
      ->
  Auth Layer (JWT)
      ->
  Conversation Engine
      ->
  Ollama API (TinyLlama)
      ->
  PostgreSQL (Memory Storage)
---

## 🔥 Features

### 🔐 Authentication System
- Secure signup/login
- Password hashing using Argon2
- JWT-based session management

### 💬 Chat System
- Context-aware responses using recent message history
- Conversation tracking via IDs
- Persistent storage in database

### ⚡ Streaming Responses
- Server-Sent Events (SSE)
- Token-by-token response rendering
- Stop generation functionality

### 🧠 AI Integration
- Local LLM via Ollama
- Automatic server startup handling
- Streaming + non-streaming support

### 🖥️ Frontend Experience
- Single Page Application (SPA)
- Animated loader with system states
- Real-time UI updates
- Session persistence via localStorage

---

## 📊 Proof of Work (PoW)

A working demonstration of the system has been recorded.

📹 **Video Proof:**  

## Week 1
<br>


https://github.com/user-attachments/assets/8455e350-4e5a-4cbe-a815-e344b07dc772

## Week 2
<br>


https://github.com/user-attachments/assets/39f46ce2-95d2-4b98-8a98-f4048687d12d

## Week 3


https://github.com/user-attachments/assets/99e635e3-9738-4f43-9bc2-a441ad64abfd

### Current work update(13 May, 2026)


https://github.com/user-attachments/assets/c62c34cf-e494-4bff-b0ff-9fb3c00b0398

Note: Work is still under progress and nearly completed(need to work on agentic logic and front-end integration)

This demonstrates:
- Authentication flow  
- Real-time streaming responses  
- Conversation persistence  
- Full system interaction  

---

## 📁 Project Structure
/backend
main.py
models.py
schemas.py
database.py
auth.py
ai_service.py

/frontend
index.html
styles.css
app.js
## ⚙️ Setup Instructions

### 1. Clone Repository
  git clone [https://github.com/MaharshiShastri/local-llm-fullStack.git](https://github.com/MaharshiShastri/local-llm-fullStack.git)<br>cd local-llm-fullStack 
### 2. Backend Setup
  Install dependencies  pip install fastapi uvicorn sqlalchemy psycopg2 passlib python-jose requests Setup PostgreSQL.<br>Create database: ai_app<br>Update credentials in:    backend/config.py
### 3. Install Ollama & Model
  Download Ollama: https://ollama.com<br>Pull model: ollama pull tinyllama
### 4. Run Backend
  uvicorn backend.main:app --reload
### 5. Run Frontend
  CMD and cd to .\frontend\: python -m http.server 5500
  
### 📌 Current Status
  - Authentication system
  - Chat + streaming
  - Database integration
  - Frontend UI/UX
  - Multi-session management (enhanced)
  - Model optimization
  
### Deployment
- 🔮 Future Work
- 🧠 Fine-tuned models / better LLM integration
- 🌐 Deployment (cloud + local hybrid)
- 📊 Analytics on conversations
- 🧩 Plugin/tool system (Agent capabilities)
- 🗂️ Advanced session/history management
- 🎙️ Voice input/output
- 🧠 Research Direction
  ## This project can evolve into:
    - **Agentic AI systems**
    - **Human-like conversational memory models**
    - **Edge AI + Local LLM ecosystems**
    - **Time-Based Auto Response Generation**
      - Example: Automatically generating and delivering a structured plan of your day before a fixed time (e.g., 6:00 AM)
      - Context-aware scheduling using past behavior, priorities, and ongoing conversations
      - Proactive AI systems that act *before* user input rather than reacting after
    - **Autonomous decision-support systems**
    - **Personalized AI assistants with predictive behavior modeling**
### ⚠️ Notes
  Ollama must be installed locally
  Database must be configured before running
  Current setup is optimized for development, not production


Open to improvements, suggestions, and collaborations.

