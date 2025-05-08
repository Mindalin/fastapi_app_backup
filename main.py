import os
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Body
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import logging
from fastapi.openapi.utils import get_openapi
from sqlalchemy.orm import Session, joinedload
from database import engine, SessionLocal, get_db
from schemas import UserCreate, UserResponse, Token, LoginData, OrderItemCreate, OrderItemCreateByName
from crud import (
    create_user, get_order_by_identifier, get_product_by_id, get_client_by_id,
    search_clients_by_name, search_products_by_name, update_client_by_name,
    update_product_by_name, update_order_by_identifier, 
    delete_item_from_order, update_item_quantity, add_item_to_order_by_name,
    update_item_quantity_by_name, create_order_by_form, get_orders, wrap_text, generate_receipt  # Добавляем get_orders
)
import models
from auth import create_access_token, verify_password, get_current_user
import schemas
from datetime import date, datetime
from fastapi.security import OAuth2PasswordRequestForm
from PIL import Image
import crud
import json

from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.DEBUG)

# Папка для хранения изображений
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Папка для хранения чеков
RECEIPTS_DIR = Path("receipts")
RECEIPTS_DIR.mkdir(exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем папку uploads как статическую
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

models.Base.metadata.create_all(bind=engine)

# Функция для изменения размера изображения
def resize_image(file_path: Path, size: tuple = (300, 300)):
    with Image.open(file_path) as img:
        img.thumbnail(size, Image.Resampling.LANCZOS)
        new_img = Image.new("RGB", size, (255, 255, 255))
        offset = ((size[0] - img.size[0]) // 2, (size[1] - img.size[1]) // 2)
        new_img.paste(img, offset)
        new_img.save(file_path)

@app.get("/")
def root():
    return {"message": "API работает!"}

@app.post("/register", response_model=UserResponse)
def register_user(
    user: UserCreate,
    current_user: models.User = Depends(get_current_user),  # Проверяем авторизацию
    db: Session = Depends(get_db)
):
    # Проверяем, что текущий пользователь — администратор
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can register new users")

    # Проверяем, не существует ли уже пользователь с таким именем
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    # Создаём нового пользователя
    return create_user(db, user)

@app.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Неверный логин или пароль")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me")
def read_users_me(current_user: models.User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "middle_name": current_user.middle_name
    }

@app.delete("/users/{user_id}", response_model=schemas.UserResponse)
def delete_user_endpoint(user_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this user")
    db_user = crud.delete_user(db, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

@app.delete("/users/by-username/{username}", response_model=schemas.UserResponse)
def delete_user_by_username_endpoint(username: str, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.username != username:
        raise HTTPException(status_code=403, detail="Not authorized to delete this user")
    db_user = crud.delete_user_by_username(db, username)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

@app.delete("/users/all")
def delete_all_users(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    result = crud.delete_all_users(db)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to delete all users")
    return {"message": "All users deleted, ID sequence reset"}

@app.post("/orders", response_model=schemas.OrderResponse)
def create_order(
    order: schemas.OrderCreate = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    return crud.create_order(db, order)

@app.post("/orders/by-form", response_model=schemas.OrderResponse)
async def create_order_by_form(
    client_first_name: str = Form(...),
    client_last_name: str = Form(...),
    status: schemas.OrderStatusEnum = Form(...),
    items: str = Form(...),  # Принимаем как строку
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Парсим items как JSON
    try:
        items_list = json.loads(items)
        if not isinstance(items_list, list):
            raise ValueError("Items should be a list")
        items_objects = [schemas.OrderItemCreateByName(**item) for item in items_list]
    except (json.JSONDecodeError, ValueError) as e:
        error_message = "Invalid items format: " + str(e) + ". Expected a JSON list of objects, e.g., [{\"product_name\": \"Product\", \"quantity\": 1}]"
        raise HTTPException(status_code=400, detail=error_message)
    
    return crud.create_order_by_form(db, client_first_name, client_last_name, status, items_objects)

@app.post("/products", response_model=schemas.ProductResponse)
async def create_product(
    name: str = Form(...),
    price: float = Form(...),
    stock: int = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    file_path = UPLOAD_DIR / image.filename
    with file_path.open("wb") as f:
        content = await image.read()
        f.write(content)
    resize_image(file_path, size=(300, 300))
    
    db_product = crud.create_product(db, name=name, image_path=str(file_path), price=price, stock=stock)
    return db_product

@app.put("/products/by-name", response_model=schemas.ProductResponse)
async def update_product_by_name(
    request: str = Form(...),  # Принимаем request как строку
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Парсим request как JSON
    try:
        # Удаляем лишние пробелы и переносы строк
        request = request.strip()
        if not request:
            raise ValueError("Request cannot be empty")
        request_data = json.loads(request)
        request_obj = schemas.ProductUpdate(**request_data)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid JSON format in 'request': {str(e)}. Expected a JSON object, e.g., {{\"name\": \"Product\", \"new_stock\": 10}}"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Проверяем, есть ли изменения
    if not any([request_obj.new_name, request_obj.new_price is not None, request_obj.new_stock is not None]):
        raise HTTPException(status_code=400, detail="No changes provided")
        
    db_product = crud.update_product_by_name(
        db,
        name=request_obj.name,
        new_name=request_obj.new_name,
        new_image_path=None,
        new_price=request_obj.new_price,
        new_stock=request_obj.new_stock
    )
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_product

@app.delete("/products/by-name", response_model=schemas.ProductResponse)
async def delete_product_by_name(
    name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    db_product = crud.delete_product_by_name(db, name)
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_product

@app.put("/products/by-name/image", response_model=schemas.ProductResponse)
async def update_product_image_by_name(
    name: str = Form(...),
    image: UploadFile = File(...),  # Обязательное поле для загрузки изображения
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Находим продукт по имени
    db_product = crud.update_product_by_name(
        db,
        name=name,
        new_name=None,
        new_image_path=None,  # Временно передаём None, обновим позже
        new_price=None,
        new_stock=None
    )
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Сохраняем старый путь к изображению для удаления
    old_image_path = db_product.image if db_product.image else None
    
    # Сохраняем новое изображение
    file_path = UPLOAD_DIR / image.filename
    with file_path.open("wb") as f:
        content = await image.read()
        f.write(content)
    resize_image(file_path, size=(300, 300))
    new_image_path = str(file_path)
    
    # Обновляем путь к изображению в базе данных
    db_product.image = new_image_path
    db.commit()
    db.refresh(db_product)
    
    # Удаляем старое изображение с сервера, если оно существует
    if old_image_path:
        try:
            old_file_path = Path(old_image_path)
            if old_file_path.exists() and old_file_path.is_file():
                old_file_path.unlink()  # Удаляем старый файл
        except Exception as e:
            # Логируем ошибку, но не прерываем выполнение
            print(f"Failed to delete old image {old_image_path}: {str(e)}")
    
    return db_product

@app.put("/products/{product_id}", response_model=schemas.ProductResponse)
async def update_product(
    product_id: int,
    name: Optional[str] = Form(None),
    price: Optional[float] = Form(None),
    stock: Optional[int] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    image_path = None
    if image is not None:
        file_path = UPLOAD_DIR / image.filename
        with file_path.open("wb") as f:
            content = await image.read()
            f.write(content)
        resize_image(file_path, size=(300, 300))
        image_path = str(file_path)
    
    db_product = crud.update_product(
        db,
        product_id=product_id,
        name=name,
        image_path=image_path,
        price=price,
        stock=stock
    )
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_product

@app.delete("/products/{product_id}", response_model=schemas.ProductResponse)
def delete_product(product_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_product = crud.delete_product(db, product_id)
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_product

@app.get("/products", response_model=List[schemas.ProductResponse])
def get_products(skip: int = 0, limit: int = 10, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_products(db, skip, limit)

@app.post("/clients", response_model=schemas.ClientResponse)
async def create_client(
    first_name: str = Form(...),
    last_name: str = Form(...),
    middle_name: str = Form(...),
    birth_date: str = Form(...),
    phone: str = Form(...),
    address: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    try:
        birth_date_parsed = date.fromisoformat(birth_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid birth_date format. Use YYYY-MM-DD")
    
    client = schemas.ClientCreate(
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        birth_date=birth_date_parsed,
        phone=phone,
        address=address
    )
    return crud.create_client(db, client)

@app.put("/clients/by-name", response_model=schemas.ClientResponse)
async def update_client_by_name(
    request: schemas.ClientUpdateRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not request.first_name and not request.last_name:
        raise HTTPException(status_code=400, detail="At least one search parameter (first_name or last_name) is required")

    # Проверяем, есть ли изменения
    changes = [
        request.new_first_name,
        request.new_last_name,
        request.new_middle_name,
        request.new_birth_date,
        request.new_phone,
        request.new_address
    ]
    if not any(changes):
        raise HTTPException(status_code=400, detail="No changes provided")

    new_birth_date_parsed = None
    if request.new_birth_date:
        try:
            new_birth_date_parsed = date.fromisoformat(request.new_birth_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid birth_date format. Use YYYY-MM-DD")

    db_client = crud.update_client_by_name(
        db,
        first_name=request.first_name,
        last_name=request.last_name,
        new_first_name=request.new_first_name,
        new_last_name=request.new_last_name,
        new_middle_name=request.new_middle_name,
        new_birth_date=new_birth_date_parsed,
        new_phone=request.new_phone,
        new_address=request.new_address
    )
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found")
    return db_client

@app.put("/clients/{client_id}", response_model=schemas.ClientResponse)
def update_client(client_id: int, client: schemas.ClientCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_client = crud.update_client(db, client_id, client)
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found")
    return db_client


@app.delete("/clients/by-name", response_model=schemas.ClientResponse)
async def delete_client_by_name(
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not first_name and not last_name:
        raise HTTPException(status_code=400, detail="At least one of first_name or last_name must be provided")
    
    db_client = crud.delete_client_by_name(db, first_name=first_name, last_name=last_name)
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found")
    return db_client

@app.delete("/clients/{client_id}", response_model=schemas.ClientResponse)
def delete_client(client_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_client = crud.delete_client(db, client_id)
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found")
    return db_client

@app.get("/clients", response_model=List[schemas.ClientResponse])
def get_clients(skip: int = 0, limit: int = 10, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_clients(db, skip, limit)

@app.get("/orders", response_model=List[schemas.OrderResponse])
def get_orders(skip: int = 0, limit: int = 10, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_orders(db, skip, limit)

@app.get("/orders/{order_id}", response_model=schemas.OrderResponse)
def get_order(order_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db_order = crud.get_order(db, order_id)
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order

@app.post("/orders/by-identifier/{identifier}/items", response_model=schemas.OrderResponse)
async def add_item_to_order(
    identifier: str,
    product_name: str = Form(...),
    quantity: int = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    print(f"Received: identifier={identifier}, product_name={product_name}, quantity={quantity}, type={type(quantity)}")
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    
    item = schemas.OrderItemCreateByName(product_name=product_name, quantity=quantity)
    db_order = crud.add_item_to_order_by_name(db, identifier, item)
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Удаляем старый чек и генерируем новый
    receipt_path = RECEIPTS_DIR / f"{identifier}_receipt.pdf"
    if receipt_path.exists():
        try:
            receipt_path.unlink()
            print(f"Старый чек для заказа {identifier} удалён")
        except Exception as e:
            print(f"Не удалось удалить старый чек для заказа {identifier}: {str(e)}")
    try:
        generate_receipt(identifier, db)
    except Exception as e:
        print(f"Не удалось сгенерировать новый чек для заказа {identifier} после добавления товара: {str(e)}")

    return db_order

@app.get("/search/orders/{identifier}", response_model=schemas.OrderResponse)
def search_order_by_identifier(identifier: str, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    order = crud.get_order_by_identifier(db, identifier)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/search/clients", response_model=List[schemas.ClientResponse])
def search_clients(first_name: str = None, last_name: str = None, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if not first_name and not last_name:
        raise HTTPException(status_code=400, detail="At least one search parameter (first_name or last_name) is required")
    clients = crud.search_clients_by_name(db, first_name, last_name)
    if not clients:
        raise HTTPException(status_code=404, detail="Clients not found")
    return clients

@app.get("/search/products", response_model=List[schemas.ProductResponse])
def search_products(name: str, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if not name:
        raise HTTPException(status_code=400, detail="Search parameter (name) is required")
    products = search_products_by_name(db, name)
    if not products:
        raise HTTPException(status_code=404, detail="Products not found")
    return products


@app.delete("/orders/{identifier}", response_model=dict)
async def delete_order_by_identifier(
    identifier: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    success = crud.delete_order_by_identifier(db, identifier)
    if not success:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Удаляем чек, если он существует
    receipt_path = RECEIPTS_DIR / f"{identifier}_receipt.pdf"
    if receipt_path.exists():
        try:
            receipt_path.unlink()
            print(f"Чек для заказа {identifier} удалён")
        except Exception as e:
            print(f"Не удалось удалить чек для заказа {identifier}: {str(e)}")

    return {"message": "Заказ удалён"}

@app.post("/orders/{identifier}/receipt", response_model=dict)
async def create_receipt(
    identifier: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Удаляем старый чек, если он существует
    receipt_path = RECEIPTS_DIR / f"{identifier}_receipt.pdf"
    if receipt_path.exists():
        try:
            receipt_path.unlink()
            print(f"Старый чек для заказа {identifier} удалён")
        except Exception as e:
            print(f"Не удалось удалить старый чек для заказа {identifier}: {str(e)}")

    # Генерируем новый чек
    return generate_receipt(identifier, db)

@app.get("/orders/{identifier}/receipt")
async def get_receipt(
    identifier: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Проверяем, существует ли заказ
    db_order = db.query(models.Order).filter(models.Order.identifier == identifier).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Формируем путь к PDF-файлу
    receipt_path = RECEIPTS_DIR / f"{identifier}_receipt.pdf"
    if not receipt_path.exists():
        raise HTTPException(status_code=404, detail="Receipt not found")

    # Возвращаем PDF-файл
    return FileResponse(
        path=receipt_path,
        filename=f"{identifier}_receipt.pdf",
        media_type="application/pdf"
    )

@app.patch("/orders/by-identifier/{identifier}/items/by-name", response_model=schemas.OrderResponse)
async def update_item_quantity_by_name(
    identifier: str,
    product_name: str = Form(...),
    quantity: int = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    print(f"Received: identifier={identifier}, product_name={product_name}, quantity={quantity}, type={type(quantity)}")
    if quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity must be non-negative")
    
    db_order = crud.update_item_quantity_by_name(db, identifier, product_name, quantity)
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Удаляем старый чек и генерируем новый
    receipt_path = RECEIPTS_DIR / f"{identifier}_receipt.pdf"
    if receipt_path.exists():
        try:
            receipt_path.unlink()
            print(f"Старый чек для заказа {identifier} удалён")
        except Exception as e:
            print(f"Не удалось удалить старый чек для заказа {identifier}: {str(e)}")
    try:
        generate_receipt(identifier, db)
    except Exception as e:
        print(f"Не удалось сгенерировать новый чек для заказа {identifier} после обновления количества: {str(e)}")

    return db_order

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="FastAPI App",
        version="0.1.0",
        description="API для вашего приложения",
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "OAuth2PasswordBearer": {
            "type": "oauth2",
            "flows": {
                "password": {
                    "scopes": {},
                    "tokenUrl": "login"
                }
            }
        }
    }
    openapi_schema["paths"]["/login"]["post"]["requestBody"]["content"]["application/x-www-form-urlencoded"]["schema"]["properties"] = {
        "username": {
            "title": "Username",
            "type": "string"
        },
        "password": {
            "title": "Password",
            "type": "string"
        },
        "grant_type": {
            "title": "Grant Type",
            "type": "string",
            "default": "password"
        },
        "scope": {
            "title": "Scope",
            "type": "string",
            "default": ""
        }
    }
    openapi_schema["paths"]["/login"]["post"]["requestBody"]["content"]["application/x-www-form-urlencoded"]["schema"]["required"] = ["username", "password"]
    
    # Настройка формы для /clients
    if "/clients" in openapi_schema["paths"] and "post" in openapi_schema["paths"]["/clients"]:
        if "requestBody" not in openapi_schema["paths"]["/clients"]["post"]:
            openapi_schema["paths"]["/clients"]["post"]["requestBody"] = {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "properties": {}
                        }
                    }
                }
            }
        if "multipart/form-data" not in openapi_schema["paths"]["/clients"]["post"]["requestBody"]["content"]:
            openapi_schema["paths"]["/clients"]["post"]["requestBody"]["content"]["multipart/form-data"] = {
                "schema": {
                    "properties": {}
                }
            }
        openapi_schema["paths"]["/clients"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]["properties"] = {
            "first_name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "last_name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "middle_name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "birth_date": {
                "type": "string",
                "nullable": True,
                "default": None,
                "format": "date"
            },
            "phone": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "address": {
                "type": "string",
                "nullable": True,
                "default": None
            }
        }
    
    # Настройка формы для /clients/by-name
    if "/clients/by-name" in openapi_schema["paths"] and "put" in openapi_schema["paths"]["/clients/by-name"]:
        if "requestBody" not in openapi_schema["paths"]["/clients/by-name"]["put"]:
            openapi_schema["paths"]["/clients/by-name"]["put"]["requestBody"] = {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "properties": {}
                        }
                    }
                }
            }
        if "multipart/form-data" not in openapi_schema["paths"]["/clients/by-name"]["put"]["requestBody"]["content"]:
            openapi_schema["paths"]["/clients/by-name"]["put"]["requestBody"]["content"]["multipart/form-data"] = {
                "schema": {
                    "properties": {}
                }
            }
        openapi_schema["paths"]["/clients/by-name"]["put"]["requestBody"]["content"]["multipart/form-data"]["schema"]["properties"] = {
            "first_name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "last_name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "new_first_name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "new_last_name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "new_middle_name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "new_birth_date": {
                "type": "string",
                "nullable": True,
                "default": None,
                "format": "date"
            },
            "new_phone": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "new_address": {
                "type": "string",
                "nullable": True,
                "default": None
            }
        }
    
    # Настройка формы для /clients/by-name (DELETE)
    if "/clients/by-name" in openapi_schema["paths"] and "delete" in openapi_schema["paths"]["/clients/by-name"]:
        if "requestBody" not in openapi_schema["paths"]["/clients/by-name"]["delete"]:
            openapi_schema["paths"]["/clients/by-name"]["delete"]["requestBody"] = {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "properties": {}
                        }
                    }
                }
            }
        if "multipart/form-data" not in openapi_schema["paths"]["/clients/by-name"]["delete"]["requestBody"]["content"]:
            openapi_schema["paths"]["/clients/by-name"]["delete"]["requestBody"]["content"]["multipart/form-data"] = {
                "schema": {
                    "properties": {}
                }
            }
        openapi_schema["paths"]["/clients/by-name"]["delete"]["requestBody"]["content"]["multipart/form-data"]["schema"]["properties"] = {
            "first_name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "last_name": {
                "type": "string",
                "nullable": True,
                "default": None
            }
        }

    # Настройка формы для /orders/by-form
    if "/orders/by-form" in openapi_schema["paths"] and "post" in openapi_schema["paths"]["/orders/by-form"]:
        if "requestBody" not in openapi_schema["paths"]["/orders/by-form"]["post"]:
            openapi_schema["paths"]["/orders/by-form"]["post"]["requestBody"] = {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "properties": {}
                        }
                    }
                }
            }
        if "multipart/form-data" not in openapi_schema["paths"]["/orders/by-form"]["post"]["requestBody"]["content"]:
            openapi_schema["paths"]["/orders/by-form"]["post"]["requestBody"]["content"]["multipart/form-data"] = {
                "schema": {
                    "properties": {}
                }
            }
        openapi_schema["paths"]["/orders/by-form"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]["properties"] = {
            "client_first_name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "client_last_name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "status": {
                "type": "string",
                "enum": ["pending", "ready", "shipped"],
                "default": "pending"
            },
            "items": {
                "type": "string",
                "description": "JSON list of items, e.g., [{\"product_name\": \"Product\", \"quantity\": 1}]",
                "default": "[]"
            }
        }
    # Настройка формы для /products/by-name
    if "/products/by-name" in openapi_schema["paths"] and "put" in openapi_schema["paths"]["/products/by-name"]:
        if "requestBody" not in openapi_schema["paths"]["/products/by-name"]["put"]:
            openapi_schema["paths"]["/products/by-name"]["put"]["requestBody"] = {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "properties": {}
                        }
                    }
                }
            }
        if "multipart/form-data" not in openapi_schema["paths"]["/products/by-name"]["put"]["requestBody"]["content"]:
            openapi_schema["paths"]["/products/by-name"]["put"]["requestBody"]["content"]["multipart/form-data"] = {
                "schema": {
                    "properties": {}
                }
            }
        openapi_schema["paths"]["/products/by-name"]["put"]["requestBody"]["content"]["multipart/form-data"]["schema"]["properties"] = {
            "request": {
                "type": "string",
                "description": "JSON object, e.g., {\"name\": \"Product\", \"new_stock\": 10}",
                "default": "{}"
            }
        }

    # Настройка для /products/by-name/image
    if "/products/by-name/image" in openapi_schema["paths"] and "put" in openapi_schema["paths"]["/products/by-name/image"]:
        if "requestBody" not in openapi_schema["paths"]["/products/by-name/image"]["put"]:
            openapi_schema["paths"]["/products/by-name/image"]["put"]["requestBody"] = {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "properties": {}
                        }
                    }
                }
            }
        if "multipart/form-data" not in openapi_schema["paths"]["/products/by-name/image"]["put"]["requestBody"]["content"]:
            openapi_schema["paths"]["/products/by-name/image"]["put"]["requestBody"]["content"]["multipart/form-data"] = {
                "schema": {
                    "properties": {}
                }
            }
        openapi_schema["paths"]["/products/by-name/image"]["put"]["requestBody"]["content"]["multipart/form-data"]["schema"]["properties"] = {
            "name": {
                "type": "string",
                "nullable": True,
                "default": None
            },
            "image": {
                "type": "string",
                "format": "binary",
                "nullable": False  # Изображение обязательно
            }
        }

    # Настройка для /products/by-name (DELETE)
    if "/products/by-name" in openapi_schema["paths"] and "delete" in openapi_schema["paths"]["/products/by-name"]:
        if "requestBody" not in openapi_schema["paths"]["/products/by-name"]["delete"]:
            openapi_schema["paths"]["/products/by-name"]["delete"]["requestBody"] = {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "properties": {}
                        }
                    }
                }
            }
        if "multipart/form-data" not in openapi_schema["paths"]["/products/by-name"]["delete"]["requestBody"]["content"]:
            openapi_schema["paths"]["/products/by-name"]["delete"]["requestBody"]["content"]["multipart/form-data"] = {
                "schema": {
                    "properties": {}
                }
            }
        openapi_schema["paths"]["/products/by-name"]["delete"]["requestBody"]["content"]["multipart/form-data"]["schema"]["properties"] = {
            "name": {
                "type": "string",
                "nullable": True,
                "default": None
            }
        }

    # Настройка для /orders/{identifier}/receipt (POST)
    if "/orders/{identifier}/receipt" in openapi_schema["paths"] and "post" in openapi_schema["paths"]["/orders/{identifier}/receipt"]:
        openapi_schema["paths"]["/orders/{identifier}/receipt"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"] = {
            "message": {
                "type": "string",
                "example": "Чек для заказа {identifier} успешно создан"
            }
        }
    
    # Настройка для /orders/{identifier}/receipt (GET)
    if "/orders/{identifier}/receipt" in openapi_schema["paths"] and "get" in openapi_schema["paths"]["/orders/{identifier}/receipt"]:
        openapi_schema["paths"]["/orders/{identifier}/receipt"]["get"]["responses"]["200"]["content"] = {
            "application/pdf": {
                "schema": {
                    "type": "string",
                    "format": "binary"
                }
            }
        }
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
