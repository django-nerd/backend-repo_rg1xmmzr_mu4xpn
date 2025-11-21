import os
from datetime import datetime
from typing import Optional, List, Literal
from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from bson import ObjectId
from hashlib import sha256

from database import db, create_document, get_documents
from schemas import User, Task, Report, SalaryPayment, FinanceRecord

app = FastAPI(title="Company Operations API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------- Utils -------------------
SECRET = os.getenv("APP_SECRET", "change-me-secret")

def oid(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    return obj


def serialize_doc(doc: dict):
    if not doc:
        return doc
    out = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def user_collection():
    return db["user"]


def hash_password(password: str) -> str:
    return sha256(password.encode()).hexdigest()


def make_token(email: str, password_hash: str) -> str:
    raw = f"{email}:{password_hash}:{SECRET}"
    return sha256(raw.encode()).hexdigest() + ":" + email


def parse_token(token: str) -> Optional[str]:
    # token format: hexhash:email
    if not token or ":" not in token:
        return None
    _hash, email = token.split(":", 1)
    return email

class AuthUser(BaseModel):
    email: EmailStr
    role: Literal["employee", "core"]
    name: str

async def get_current_user(authorization: Optional[str] = Header(None)) -> AuthUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    email = parse_token(token)
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = user_collection().find_one({"email": email, "is_active": True})
    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    # verify token signature
    expected = make_token(user["email"], user["password_hash"]).split(":", 1)[0]
    if token.split(":", 1)[0] != expected:
        raise HTTPException(status_code=401, detail="Invalid token signature")
    return AuthUser(email=user["email"], role=user["role"], name=user.get("name", ""))

# ------------------- Health -------------------
@app.get("/")
def read_root():
    return {"message": "Company Operations Backend Running"}

@app.get("/test")
def test_database():
    response = {
      "backend": "✅ Running",
      "database": "❌ Not Available",
      "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
      "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
      "connection_status": "Not Connected",
      "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

# ------------------- Auth -------------------
class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: Literal["employee", "core"] = "employee"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    token: str
    user: AuthUser

@app.post("/auth/register", response_model=AuthUser)
def register_user(payload: RegisterRequest, current: Optional[AuthUser] = Depends(lambda: None)):
    # Rule: allow creating the very first core user without auth.
    users_count = user_collection().count_documents({})
    if users_count > 0:
        # If there are users already, only core can create new users
        if current is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if current.role != "core":
            raise HTTPException(status_code=403, detail="Only core can create users")
    # Prevent duplicate email
    if user_collection().find_one({"email": payload.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = User(
        name=payload.name,
        email=payload.email,
        role=payload.role,
        password_hash=hash_password(payload.password),
        is_active=True,
    ).model_dump()
    create_document("user", doc)
    return AuthUser(email=payload.email, role=payload.role, name=payload.name)

@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    user = user_collection().find_one({"email": payload.email, "is_active": True})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user["password_hash"] != hash_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = make_token(user["email"], user["password_hash"])
    return TokenResponse(token=token, user=AuthUser(email=user["email"], role=user["role"], name=user.get("name", "")))

@app.get("/me", response_model=AuthUser)
def me(current: AuthUser = Depends(get_current_user)):
    return current

# ------------------- Tasks -------------------
class CreateTaskRequest(BaseModel):
    title: str
    description: Optional[str] = None
    assignee_email: EmailStr
    due_date: Optional[str] = None  # ISO date

class UpdateTaskRequest(BaseModel):
    status: Optional[Literal["pending", "in_progress", "done"]] = None
    title: Optional[str] = None
    description: Optional[str] = None

@app.post("/tasks")
def create_task(payload: CreateTaskRequest, current: AuthUser = Depends(get_current_user)):
    if current.role != "core":
        raise HTTPException(status_code=403, detail="Only core can create tasks")
    data = Task(
        title=payload.title,
        description=payload.description,
        assignee_email=payload.assignee_email,
        status="pending",
        due_date=None,
    ).model_dump()
    # store due_date if provided (string)
    if payload.due_date:
        data["due_date"] = payload.due_date
    inserted_id = create_document("task", data)
    doc = db["task"].find_one({"_id": ObjectId(inserted_id)})
    return serialize_doc(doc)

@app.get("/tasks")
def list_tasks(current: AuthUser = Depends(get_current_user), assignee: Optional[EmailStr] = Query(None)):
    q = {}
    if current.role == "employee":
        q["assignee_email"] = current.email
    else:
        if assignee:
            q["assignee_email"] = str(assignee)
    docs = get_documents("task", q)
    return [serialize_doc(d) for d in docs]

@app.patch("/tasks/{task_id}")
def update_task(task_id: str, payload: UpdateTaskRequest, current: AuthUser = Depends(get_current_user)):
    try:
        _id = ObjectId(task_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid task id")
    doc = db["task"].find_one({"_id": _id})
    if not doc:
        raise HTTPException(status_code=404, detail="Task not found")
    if current.role == "employee" and doc.get("assignee_email") != current.email:
        raise HTTPException(status_code=403, detail="Not allowed")
    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not updates:
        return serialize_doc(doc)
    updates["updated_at"] = datetime.utcnow()
    db["task"].update_one({"_id": _id}, {"$set": updates})
    doc = db["task"].find_one({"_id": _id})
    return serialize_doc(doc)

# ------------------- Reports -------------------
class CreateReportRequest(BaseModel):
    date: str
    summary: str
    hours_worked: float

@app.post("/reports")
def create_report(payload: CreateReportRequest, current: AuthUser = Depends(get_current_user)):
    if current.role != "employee":
        raise HTTPException(status_code=403, detail="Only employees can submit reports")
    data = Report(
        employee_email=current.email,
        report_date=datetime.fromisoformat(payload.date).date(),
        summary=payload.summary,
        hours_worked=payload.hours_worked,
    ).model_dump()
    inserted_id = create_document("report", data)
    doc = db["report"].find_one({"_id": ObjectId(inserted_id)})
    return serialize_doc(doc)

@app.get("/reports")
def list_reports(current: AuthUser = Depends(get_current_user), employee: Optional[EmailStr] = Query(None)):
    q = {}
    if current.role == "employee":
        q["employee_email"] = current.email
    else:
        if employee:
            q["employee_email"] = str(employee)
    docs = get_documents("report", q)
    return [serialize_doc(d) for d in docs]

# ------------------- Salary -------------------
class CreateSalaryRequest(BaseModel):
    employee_email: EmailStr
    amount: float
    month: str
    notes: Optional[str] = None
    status: Literal["pending", "paid"] = "paid"

@app.post("/salary")
def create_salary(payload: CreateSalaryRequest, current: AuthUser = Depends(get_current_user)):
    if current.role != "core":
        raise HTTPException(status_code=403, detail="Only core can create salary records")
    data = SalaryPayment(**payload.model_dump()).model_dump()
    inserted_id = create_document("salarypayment", data)
    doc = db["salarypayment"].find_one({"_id": ObjectId(inserted_id)})
    return serialize_doc(doc)

@app.get("/salary")
def list_salary(current: AuthUser = Depends(get_current_user), employee: Optional[EmailStr] = Query(None)):
    q = {}
    if current.role == "employee":
        q["employee_email"] = current.email
    else:
        if employee:
            q["employee_email"] = str(employee)
    docs = get_documents("salarypayment", q)
    return [serialize_doc(d) for d in docs]

# ------------------- Finance (core only) -------------------
class CreateFinanceRequest(BaseModel):
    kind: Literal["revenue", "expense"]
    amount: float
    category: str
    description: Optional[str] = None
    reference: Optional[str] = None

@app.post("/finance")
def create_finance(payload: CreateFinanceRequest, current: AuthUser = Depends(get_current_user)):
    if current.role != "core":
        raise HTTPException(status_code=403, detail="Only core can add finance records")
    data = FinanceRecord(**payload.model_dump()).model_dump()
    inserted_id = create_document("financerecord", data)
    doc = db["financerecord"].find_one({"_id": ObjectId(inserted_id)})
    return serialize_doc(doc)

@app.get("/finance")
def list_finance(current: AuthUser = Depends(get_current_user)):
    if current.role != "core":
        raise HTTPException(status_code=403, detail="Only core can view finance records")
    docs = get_documents("financerecord", {})
    return [serialize_doc(d) for d in docs]

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
