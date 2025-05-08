from pathlib import Path
from sqlalchemy.orm import Session, joinedload
from models import User
from schemas import UserCreate, OrderCreate
from utils import hash_password
import models
import schemas

from datetime import date

import unidecode

from sqlalchemy import func

from typing import List, Optional, Dict, Any

from datetime import date, datetime
import json
from fastapi import HTTPException

from schemas import (
    UserCreate, UserResponse, OrderCreate, OrderResponse, ProductCreate, ProductResponse,
    ClientCreate, ClientResponse, OrderItemCreate, OrderItemCreateByName, OrderItemResponse,
    ProductUpdate, ClientUpdateRequest, OrderStatusEnum
)

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
# Импорт для преобразования суммы в слова
from num2words import num2words

# Импорт для локализации даты
import locale

# Устанавливаем локализацию для русского языка
locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')

pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))

RECEIPTS_DIR = Path("receipts")
RECEIPTS_DIR.mkdir(exist_ok=True)

def create_user(db: Session, user: UserCreate):
    db_user = User(
        username=user.username,
        hashed_password=hash_password(user.password),
        first_name=user.first_name,
        last_name=user.last_name,
        middle_name=user.middle_name
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_orders(db: Session, skip: int = 0, limit: int = 10):
    return db.query(models.Order).offset(skip).limit(limit).all()


def delete_user(db: Session, user_id: int):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        return None
    db.delete(db_user)
    db.commit()
    return db_user

def delete_user_by_username(db: Session, username: str):
    db_user = db.query(models.User).filter(models.User.username == username).first()
    if not db_user:
        return None
    db.delete(db_user)
    db.commit()
    return db_user

def generate_receipt(identifier: str, db: Session):
    # Находим заказ
    db_order = db.query(models.Order).options(
        joinedload(models.Order.client),
        joinedload(models.Order.items).joinedload(models.OrderItem.product)
    ).filter(models.Order.identifier == identifier).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Формируем путь для PDF-файла
    receipt_path = RECEIPTS_DIR / f"{identifier}_receipt.pdf"
    
    # Создаём PDF с уменьшенными отступами
    doc = SimpleDocTemplate(
        str(receipt_path),
        pagesize=A4,
        leftMargin=15,
        rightMargin=15,
        topMargin=30,
        bottomMargin=30
    )
    elements = []

    # Параметры таблицы
    padding = 5
    table_width = A4[0] - 15 - 15
    col_widths = [30, 60, 220, 80, 80, 80]
    row_height = 30
    styles = getSampleStyleSheet()
    style_normal = styles['Normal']
    style_normal.fontName = 'DejaVuSans'
    style_normal.fontSize = 12
    style_normal.leading = 20
    style_normal.alignment = 0

    # Заголовок
    date_str = datetime.now().strftime("%d %B %Y г.").encode('utf-8').decode('utf-8')
    elements.append(Paragraph(f"Товарный чек № {identifier} от {date_str}", style_normal))
    elements.append(Paragraph("Поставщик: ИП Иванов И.И.", style_normal))

    # Информация о покупателе
    client_name = f"{db_order.client.last_name} {db_order.client.first_name}" if db_order.client else "Неизвестный клиент"
    elements.append(Paragraph(f"Покупатель: {client_name}", style_normal))

    # Пустая строка для отступа
    elements.append(Paragraph("", style_normal))

    # Данные для таблицы
    table_data = [["№", "Артикул", "Товар", "Количество", "Цена", "Сумма"]]
    total_amount = 0
    for idx, item in enumerate(db_order.items, 1):
        product = item.product
        quantity = item.quantity
        price = product.price
        amount = quantity * price
        total_amount += amount
        table_data.append([
            str(idx),
            str(product.id),
            product.name,
            str(quantity),
            f"{price:.1f}",
            f"{amount:.1f}"
        ])

    # Создаём таблицу
    table = Table(table_data, colWidths=col_widths, rowHeights=[row_height] * len(table_data))
    table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'DejaVuSans'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.black),
        ('BOX', (0, 0), (-1, -1), 0.25, colors.black),
        ('LEFTPADDING', (0, 0), (-1, -1), padding),
        ('RIGHTPADDING', (0, 0), (-1, -1), padding),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(table)

    # Итоговая сумма
    elements.append(Paragraph(f"Итого: {total_amount:.2f} руб.", style_normal))

    # Сумма прописью
    rubles = int(total_amount)
    kopecks = int((total_amount - rubles) * 100)
    amount_in_words = num2words(rubles, lang='ru').replace(' и ', ' ').capitalize() + " рублей"
    if kopecks > 0:
        amount_in_words += f" {kopecks:02d} копеек"
    else:
        amount_in_words += " 00 копеек"
    elements.append(Paragraph(f"Всего наименований {len(db_order.items)}, на сумму {total_amount:.2f} руб.", style_normal))
    elements.append(Paragraph(amount_in_words, style_normal))

    # Подписи
    elements.append(Paragraph("Отпустил _______________  Получил _______________", style_normal))

    # Создаём PDF
    doc.build(elements)

    return {"message": f"Чек для заказа {identifier} успешно создан"}

def generate_identifier(client: models.Client, order_id: int) -> str:
    # Транслитерация первых букв
    last_initial = unidecode.unidecode(client.last_name[0]).upper() if client.last_name else 'X'
    first_initial = unidecode.unidecode(client.first_name[0]).upper() if client.first_name else 'X'
    middle_initial = unidecode.unidecode(client.middle_name[0]).upper() if client.middle_name else 'X'
    
    # Форматирование порядкового номера (id с ведущими нулями до 6 цифр)
    order_number = str(order_id).zfill(6)
    
    # Формируем identifier
    return f"{last_initial}{first_initial}{middle_initial}{order_number}"

def create_order(db: Session, order: schemas.OrderCreate):
    db_client = db.query(models.Client).filter(models.Client.id == order.client_id).first()
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    temp_identifier = generate_identifier(db_client, 0)
    db_order = models.Order(status=order.status, client_id=order.client_id, identifier=temp_identifier)
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    
    identifier = generate_identifier(db_client, db_order.id)
    db_order.identifier = identifier
    db.commit()
    db.refresh(db_order)

    for item in order.items:
        db_product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if not db_product:
            raise HTTPException(status_code=404, detail=f"Product with id {item.product_id} not found")
        if db_product.stock < item.quantity:
            raise HTTPException(status_code=400, detail=f"Not enough stock for product {db_product.name}")
        db_product.stock -= item.quantity  # Уменьшаем stock
        db_item = models.OrderItem(
            order_id=db_order.id,
            product_id=item.product_id,
            quantity=item.quantity
        )
        db.add(db_item)
    
    db.commit()
    db.refresh(db_order)
    return db_order

def update_existing_orders(db: Session):
    orders = db.query(models.Order).all()
    for order in orders:
        if not order.identifier:
            client = db.query(models.Client).filter(models.Client.id == order.client_id).first()
            if client:
                order.identifier = generate_identifier(client, order.id)
    db.commit()

def create_product(db: Session, name: str, image_path: str, price: float, stock: int):
    db_product = models.Product(
        name=name,
        image=image_path,  # Путь к файлу
        price=price,
        stock=stock
    )
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

def update_product(db: Session, product_id: int, name: str = None, image_path: str = None, price: float = None, stock: int = None):
    db_product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_product:
        return None
    if name is not None:
        db_product.name = name
    if image_path is not None:
        db_product.image = image_path
    if price is not None:
        db_product.price = price
    if stock is not None:
        db_product.stock = stock
    db.commit()
    db.refresh(db_product)
    return db_product

def delete_product(db: Session, product_id: int):
    db_product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_product:
        return None
    db.delete(db_product)
    db.commit()
    return db_product

def get_products(db: Session, skip: int = 0, limit: int = 10):
    return db.query(models.Product).offset(skip).limit(limit).all()

def get_product_by_id(db: Session, product_id: int):
    return db.query(models.Product).filter(models.Product.id == product_id).first()

def get_client_by_id(db: Session, client_id: int):
    return db.query(models.Client).filter(models.Client.id == client_id).first()

def create_client(db: Session, client: schemas.ClientCreate):
    db_client = models.Client(
        first_name=client.first_name,
        last_name=client.last_name,
        middle_name=client.middle_name,
        birth_date=client.birth_date,
        phone=client.phone,
        address=client.address
    )
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client

def update_client(db: Session, client_id: int, client: schemas.ClientCreate):
    db_client = db.query(models.Client).filter(models.Client.id == client_id).first()
    if not db_client:
        return None
    db_client.first_name = client.first_name
    db_client.last_name = client.last_name
    db_client.middle_name = client.middle_name
    db_client.birth_date = client.birth_date
    db_client.phone = client.phone
    db_client.address = client.address
    db.commit()
    db.refresh(db_client)
    return db_client

def delete_client(db: Session, client_id: int):
    db_client = db.query(models.Client).filter(models.Client.id == client_id).first()
    if not db_client:
        return None
    db.delete(db_client)
    db.commit()
    return db_client

def get_clients(db: Session, skip: int = 0, limit: int = 10):
    return db.query(models.Client).offset(skip).limit(limit).all()

def get_orders(db: Session, skip: int = 0, limit: int = 10):
    return db.query(models.Order).offset(skip).limit(limit).all()

def get_order(db: Session, order_id: int):
    return db.query(models.Order).filter(models.Order.id == order_id).first()


# Новые функции для поиска
def search_clients_by_name(db: Session, first_name: str = None, last_name: str = None):
    query = db.query(models.Client)
    if first_name:
        query = query.filter(func.lower(models.Client.first_name) == func.lower(first_name))
    if last_name:
        query = query.filter(func.lower(models.Client.last_name) == func.lower(last_name))
    return query.all()

def search_products_by_name(db: Session, name: str):
    return db.query(models.Product).filter(func.lower(models.Product.name).like(f"%{name.lower()}%")).all()

def get_order_by_identifier(db: Session, identifier: str):
    return db.query(models.Order).filter(models.Order.identifier == identifier).first()


def update_client_by_name(
    db: Session,
    first_name: str = None,
    last_name: str = None,
    new_first_name: str = None,
    new_last_name: str = None,
    new_middle_name: str = None,
    new_birth_date: date = None,
    new_phone: str = None,
    new_address: str = None
):
    query = db.query(models.Client)
    if first_name:
        query = query.filter(func.lower(models.Client.first_name) == func.lower(first_name))
    if last_name:
        query = query.filter(func.lower(models.Client.last_name) == func.lower(last_name))
    db_client = query.first()
    if not db_client:
        return None
    if new_first_name is not None:
        db_client.first_name = new_first_name
    if new_last_name is not None:
        db_client.last_name = new_last_name
    if new_middle_name is not None:
        db_client.middle_name = new_middle_name
    if new_birth_date is not None:
        db_client.birth_date = new_birth_date
    if new_phone is not None:
        db_client.phone = new_phone
    if new_address is not None:
        db_client.address = new_address
    db.commit()
    db.refresh(db_client)
    return db_client

def update_product_by_name(
    db: Session,
    name: str,
    new_name: Optional[str] = None,
    new_image_path: Optional[str] = None,
    new_price: Optional[float] = None,
    new_stock: Optional[int] = None
):
    db_product = db.query(models.Product).filter(func.lower(models.Product.name) == func.lower(name)).first()
    if not db_product:
        return None
    if new_name is not None:
        db_product.name = new_name
    if new_image_path is not None:
        db_product.image = new_image_path
    if new_price is not None:
        db_product.price = new_price
    if new_stock is not None:
        db_product.stock = new_stock
    db.commit()
    db.refresh(db_product)
    return db_product

def update_order_by_identifier(db: Session, identifier: str, items: List[schemas.OrderItemCreate]):
    db_order = db.query(models.Order).filter(models.Order.identifier == identifier).first()
    if not db_order:
        return None
    
    # Удаляем старые элементы заказа
    db.query(models.OrderItem).filter(models.OrderItem.order_id == db_order.id).delete()
    
    # Добавляем новые элементы
    for item in items:
        db_product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if not db_product:
            raise HTTPException(status_code=404, detail=f"Product with id {item.product_id} not found")
        db_item = models.OrderItem(
            order_id=db_order.id,
            product_id=item.product_id,
            quantity=item.quantity
        )
        db.add(db_item)
    
    db.commit()
    db.refresh(db_order)
    return db_order

def delete_item_from_order(db: Session, identifier: str, product_id: int):
    db_order = db.query(models.Order).filter(models.Order.identifier == identifier).first()
    if not db_order:
        return None
    
    db_item = db.query(models.OrderItem).filter(
        models.OrderItem.order_id == db_order.id,
        models.OrderItem.product_id == product_id
    ).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found in order")
    
    db.delete(db_item)
    db.commit()
    db.refresh(db_order)
    return db_order

def update_item_quantity(db: Session, identifier: str, product_id: int, quantity: int):
    db_order = db.query(models.Order).filter(models.Order.identifier == identifier).first()
    if not db_order:
        return None
    
    db_item = db.query(models.OrderItem).filter(
        models.OrderItem.order_id == db_order.id,
        models.OrderItem.product_id == product_id
    ).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found in order")
    
    db_item.quantity = quantity
    db.commit()
    db.refresh(db_order)
    return db_order

def create_order_by_form(db: Session, client_first_name: str, client_last_name: str, status: OrderStatusEnum, items: List[OrderItemCreateByName]):
    # Находим клиента по имени/фамилии
    query = db.query(models.Client)
    if client_first_name:
        query = query.filter(func.lower(models.Client.first_name) == func.lower(client_first_name))
    if client_last_name:
        query = query.filter(func.lower(models.Client.last_name) == func.lower(client_last_name))
    db_client = query.first()
    if not db_client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Создаём список товаров по их названиям
    items_with_ids = []
    for item in items:
        db_product = db.query(models.Product).filter(func.lower(models.Product.name) == func.lower(item.product_name)).first()
        if not db_product:
            raise HTTPException(status_code=404, detail=f"Product with name {item.product_name} not found")
        if db_product.stock < item.quantity:
            raise HTTPException(status_code=400, detail=f"Not enough stock for product {db_product.name}")
        items_with_ids.append(OrderItemCreate(product_id=db_product.id, quantity=item.quantity))
        db_product.stock -= item.quantity  # Уменьшаем stock
    
    # Создаём заказ
    temp_identifier = generate_identifier(db_client, 0)
    db_order = models.Order(status=status, client_id=db_client.id, identifier=temp_identifier)
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    
    identifier = generate_identifier(db_client, db_order.id)
    db_order.identifier = identifier
    db.commit()
    db.refresh(db_order)

    for item in items_with_ids:
        db_item = models.OrderItem(
            order_id=db_order.id,
            product_id=item.product_id,
            quantity=item.quantity
        )
        db.add(db_item)
    
    db.commit()
    db.refresh(db_order)

    # Генерируем чек для нового заказа
    try:
        generate_receipt(db_order.identifier, db)
        print(f"Чек для заказа {db_order.identifier} сгенерирован при создании заказа")
    except Exception as e:
        print(f"Не удалось сгенерировать чек для заказа {db_order.identifier} при создании: {str(e)}")

    return db_order

def add_item_to_order_by_name(db: Session, identifier: str, item: schemas.OrderItemCreateByName):
    db_order = db.query(models.Order).filter(models.Order.identifier == identifier).first()
    if not db_order:
        return None

    db_product = db.query(models.Product).filter(func.lower(models.Product.name) == func.lower(item.product_name)).first()
    if not db_product:
        raise HTTPException(status_code=404, detail=f"Product with name {item.product_name} not found")

    if db_product.stock < item.quantity:
        raise HTTPException(status_code=400, detail=f"Not enough stock for product {db_product.name}")

    # Проверяем, есть ли уже элемент с этим продуктом в заказе
    existing_item = db.query(models.OrderItem).filter(
        models.OrderItem.order_id == db_order.id,
        models.OrderItem.product_id == db_product.id
    ).first()

    if existing_item:
        # Если элемент уже существует, увеличиваем quantity
        existing_item.quantity += item.quantity
        # Проверяем, достаточно ли stock для увеличения количества
        if db_product.stock < item.quantity:
            raise HTTPException(status_code=400, detail=f"Not enough stock for product {db_product.name}")
        db_product.stock -= item.quantity  # Уменьшаем stock
    else:
        # Если элемента нет, создаём новый
        db_product.stock -= item.quantity  # Уменьшаем stock
        new_item = models.OrderItem(
            order_id=db_order.id,
            product_id=db_product.id,
            quantity=item.quantity
        )
        db.add(new_item)

    db.commit()
    db.refresh(db_order)
    return db_order

def update_item_quantity_by_name(db: Session, identifier: str, product_name: str, quantity: int):
    db_order = db.query(models.Order).filter(models.Order.identifier == identifier).first()
    if not db_order:
        return None
    
    db_product = db.query(models.Product).filter(func.lower(models.Product.name) == func.lower(product_name)).first()
    if not db_product:
        raise HTTPException(status_code=404, detail=f"Product with name {product_name} not found")
    
    db_item = db.query(models.OrderItem).filter(
        models.OrderItem.order_id == db_order.id,
        models.OrderItem.product_id == db_product.id
    ).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found in order")
    
    # Изменяем stock
    old_quantity = db_item.quantity
    if quantity > old_quantity:
        # Увеличиваем количество, уменьшаем stock
        delta = quantity - old_quantity
        if db_product.stock < delta:
            raise HTTPException(status_code=400, detail=f"Not enough stock for product {db_product.name}")
        db_product.stock -= delta
    elif quantity < old_quantity:
        # Уменьшаем количество, увеличиваем stock
        delta = old_quantity - quantity
        db_product.stock += delta
    
    if quantity == 0:
        # Удаляем товар из заказа
        db.delete(db_item)
    else:
        db_item.quantity = quantity
    
    db.commit()
    db.refresh(db_order)
    return db_order

def delete_product_by_name(db: Session, name: str):
    db_product = db.query(models.Product).filter(func.lower(models.Product.name) == func.lower(name)).first()
    if not db_product:
        return None
    
    # Сохраняем путь к изображению для удаления
    image_path = db_product.image if db_product.image else None
    
    # Удаляем продукт
    db.delete(db_product)
    db.commit()
    
    # Удаляем изображение с сервера, если оно существует
    if image_path:
        try:
            file_path = Path(image_path)
            if file_path.exists() and file_path.is_file():
                file_path.unlink()
        except Exception as e:
            print(f"Failed to delete image {image_path}: {str(e)}")
    
    return db_product

def delete_client_by_name(db: Session, first_name: str = None, last_name: str = None):
    query = db.query(models.Client)
    if first_name:
        query = query.filter(func.lower(models.Client.first_name) == func.lower(first_name))
    if last_name:
        query = query.filter(func.lower(models.Client.last_name) == func.lower(last_name))
    db_client = query.first()
    if not db_client:
        return None
    
    # Удаляем связанные заказы
    orders = db.query(models.Order).filter(models.Order.client_id == db_client.id).all()
    for order in orders:
        # Находим все элементы заказа
        order_items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order.id).all()
        for item in order_items:
            # Находим продукт и увеличиваем stock
            product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
            if product:
                product.stock += item.quantity
            # Удаляем элемент заказа
            db.delete(item)
        # Удаляем сам заказ
        db.delete(order)
    
    # Удаляем клиента
    db.delete(db_client)
    db.commit()
    return db_client

def delete_order_by_identifier(db: Session, identifier: str):
    db_order = db.query(models.Order).filter(models.Order.identifier == identifier).first()
    if not db_order:
        return None
    
    # Находим все элементы заказа
    order_items = db.query(models.OrderItem).filter(models.OrderItem.order_id == db_order.id).all()
    for item in order_items:
        # Находим продукт и увеличиваем stock
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if product:
            product.stock += item.quantity
        # Удаляем элемент заказа
        db.delete(item)
    
    # Удаляем заказ
    db.delete(db_order)
    db.commit()
    
    return True  # Возвращаем True, чтобы указать, что удаление прошло успешно

def wrap_text(text, max_width, font_name, font_size, canvas):
    """Функция для переноса текста на следующую строку, если он не помещается в заданную ширину."""
    canvas.setFont(font_name, font_size)
    lines = []
    words = text.split()
    current_line = []
    current_width = 0

    for word in words:
        word_width = canvas.stringWidth(word + " ", font_name, font_size)
        if current_width + word_width <= max_width:
            current_line.append(word)
            current_width += word_width
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_width = word_width
    if current_line:
        lines.append(" ".join(current_line))
    
    return lines
