"""
Запуск: python create_admin.py
Створює адміністратора або підвищує існуючого користувача до адміна.
"""
from database import SessionLocal, engine
import models_db as models
from auth import get_password_hash

models.Base.metadata.create_all(bind=engine)

EMAIL    = "admin@agrovision.com"   
PASSWORD = "Admin1234!"             
NAME     = "Адміністратор"

db = SessionLocal()
try:
    user = db.query(models.User).filter(models.User.email == EMAIL).first()
    if user:
        user.is_admin  = True
        user.is_active = True
        db.commit()
        print(f"✅ Існуючий користувач {EMAIL} отримав права адміна")
    else:
        user = models.User(
            name=NAME, email=EMAIL,
            hashed_password=get_password_hash(PASSWORD),
            is_admin=True, is_active=True,
        )
        db.add(user); db.commit()
        print(f"✅ Адміна створено: {EMAIL} / {PASSWORD}")
finally:
    db.close()