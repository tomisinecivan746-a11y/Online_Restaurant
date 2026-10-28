from datetime import datetime

from flask import Flask, g
from sqlalchemy import inspect, select, DateTime, Integer, String, Text, create_engine, ForeignKey
from sqlalchemy.orm import Mapped, Session, mapped_column, DeclarativeBase, sessionmaker

app = Flask(__name__)

engine = create_engine("sqlite:///skills.db")
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

class Base(DeclarativeBase):
    pass

class Position(Base):
    __tablename__ = "positions"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    dish_name: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingredients: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

def get_db():
    if "db" not in g:
        g.db = Session()
        
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db:
        db.close()

class Order(Base):
    __tablename__ = "orders"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    dish_id: Mapped[int] = mapped_column(Integer, ForeignKey("positions.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_price: Mapped[int] = mapped_column(Integer, nullable=False)
    order_group: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Reservation(Base):
    __tablename__ = "reservations"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    reservation_time: Mapped[str] = mapped_column(String(50), nullable=False)
    number_of_people: Mapped[int] = mapped_column(Integer, nullable=False)
    table_number: Mapped[int] = mapped_column(Integer, nullable=False)

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

class CartItem(Base):
    __tablename__ = "cart_items"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    
Base.metadata.create_all(bind=engine)

position_columns = {
    column["name"] for column in inspect(engine).get_columns("positions")
}
with engine.begin() as connection:
    for column_name in ("description", "ingredients", "image_filename"):
        if column_name not in position_columns:
            connection.exec_driver_sql(
                f"ALTER TABLE positions ADD COLUMN {column_name} TEXT"
            )

order_columns = {
    column["name"] for column in inspect(engine).get_columns("orders")
}
with engine.begin() as connection:
    order_migrations = {
        "order_group": "VARCHAR(36)",
        "user_id": "INTEGER REFERENCES users(id)",
        "created_at": "DATETIME",
    }
    for column_name, column_type in order_migrations.items():
        if column_name not in order_columns:
            connection.exec_driver_sql(
                f"ALTER TABLE orders ADD COLUMN {column_name} {column_type}"
            )

seafood_positions = [
    {
        "dish_name": "Grilled salmon",
        "price": 320,
        "weight": 250,
        "description": "Grilled salmon served with lemon and seasonal vegetables.",
        "ingredients": "Salmon, lemon, seasonal vegetables, olive oil, herbs",
        "image_filename": "salmon.jpg",
    },
    {
        "dish_name": "Shrimp pasta",
        "price": 280,
        "weight": 300,
        "description": "Pasta with shrimp in a creamy garlic sauce.",
        "ingredients": "Shrimp, pasta, cream, garlic, parmesan, parsley",
        "image_filename": "shrimp-pasta.jpg",
    },
    {
        "dish_name": "Fish and chips",
        "price": 240,
        "weight": 350,
        "description": "Crispy battered white fish served with golden fries.",
        "ingredients": "White fish, potatoes, flour, egg, breadcrumbs, tartar sauce",
        "image_filename": "fish&chips.jpg",
    },
    {
        "dish_name": "Seafood risotto",
        "price": 310,
        "weight": 300,
        "description": "Creamy risotto with seafood and herbs.",
        "ingredients": "Rice, seafood, broth, parmesan, onion, herbs",
        "image_filename": "seafood-rosotto.jpg",
    },
    {
        "dish_name": "Fried calamari",
        "price": 260,
        "weight": 200,
        "description": "Lightly breaded calamari, fried until crisp.",
        "ingredients": "Calamari, flour, lemon, salt, pepper",
        "image_filename": "fried-calamari.jpg",
    },
    {
        "dish_name": "Mussels in garlic sauce",
        "price": 290,
        "weight": 500,
        "description": "Mussels cooked in a fragrant garlic and herb sauce.",
        "ingredients": "Mussels, garlic, butter, parsley, lemon",
        "image_filename": "mussels.jpg",
    },
]

with SessionLocal() as db_session:
    existing_positions = {
        position.dish_name: position
        for position in db_session.scalars(select(Position)).all()
    }
    for position_data in seafood_positions:
        position = existing_positions.get(position_data["dish_name"])
        if position is None:
            position = Position(**position_data)
            db_session.add(position)
        else:
            for field in ("description", "ingredients", "image_filename"):
                if not getattr(position, field):
                    setattr(position, field, position_data[field])
    db_session.commit()