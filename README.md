# AgroVision

Веб-застосунок для аналізу сільськогосподарських знімків із використанням комп'ютерного зору (SegFormer-B2).

## Датасет

Модель навчалась на **[Agriculture-Vision](https://agriculture-vision.intelinair.com/)** — великому датасеті аерофотознімків сільськогосподарських угідь США.

## Вимоги

- Python 3.10+
- PostgreSQL
- AWS S3 bucket (для зберігання зображень)

## Запуск локально

### 1. Клонувати репозиторій

```bash
git clone <repo-url>
cd AGRO/backend
```

### 2. Створити віртуальне середовище

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
```

### 3. Встановити залежності

```bash
pip install -r requirements.txt
```

### 4. Налаштувати змінні середовища

Скопіюй `.env.example` і заповни своїми значеннями:

```bash
cp .env.example .env
```

Відредагуй `.env`:

```env
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/agrovision
SECRET_KEY=your-secret-key-here
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_BUCKET_NAME=...
AWS_REGION=...
```

### 5. Запустити сервер

```bash
uvicorn main:app --reload
```

API буде доступне на `http://localhost:8000`.  
Документація: `http://localhost:8000/docs`

### 6. Створити адміністратора

```bash
python create_admin.py
```

> Перед запуском змініть email і пароль у `create_admin.py`

## Тести

```bash
cd ..
pytest tests/
```
