import uuid
from datetime import datetime
from fastapi import HTTPException, Header, Depends, APIRouter, status
from pydantic import BaseModel

router = APIRouter()

# Simple in‑memory user store – replace with real DB later
USERS = {"player1": "password1"}
SESSIONS = {}
PLAYER_STATE = {}

class LoginRequest(BaseModel):
    username: str
    password: str

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or malformed token")
    token = authorization.split(" ")[1]
    session = SESSIONS.get(token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return session["username"]

@router.post("/login")
async def login(req: LoginRequest):
    if USERS.get(req.username) != req.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = str(uuid.uuid4())
    SESSIONS[token] = {"username": req.username, "created": datetime.utcnow()}
    return {"access_token": token, "token_type": "bearer"}



