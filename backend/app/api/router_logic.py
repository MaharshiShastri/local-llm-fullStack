from fastapi import APIRouter, Depends, HTTPException, status, FastAPI, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from fastapi.responses import StreamingResponse, JSONResponse
from jose import jwt, JWTError
import json
import asyncio
import fitz
import os
import time
import psutil
import logging
import redis
import concurrent.futures

# Internal Imports (User-defined modules and methods)
from database import SessionLocal
from app.schemas.schemas import ChatRequest, ChatResponse, UserAuth, StepApprovalRequest, PlanRequest, StatusUpdate, MemoryCreate
from app.services.ai_service import generate_response, generate_stream, generate_plan
import app.models.models as models
from app.core.auth import hash_password, verify_password, create_access_token, SECRET_KEY, ALGORITHM
from fastapi.security import OAuth2PasswordBearer
from app.services import chat_service, task_service
from app.rag.retriever import rag_retriever
from app.rag.ingestor import ingest_text, get_grounded_context
from app.services.memory_service import get_memories, add_memory, delete_memory, update_memory, extract_and_save_memories
from app.utils.analytics import analytics_engine
from app.services.task_service import trigger_mission_execution
from app.services.tasks import celery, r_client, process_chat_task, process_plan_task

api_router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
failure_logger = logging.getLogger("failure_recorder")
fh = logging.FileHandler("failure.log")
fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
failure_logger.addHandler(fh)

#Start of Helper functions
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


r_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6373/0"))

def get_rag_context(query: str, db: Session, time: int):
    try:
        cpu_load = psutil.cpu_percent()

        result, metrics = rag_retriever.retrieve_context(query, db, load=cpu_load, total_time=time)
                
        if not result:
            return ""
        
        metrics['system_cpu'] = cpu_load
        with open("retrieval_metrics.log", "a") as log_file:
            log_file.write(json.dumps(metrics) + "\n")
            print("RAG Retrieval Metrics:", metrics)
        context_block = "\n--- RELEVANT DOCUMENTS ---\n" + "\n".join(result)
        return context_block
    
    except Exception as e:
        print(f"RAG RETRIEVAL ERROR: {e}")
    return None

def classify_failure(error_type: str, detail: str=""):
    mapping = {
        # --- IDENTITY & SECURITY ---
        "UNAUTHORIZED_ACCESS": {"code": "ERR_AUTH_403", "severity": "CRITICAL", "retry": False},
        "SESSION_EXPIRED": {"code": "ERR_AUTH_401", "severity": "HIGH", "retry": False},
        
        # --- RESOURCE & INFRASTRUCTURE ---
        "RESOURCE_STARVATION": {"code": "ERR_SYS_EXHAUSTED", "severity": "CRITICAL", "retry": True},
        "LLM_LATENCY": {"code": "ERR_OLLAMA_TIMEOUT", "severity": "HIGH", "retry": True},
        
        # --- LOGIC & DATA ---
        "GROUNDING_VIOLATION": {"code": "ERR_FACTUAL_DIVERGENCE", "severity": "CRITICAL", "retry": False},
        "RAG_SILENCE": {"code": "ERR_CONTEXT_MISSING", "severity": "LOW", "retry": True},
        "PLAN_GEN_FAILED": {"code": "ERR_STRUCTURAL_INTEGRITY", "severity": "MEDIUM", "retry": True}
    }
    meta = mapping.get(error_type, {"code": "ERR_UNKNOWN", "severity": "UNKNOWN", "retry": False})
    failure_entry = {
        "error": error_type,
        "code" : meta["code"],
        "detail" : detail,
        "timestamp" : time.time()
    }
    failure_logger.error(json.dumps(failure_entry, indent=4))
    return {"error": meta, "detail": detail, "timestamp": time.time()}

#Retrieve Current user details from token
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    #Recieve the token and check if the ser exists, if user exists, return user details, else return credentials_exception error

    credentials_exception = HTTPException(
        status_code = status.HTTP_401_UNAUTHORIZED,
        detail = "Could not validate credentials",
        headers = {"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.email == email).first()

    if user is None:
        raise credentials_exception

    return user


def validate_input(text: str):
    forbidden_keywords=["IGNORE ALL PREVIOUS INSTRUCTIONS", "SYSTEM_OVERRIDE"]
    if any (key in text.upper() for key in forbidden_keywords):
        raise HTTPException(status_code=403, detail="Instruction Injection Detected")
    
def get_active_mission_context(user_id: int, db: Session):
    active_mission = db.query(models.Tasks).filter(
        models.Tasks.user_id == user_id,
        models.Tasks.status == "pending"
    ).first()

    if active_mission:
        return f"\n[SYSTEM ALERT: The user has an active mission: '{active_mission.task_name}']\n"
    return ""

executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
#End of Helper functions

@api_router.get("/")
def root():
    return {"message": "AI Backend Running"}

#Signup page
@api_router.post("/signup")
def signup(request: UserAuth, db: Session = Depends(get_db)):
    #Check if email already exists, if so, reject, if not then create new user with hashed password and save to database

    existing_user = db.query(models.User).filter(models.User.email == request.email).first()

    if existing_user:
        raise HTTPException(status_code=400, detail= "Email already registered")
    hashed_password = hash_password(request.password)
    new_user = models.User(
        email = request.email,
        password_hash = hashed_password
    )

    db.add(new_user)
    db.commit()
    return {"message" : "User created successfully!"}

#Login Page
@api_router.post("/login")
def login(request: UserAuth, db: Session = Depends(get_db)):
    #Check if user exists, if not raise HTTPexception, if they do, then match their password and email and provide token if
    # valid credentials and return the token to user's localItem 
    user = db.query(models.User).filter(models.User.email == request.email).first()
    
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code = 401, detail = "Invalid Credentials!")
    
    access_token = create_access_token(data={"sub": user.email})
    return ({"access_token": access_token, "token_type": "bearer", "user": {"id": user.id,  "email": user.email}})

#START of Ordinary conversations with AI functions below for web-equivalent CRUD operations
#Update the conversation with new prompt from user(buffererd response used for very initial testing)
"""
@api_router.post("/chat")
def chat(request: ChatRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    #Check if the conversation is presnet, if not then create a new one
    if request.conversation_id:
        conversation = db.query(models.Conversation).filter(
            models.Conversation.id == request.conversation_id
            ).first()
    else:
        conversation = models.Conversation(user_id=current_user.id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    
    try:
        validate_input(request.message)
    except Exception as e:
        return JSONResponse(
            status_code=403, 
            content=classify_failure("UNAUTHORIZED_ACCESS", detail=str(e.detail))
        )

        #Save user message
    user_msg = models.Message(
        conversation_id = conversation.id,
        role="User",
        content = request.message
    )

    db.add(user_msg)
    messages = db.query(models.Message).filter(
    models.Message.conversation_id == conversation.id
).order_by(models.Message.timestamp.desc()).limit(6).all()
    history_text = ""

    for msg in messages:
        if msg.role == "user":
            history_text += f"User: {msg.content}\n"
        else:
            history_text += f"AI: {msg.content}\n"

    full_prompt = history_text + f"User: {request.message}\nAssistant:"
    #GEnerate AI reply
    #ai_reply = await queued_llm(generate_response, full_prompt)
    #ai_reply = generate_response(full_prompt)

    #Save AI reply
    ai_msg = models.Message(
        conversation_id = conversation.id,
        role="LLM",
        content = ai_reply
    )

    db.add(ai_msg)
    db.commit()

    return {"response": ai_reply, "conversation_id": conversation.id}"""

#Read opearation of web-equivalent(GET) for all conversations
@api_router.get("/conversation/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    #Retrieve a list of conversations of the user, based on matching the conversation's user id and user's id, 
    # retrieve the previous messages by matching conversation id of database and request.
    conversation = db.query(models.Message).filter(
        models.Conversation.id == conversation_id,
        models.Conversation.user_id == current_user.id
        ).first()
    
    if not conversation:
        return JSONResponse(
            status_code=403, 
            content=classify_failure("UNAUTHORIZED_ACCESS", "This conversation belongs to another user profile.")
        )
    
    messages = db.query(models.Message).filter(
        models.Message.conversation_id == conversation_id,
        models.Conversation.user_id == current_user.id
        ).order_by(models.Message.timestamp.asc()).all()

    return [
        {
            "role": msg.role.lower(),
            "content": msg.content,
            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None
        }
        for msg in messages
    ]
@api_router.post("/chat-stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user), bg_tasks: BackgroundTasks = BackgroundTasks()):
    
    if not current_user:
        raise HTTPException(status_code=401, detail="User session invalid")

    # 1. Handle Conversation Creation/Lookup
    if not request.conversation_id or request.conversation_id == "null":
        temp_title = request.message[:30] + "..." if len(request.message) > 30 else request.message
        new_conv = models.Conversation(title=temp_title, user_id=current_user.id)
        db.add(new_conv)
        db.commit()
        db.refresh(new_conv)
        conv_id = new_conv.id
    else:
        conv_id = int(request.conversation_id)
    try:
        validate_input(request.message)
    except Exception as e:
        return JSONResponse(
            status_code=403, 
            content=classify_failure("UNAUTHORIZED_ACCESS", detail=str(e.detail))
        )
    
    # 2. RETRIEVE CONTEXT 
    # Use the retriever as the single source for RAG context
    try:
        doc_context = get_rag_context(request.message, db, time=50000)
        #print(doc_context[:10])
        if not doc_context and request.message.startswith("@doc"):
            print(classify_failure("RAG_SILENCE", "Query Explicitly requested docs but not found."))
        mission_context = get_active_mission_context(current_user.id, db)
    except Exception as e:
        return JSONResponse(status_code=500, content=classify_failure("DB_CONTENT", str(e)))

    # 3. Save User Message
    chat_service.save_message(db, conv_id, "user", request.message)
    
    # 4. Get User Memories
    memories = get_memories(db, current_user.id)
    memory_context = ""
    if memories:
        memory_context = "USER FACTS:\n" + "\n".join(
            [f"-[{m.category}] {m.fact_key}: {m.fact_value}" for m in memories if m.importance >= 3]
        )
        
    # 5. Build History
    history = chat_service.build_chat_history(db, conv_id)
    
    # 6. Construct Final Prompt (Unified Context)
    # We use doc_context here which contains the actual text from your PDF chunks
   
    process_chat_task.delay(conv_id, f"{mission_context}\n{memory_context}\n{doc_context}\n{history}\nUser: {request.message}")

    async def stream_generator():
        pubsub = r_client.pubsub()
        channel = f"chat_stream_{conv_id}"
        print("Listening to Redis channel: ", channel)
        pubsub.subscribe(channel)
        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages = True)
                 
                if message is not None:
                    
                    print("Type of message['data']:", type(message['data']))   
                    token = message['data']
                    
                    if token == b'[DONE]'or token == '[DONE]':
                        break

                    if isinstance(token, bytes):
                        token = token.decode('utf-8')
                    yield f"data: {json.dumps({'payload': token})}\n\n"                
                await asyncio.sleep(0.005)

        finally:
            pubsub.unsubscribe(channel)
            pubsub.close()
            
    return StreamingResponse(stream_generator(), media_type="text/event-stream")
#Read of web-quivalent method
@api_router.get('/conversations')
def get_user_conversations(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    #Retrieve a list of conversations for the sidebar to give users the chance to go back to jumpt between conversations
    conversations = db.query(models.Conversation).filter(
        models.Conversation.user_id == current_user.id
    ).order_by(models.Conversation.id.desc()).all()

    return [
        {
            "id": conversation.id,
            "title": conversation.title if conversation.title else f"Conversation {conversation.id}",
            "created_at": conversation.timestamp.isoformat() if hasattr(conversation, 'timestamp') else None
        }
        for conversation in conversations
    ]

#Delete of web-equivalent method    
@api_router.delete("/conversation/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    #Check if the conversation_id is present in DB, if not then raise an error,
    #If present, then delete the conversation along with messages of the converation(via enabling CASCADE)
    conv = db.query(models.Conversation).filter(
        models.Conversation.user_id == current_user.id,
        models.Conversation.id == conversation_id
    ).first()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied")
    
    db.delete(conv)
    db.commit()
    return{"message": "Conversation deleted successfully!"}

#Update of web-equivalent method
@api_router.patch("/conversation/{conversation_id}")
def update_title(conversation_id: int, title: str, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    #Check if the retreieved id present, if present then rename, if not then raise HTTPException
    conv = db.query(models.Conversation).filter(
        models.Conversation.user_id == current_user.id,
        models.Conversation.id == conversation_id
    ).first()
    
    validate_input(title)

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied")
    
    conv.title = title
    db.commit()
    return {"title": conv.title, "id": conversation_id}
#END of Ordinary conversations with AI functions below for web-equivalent CRUD operations
#START of Agentic AI with time-awareness engine conversations with functions below for web-equivalent CRUD operations
#Read function of web-equivalent method
@api_router.get("/tasks")
def get_tasks(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    #Return a list of previously given task to access them
    return db.query(models.Tasks).filter(models.Tasks.user_id == current_user.id).order_by(models.Tasks.created_at.desc()).all()

#Delete function of web-equivalent
@api_router.delete("/task/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    #Delete a task based on task_id recieved from user, if such task does not exist, then return a raise HTTPException
    task = db.query(models.Tasks).filter(
        models.Tasks.user_id == current_user.id,
        models.Tasks.id == task_id
    ).first()
    if not task:
        raise HTTPException(status_code = 404, detail="Task not found or access denied")

    db.delete(task)
    db.commit()
    return {"message": "Task deleted successfully!"}
#Create function of web-equivalent method
@api_router.post("/plan")
async def create_execution_plan(request: PlanRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    
    try:
        validate_input(request.task)
    except Exception as e:
        return JSONResponse(
            status_code=403, 
            content=classify_failure("UNAUTHORIZED_ACCESS", detail=str(e.detail))
        )
    
    async def validate_and_correct_steps(steps, total_budget):
        if len(steps) < 5:
            logger.warning(f"Guardrail Trigerred: Only {len(steps)} steps. Padding Plan")
            while len(steps) < 5:
                steps.append({"step": "Additional validation and review", "time_allocated": 0})
        elif len(steps) > 7:
            logger.warning(f"Guardrail Triggered: {len(steps)} steps. Compressing plan.")
            steps = steps[:7]
        
        for s in steps:
            if s.get("time_allocated", 0) <= 0:
                s["time_allocated"] = total_budget // len(steps)

        actual_sum = sum(step.get("time_allocated", 0) for step in steps)

        if actual_sum > total_budget:
            # Scale all steps down proportionally instead of just nuking the last one
            ratio = total_budget / actual_sum
            for s in steps:
                s["time_allocated"] = max(10, int(s["time_allocated"] * ratio))

        return steps
        
    
    context = get_rag_context(request.task, db, time=request.time_budget)
    
    process_plan_task.delay(request.task, request.time_budget, request.mode, current_user.id, context)

    async def plan_generator():
        pubsub = r_client.pubsub()
        channel = f"plan_result_{current_user.id}"
        print("Listening to Redis channel for plan results: ", channel)
        pubsub.subscribe(channel)
        try:
            yield f"data: {json.dumps({'status': 'initializing', 'message': 'Generating mission strategy...'})}\n\n"
            start_wait = time.time()
            while True:
                message =pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is not None:
                    data = message['data']
                    if isinstance(data, bytes):
                        data = data.decode('utf-8')
                    
                    # This is the final JSON payload from the worker
                    yield f"data: {data}\n\n"
                    break # We received the plan, we can close the stream
                
                # Safety timeout (60 seconds)
                if time.time() - start_wait > 60:
                    yield f"data: {json.dumps({'status': 'error', 'message': 'Plan generation timed out'})}\n\n"
                    break
                    
                await asyncio.sleep(0.1)
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            pubsub.unsubscribe(channel)
            pubsub.close()

    return StreamingResponse(plan_generator(), media_type="text/event-stream")

#Update function of web-equivalent
@api_router.patch("/task/{task_id}")
def update_task_status(task_id: int, data: StatusUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    #Update the task status, whether it is "pending" or "completed", if such a task exists, if no such task exists then 
    #return a HTTPException
    task = db.query(models.Tasks).filter(
        models.Tasks.user_id == current_user.id,
        models.Tasks.id == task_id 
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = data.status 
    
    db.commit()
    return {"status": task.status}

#Read funtion of web-equivalent
@api_router.get("/execute/{mission_id}")
async def start_execution(mission_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    #Once the step is approved, execute it here, remove from current list of steps
    #Do this until the entire task list is completed

    task = db.query(models.Tasks).filter(models.Tasks.id == mission_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Mission not found")

    if task.user_id != current_user.id:
        logger.warning(f"SECURITY ALERT: User {current_user.id} tried to access Task {mission_id}")
        return JSONResponse(
            status_code=403, 
            content=classify_failure("UNAUTHORIZED_ACCESS", "Mission ownership mismatch.")
        )
    steps = db.query(models.TaskStep).filter(models.TaskStep.task_id == mission_id).all()
    manifest = [
        {
            "id": s.id,
            "backend_step_id": s.backend_step_id, # Changed from step_id
            "description": s.description, 
            "time_allocated": s.time_allocated,
            "status": s.status,
            "artifact_content": "",
            "tool_required": s.tool_required,
            "reasoning": s.logic_reasoning
        }
        for s in steps
    ]
    task_id = trigger_mission_execution(db, mission_id, task.total_time, manifest)
    return {
        "status": "QUEUED",
        "mission_id": mission_id,
        "celery_task_id": task_id,
        "message": "Mission execution moved to background worker."
    }

@api_router.get("execute/status/{task_id}")
async def get_mission_status(task_id: str):
    task_result = celery.AsyncResult(task_id)
    progress_data = task_result.info if isinstance(task_result.info, dict) else {"message": str(task_result.info)}
    
    return {
        "task_id": task_id,
        "state": task_result.state, 
        "data": progress_data
    }

    return response
@api_router.patch("/execute/{mission_id}/approve")
async def approve_mission_step(mission_id: int, data: StepApprovalRequest, db: Session = Depends(get_db)):
    step_id = str(data.step_id)
    state_key = f"mission_state:{mission_id}"
    r_client.hset(state_key, f"{step_id}_status", data.status)
    
    def sync_db_approval(db, mission_id, step_id, data):
        step_db = db.query(models.TaskStep).filter(
            models.TaskStep.task_id == mission_id,
            models.TaskStep.backend_step_id == step_id
        ).first()
        if step_db:
            step_db.status = data.status
            if data.description:
                step_db.description = data.description
            db.commit()

    try:
        validate_input(data.description)
    except Exception as e:
       return JSONResponse(
        status_code=403, 
        content=classify_failure("UNAUTHORIZED_ACCESS", detail=str(e.detail))
    )
    if data.description:
        r_client.hset(state_key, f"{step_id}_desc", data.description)
    
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(executor, lambda: sync_db_approval(db, mission_id, step_id, data))

    approval_channel = f"mission_approval_{mission_id}"
    payload = json.dumps({"action": "RESUME", "step_id": data.step_id})
    r_client.publish(approval_channel, payload)

    return {"status": "Step Approved", "mission_id": mission_id}

#Kill switch for the Agentic ai
@api_router.post("/execute/cancel/{task_id}")
async def cancel_mission_execution(task_id: str):
    try:
        # 'terminate=True' sends a SIGTERM to the child process executing the task
        # 'signal="SIGKILL"' can be used if you want a more forceful shutdown
        celery.control.revoke(task_id, terminate=True, signal="SIGKILL")
        
        return {
            "status": "success",
            "message": f"Termination signal sent to task {task_id}",
            "task_id": task_id
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to issue kill command: {str(e)}"
        )
#End of Agentic AI with time-awareness engine conversations with functions below for web-equivalent CRUD operations
#START of Memory Vault functions for web-equivalent CRUD operations
@api_router.get("/memories")
def read_memories(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return get_memories(db, current_user.id)

@api_router.post("/memory")
def add_user_memory(request: MemoryCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    try:
        validate_input(request.fact_key)
        validate_input(request.fact_value)
    except Exception as e:
        return JSONResponse(
            status_code=403,
            content=classify_failure("UNAUTHORIZED_ACCESS", detail=str(e.detail))
        )
    
    new_memory = add_memory(
        db,
        user_id = current_user.id,
        fact_key = request.fact_key,
        fact_value = request.fact_value,
        importance = request.importance,
        category = request.category
    )
    return new_memory

@api_router.delete("/memory/{memory_id}")
def delete_user_memory(memory_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    success = delete_memory(db, current_user.id, memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found or access denied")
    
    return {"message": "memory purged successfully!"}

@api_router.patch("/memory/{memory_id}")
def update_user_memory(memory_id: int, updates: MemoryCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    try:
        validate_input(updates.fact_key)
        validate_input(updates.fact_value)
    except Exception as e:
        return JSONResponse(
            status_code=403,
            content=classify_failure("UNAUTHORIZED_ACCESS", detail=str(e.detail))
        )
    
    updated_memory = update_memory(
        db,
        user_id = current_user.id,
        memory_id = memory_id,
        updates = updates.dict(exclude_unset=True)
    )
    if not updated_memory:
        raise HTTPException(status_code=404, detail="Memory not found or access denied")
    
    return updated_memory


@api_router.post("/upload-doc")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    contents = await file.read()
    doc = fitz.open(stream=contents, filetype="pdf")

    full_text = ""
    for page in doc:
        full_text += page.get_text()

    result = ingest_text(db, title=file.filename, raw_text=full_text, user_id=current_user.id, source_type="pdf")

    return {"message": "Document ingested successfully!", "details": result}

@api_router.post("/mission/{mission_id}/archive-logs")
async def archive_logs(mission_id: int, data: dict):
    log_dir = "logs/missions"
    os.makedirs(log_dir, exist_ok=True)
    
    file_path = f"{log_dir}/mission_{mission_id}.txt"
    with open(file_path, "a") as f:
        f.write(f"\n--- SESSION ARCHIVE: {time.ctime()} ---\n")
        f.write(data['terminal_output'])
        f.write("\n--- END OF SESSION ---\n")
        
    return {"status": "archived", "path": file_path}

@api_router.get("/system/stats")
def get_stats(current_user: models.User = Depends(get_current_user)):
    return analytics_engine.get_system_kpis()
