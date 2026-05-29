from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
import tempfile, os
import ast, json
from database import get_db, engine
import models_db as models
from auth import (
    get_password_hash, verify_password,
    create_access_token, get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from model import run_inference
from s3_storage import upload_image, get_presigned_url, delete_image
from pydantic import BaseModel, validator
import re

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="AgroVision API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ════════════════════════════════════════
#  перевірка адміна
# ════════════════════════════════════════
def require_admin(current_user: models.User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    return current_user


# ════════════════════════════════════════
#  СХЕМИ
# ════════════════════════════════════════
class UserRegister(BaseModel):
    name: str
    email: str
    password: str
    company: str = ""
    phone: str = ""

    @validator("email")
    def validate_email(cls, v):
        if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError("Невірний формат email")
        return v.lower().strip()

    @validator("phone")
    def validate_phone(cls, v):
        if not v:
            return v
        cleaned = re.sub(r'[^\d+]', '', v)
        if not re.match(r'^(\+380\d{9}|0\d{9})$', cleaned):
            raise ValueError("Невірний формат телефону")
        return cleaned

    @validator("password")
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError("Пароль має бути не менше 6 символів")
        return v

    @validator("name")
    def validate_name(cls, v):
        if len(v.strip()) < 2:
            raise ValueError("Ім'я занадто коротке")
        return v.strip()


class Token(BaseModel):
    access_token: str
    token_type: str
    user_name: str
    user_email: str
    is_admin: bool


# ════════════════════════════════════════
#  АВТОРИЗАЦІЯ
# ════════════════════════════════════════
@app.post("/register", response_model=Token)
def register(data: UserRegister, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Цей email вже зареєстровано")

    user = models.User(
        name=data.name, email=data.email,
        company=data.company, phone=data.phone,
        hashed_password=get_password_hash(data.password),
        last_login=datetime.utcnow(),
    )
    db.add(user); db.commit(); db.refresh(user)

    token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": token, "token_type": "bearer",
            "user_name": user.name, "user_email": user.email, "is_admin": user.is_admin}


@app.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(
        models.User.email == form_data.username.lower().strip()
    ).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Невірний email або пароль")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Акаунт деактивовано")

    user.last_login = datetime.utcnow(); db.commit()

    token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": token, "token_type": "bearer",
            "user_name": user.name, "user_email": user.email, "is_admin": user.is_admin}


@app.get("/me")
def get_me(current_user: models.User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "company": current_user.company,
        "phone": current_user.phone,
        "is_admin": current_user.is_admin,
        "created_at": current_user.created_at.strftime("%d.%m.%Y"),
        "last_login": current_user.last_login.strftime("%d.%m.%Y %H:%M") if current_user.last_login else None,
    }


# ════════════════════════════════════════
#  АНАЛІЗ ПОЛЯ
# ════════════════════════════════════════
@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    threshold: float = 0.4,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed = {"image/jpeg", "image/png", "image/tiff", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Дозволені формати: JPG, PNG, TIFF, WEBP")
    suffix = os.path.splitext(file.filename)[-1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        result = run_inference(tmp_path, threshold=threshold)
        s3_key = upload_image(tmp_path, file.filename)
    finally:
        os.unlink(tmp_path) 
    analysis = models.Analysis(
        user_id=current_user.id,
        image_filename=s3_key,          
        original_filename=file.filename,
        anomalies_count=len(result["detections"]),
        result_json=str(result["detections"]),
        threshold=str(threshold),
    )
    db.add(analysis); db.commit(); db.refresh(analysis)

    return {
        "analysis_id": analysis.id,
        "detections": result["detections"],
        "mask_base64": result["mask_base64"],
    }


# ════════════════════════════════════════
#  ІСТОРІЯ 
# ════════════════════════════════════════
@app.get("/history")
def get_history(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    analyses = (
        db.query(models.Analysis)
        .filter(models.Analysis.user_id == current_user.id)
        .order_by(models.Analysis.created_at.desc())
        .all()
    )
    return [_fmt_analysis(a) for a in analyses]


# ════════════════════════════════════════
#  АДМІН
# ════════════════════════════════════════
@app.get("/admin/users")
def admin_get_users(admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    return [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "company": u.company,
            "phone": u.phone,
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "created_at": u.created_at.strftime("%d.%m.%Y"),
            "last_login": u.last_login.strftime("%d.%m.%Y %H:%M") if u.last_login else "—",
            "analyses_count": len(u.analyses),
        }
        for u in users
    ]


@app.patch("/admin/users/{user_id}/toggle-active")
def admin_toggle_active(
    user_id: int,
    admin: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Не можна деактивувати себе")
    user.is_active = not user.is_active
    db.commit()
    return {"id": user.id, "is_active": user.is_active}


@app.delete("/admin/users/{user_id}")
def admin_delete_user(
    user_id: int,
    admin: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Не можна видалити себе")

    # Видаляємо зображення з S3
    for a in user.analyses:
        delete_image(a.image_filename)

    db.delete(user); db.commit()
    return {"detail": "Видалено"}


@app.get("/admin/analyses")
def admin_get_analyses(
    admin: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    analyses = db.query(models.Analysis).order_by(models.Analysis.created_at.desc()).all()
    return [_fmt_analysis(a, include_user=True) for a in analyses]


@app.delete("/admin/analyses/{analysis_id}")
def admin_delete_analysis(
    analysis_id: int,
    admin: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    a = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Аналіз не знайдено")
    delete_image(a.image_filename)
    db.delete(a); db.commit()
    return {"detail": "Видалено"}


# ════════════════════════════════════════
#  
# ════════════════════════════════════════
def _fmt_analysis(a, include_user: bool = False) -> dict:
    
    detections = []
    if a.result_json:
        try:
            detections = ast.literal_eval(a.result_json)
        except Exception:
            try:
                detections = json.loads(a.result_json)
            except Exception:
                detections = []
 
    d = {
        "id": a.id,
        "filename": a.original_filename,
        "date": a.created_at.strftime("%d.%m.%Y %H:%M"),
        "anomalies_count": a.anomalies_count,
        "threshold": a.threshold,
        "image_url": get_presigned_url(a.image_filename),
        "detections": detections,   
    }
    if include_user:
        d["user_name"]  = a.user.name  if a.user else "—"
        d["user_email"] = a.user.email if a.user else "—"
    return d

@app.get("/health")
def health():
    return {"status": "ok"}


_frontend = os.path.join(os.path.dirname(__file__), "../frontend")
if os.path.isdir(_frontend):
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")