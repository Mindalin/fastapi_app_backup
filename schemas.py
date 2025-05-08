from pydantic import BaseModel, Field
from datetime import date
from enum import Enum
from typing import List, Optional

class UserCreate(BaseModel):
    username: str
    password: str
    first_name: str
    last_name: str
    middle_name: str
    role: str = "user"

class ClientCreate(BaseModel):
    first_name: str
    last_name: str
    middle_name: str
    birth_date: date
    phone: str
    address: str

class ClientUpdate(BaseModel):
    first_name: Optional[str] = Field(default=None, description="Имя клиента для поиска")
    last_name: Optional[str] = Field(default=None, description="Фамилия клиента для поиска")
    new_first_name: Optional[str] = Field(default=None, description="Новое имя клиента")
    new_last_name: Optional[str] = Field(default=None, description="Новая фамилия клиента")
    new_middle_name: Optional[str] = Field(default=None, description="Новое отчество клиента")
    new_birth_date: Optional[str] = Field(default=None, description="Новая дата рождения (YYYY-MM-DD)")
    new_phone: Optional[str] = Field(default=None, description="Новый телефон клиента")
    new_address: Optional[str] = Field(default=None, description="Новый адрес клиента")

class ClientResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    middle_name: str
    birth_date: date
    phone: str
    address: str

    class Config:
        from_attributes = True

class OrderStatusEnum(str, Enum):
    pending = "pending"
    ready = "ready"
    shipped = "shipped"

class ProductCreate(BaseModel):
    name: str
    image: str
    price: float
    stock: int

class ProductUpdate(BaseModel):
    name: str
    new_name: Optional[str] =None
    new_price: Optional[float] = None
    new_stock: Optional[int] = None

class ProductResponse(BaseModel):
    id: int
    name: str
    image: str
    price: float
    stock: int

    class Config:
        from_attributes = True

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int

class OrderItemCreateByName(BaseModel):  # Новая схема для добавления товара по названию
    product_name: str
    quantity: int

class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: int
    product: ProductCreate

    class Config:
        from_attributes = True

class OrderCreate(BaseModel):
    client_id: int
    status: OrderStatusEnum
    items: List[OrderItemCreate]

class OrderResponse(BaseModel):
    id: int
    status: OrderStatusEnum
    client_id: int
    identifier: str
    client: ClientCreate
    items: List[OrderItemResponse]

    class Config:
        from_attributes = True

class UserResponse(BaseModel):
    id: int
    username: str
    first_name: str
    last_name: str
    middle_name: str
    role: str

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None

class LoginData(BaseModel):
    username: str
    password: str


class ClientUpdateRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    new_first_name: Optional[str] = None
    new_last_name: Optional[str] = None
    new_middle_name: Optional[str] = None
    new_birth_date: Optional[str] = None
    new_phone: Optional[str] = None
    new_address: Optional[str] = None
