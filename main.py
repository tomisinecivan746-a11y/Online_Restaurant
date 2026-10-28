import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.utils import secure_filename

from database import CartItem, Order, Position, Reservation, SessionLocal, User

create_app = Flask(__name__)
create_app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
create_app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024

ALLOWED_IMAGE_EXTENSIONS = {'gif', 'jpeg', 'jpg', 'png', 'webp'}


def require_admin():
    if session.get('user_id') is None:
        return redirect(url_for('login'))
    if session.get('username') != 'Admin':
        abort(403)
    return None


@create_app.route('/')
def main():
    return render_template('main.html')


@create_app.route('/menu')
def menu():
    with SessionLocal() as db_session:
        positions = db_session.scalars(
            select(Position).order_by(Position.id)
        ).all()
    return render_template('menu.html', positions=positions)


@create_app.route('/add_position', methods=['GET', 'POST'])
def add_position():
    access_denied = require_admin()
    if access_denied is not None:
        return access_denied

    if request.method == 'POST':
        dish_name = request.form.get('dish_name', '').strip()
        description = request.form.get('description', '').strip()
        ingredients = request.form.get('ingredients', '').strip()
        price = request.form.get('price', type=int)
        weight = request.form.get('weight', type=int)
        image = request.files.get('image')
        image_name = secure_filename(image.filename) if image else ''
        extension = image_name.rsplit('.', 1)[-1].lower() if '.' in image_name else ''

        if (
            not dish_name
            or len(dish_name) > 100
            or not description
            or not ingredients
            or price is None
            or price < 1
            or weight is None
            or weight < 1
            or not image_name
            or extension not in ALLOWED_IMAGE_EXTENSIONS
        ):
            return render_template(
                'add_position.html',
                message='Enter valid dish details and upload a supported image (JPG, PNG, GIF, or WEBP).',
                form_data=request.form,
            ), 400

        uploaded_filename = f'{uuid4().hex}.{extension}'
        uploaded_path = os.path.join(create_app.static_folder, uploaded_filename)
        image.save(uploaded_path)

        try:
            with SessionLocal() as db_session:
                db_session.add(
                    Position(
                        dish_name=dish_name,
                        description=description,
                        ingredients=ingredients,
                        price=price,
                        weight=weight,
                        image_filename=uploaded_filename,
                    )
                )
                db_session.commit()
        except SQLAlchemyError:
            os.remove(uploaded_path)
            raise

        flash(f'{dish_name} was added to the menu.')
        return redirect(url_for('menu'))

    return render_template('add_position.html', form_data={})


@create_app.route('/delete_position/<int:position_id>', methods=['POST'])
def delete_position(position_id):
    access_denied = require_admin()
    if access_denied is not None:
        return access_denied

    with SessionLocal() as db_session:
        position = db_session.get(Position, position_id)
        if position is None:
            abort(404)

        order_exists = db_session.scalar(
            select(Order.id).where(Order.dish_id == position_id).limit(1)
        )
        if order_exists is not None:
            flash('This item cannot be deleted because it has order history.')
            return redirect(url_for('menu'))

        image_filename = position.image_filename
        db_session.execute(
            delete(CartItem).where(CartItem.position_id == position_id)
        )
        db_session.delete(position)
        db_session.commit()

    image_stem, image_extension = os.path.splitext(image_filename or '')
    is_uploaded_image = (
        len(image_stem) == 32
        and all(character in '0123456789abcdef' for character in image_stem.lower())
        and image_extension.lower() in {'.gif', '.jpeg', '.jpg', '.png', '.webp'}
    )
    if is_uploaded_image:
        with SessionLocal() as db_session:
            image_is_referenced = db_session.scalar(
                select(Position.id)
                .where(Position.image_filename == image_filename)
                .limit(1)
            )
        if image_is_referenced is None:
            image_path = os.path.join(create_app.static_folder, image_filename)
            if os.path.isfile(image_path):
                os.remove(image_path)

    flash('The menu item was deleted.')
    return redirect(url_for('menu'))


@create_app.route('/position/<name>')
def position_detail(name):
    with SessionLocal() as db_session:
        position = db_session.scalar(
            select(Position).where(Position.dish_name == name)
        )
        if position is None:
            return render_template('position.html', position=None), 404
        position_details = {
            'id': position.id,
            'dish_name': position.dish_name,
            'description': position.description,
            'ingredients': position.ingredients,
            'price': position.price,
            'weight': position.weight,
            'image_filename': position.image_filename,
        }
    return render_template('position.html', position=position_details)


@create_app.route('/cart/add/<int:position_id>', methods=['POST'])
def add_to_cart(position_id):
    quantity = request.form.get('quantity', default=1, type=int)
    if quantity is None or quantity < 1:
        return 'Quantity must be at least 1.', 400

    with SessionLocal() as db_session:
        position = db_session.get(Position, position_id)
        if position is None:
            return 'Position not found.', 404

    cart = session.get('cart', {})
    key = str(position_id)
    cart[key] = cart.get(key, 0) + quantity
    session['cart'] = cart
    if session.get('user_id') is not None:
        with SessionLocal() as db_session:
            save_cart(db_session, session['user_id'], cart)
            db_session.commit()
    print(f'Cart: {session["cart"]}')
    return redirect(url_for('cart'))


@create_app.route('/cart/remove/<int:position_id>', methods=['POST'])
def remove_from_cart(position_id):
    cart = session.get('cart', {})
    cart.pop(str(position_id), None)
    session['cart'] = cart
    if session.get('user_id') is not None:
        with SessionLocal() as db_session:
            save_cart(db_session, session['user_id'], cart)
            db_session.commit()
    return redirect(url_for('cart'))


def save_cart(db_session, user_id, cart):
    db_session.execute(
        delete(CartItem).where(CartItem.user_id == user_id)
    )
    for position_id, quantity in cart.items():
        db_session.add(
            CartItem(
                user_id=user_id,
                position_id=int(position_id),
                quantity=quantity,
            )
        )


@create_app.route('/cart')
def cart():
    items, total, cart_is_valid = get_cart_details()
    if not cart_is_valid:
        return 'A cart item is no longer available. Remove it and try again.', 400
    return render_template('cart.html', items=items, total=total)


def get_cart_details():
    cart_items = session.get('cart', {})
    position_ids = [int(position_id) for position_id in cart_items]
    items = []
    total = 0

    if position_ids:
        with SessionLocal() as db_session:
            positions = db_session.scalars(
                select(Position).where(Position.id.in_(position_ids))
            ).all()

        for position in positions:
            quantity = cart_items.get(str(position.id), 0)
            subtotal = position.price * quantity
            total += subtotal
            items.append({
                'position_id': position.id,
                'dish_name': position.dish_name,
                'price': position.price,
                'quantity': quantity,
                'subtotal': subtotal,
            })

    return items, total, len(items) == len(position_ids)


@create_app.route('/create_order', methods=['GET', 'POST'])
def create_order():
    user_id = session.get('user_id')
    if user_id is None:
        return redirect(url_for('login'))

    items, total, cart_is_valid = get_cart_details()
    if not cart_is_valid:
        return 'A cart item is no longer available. Remove it and try again.', 400
    if not items:
        flash('Your cart is empty.')
        return redirect(url_for('cart'))

    if request.method == 'POST':
        cart_items = session.get('cart', {})
        position_ids = [int(position_id) for position_id in cart_items]
        with SessionLocal() as db_session:
            user = db_session.get(User, user_id)
            if user is None:
                session.pop('user_id', None)
                session.pop('username', None)
                return redirect(url_for('login'))

            positions = db_session.scalars(
                select(Position).where(Position.id.in_(position_ids))
            ).all()
            if len(positions) != len(position_ids):
                return 'A cart item is no longer available. Remove it and try again.', 400

            order_group = str(uuid4())
            created_at = datetime.now(timezone.utc)
            for position in positions:
                quantity = cart_items[str(position.id)]
                db_session.add(
                    Order(
                        dish_id=position.id,
                        quantity=quantity,
                        total_price=position.price * quantity,
                        order_group=order_group,
                        user_id=user.id,
                        created_at=created_at,
                    )
                )
            db_session.execute(
                delete(CartItem).where(CartItem.user_id == user.id)
            )
            db_session.commit()

        session.pop('cart', None)
        flash('Your order has been placed.')
        return redirect(url_for('cart'))

    return render_template('create_order.html', items=items, total=total)


@create_app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not email or not password:
            return render_template(
                'register.html',
                message='Please fill in all fields.',
            ), 400

        with SessionLocal() as session:
            session.add(
                User(
                    username=username,
                    email=email,
                    password_hash=hashlib.sha256(password.encode('utf-8')).hexdigest(),
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return render_template(
                    'register.html',
                    message='That username or email is already registered.',
                ), 409

        return redirect(url_for('register', registered='1'))

    return render_template('register.html')


@create_app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        with SessionLocal() as db_session:
            user = db_session.scalar(
                select(User).where(User.username == username)
            )

        password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
        if user is None or not hmac.compare_digest(user.password_hash, password_hash):
            return render_template(
                'login.html',
                message='Invalid username or password.',
            ), 401

        session['user_id'] = user.id
        session['username'] = user.username
        cart = session.get('cart', {})
        with SessionLocal() as db_session:
            saved_items = db_session.scalars(
                select(CartItem).where(CartItem.user_id == user.id)
            ).all()
            for item in saved_items:
                key = str(item.position_id)
                cart[key] = cart.get(key, 0) + item.quantity
            save_cart(db_session, user.id, cart)
            db_session.commit()
        session['cart'] = cart
        return redirect(url_for('main'))

    return render_template('login.html')


@create_app.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id is not None:
        with SessionLocal() as db_session:
            save_cart(db_session, user_id, session.get('cart', {}))
            db_session.commit()
    session.clear()
    return redirect(url_for('main'))


@create_app.route('/orders')
def orders():
    user_id = session.get('user_id')
    if user_id is None:
        return redirect(url_for('login'))

    grouped_orders = {}
    with SessionLocal() as db_session:
        order_items = db_session.execute(
            select(Order, Position)
            .join(Position, Order.dish_id == Position.id)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc(), Order.id.desc())
        ).all()

    for order, position in order_items:
        group_id = order.order_group or f'legacy-{order.id}'
        if group_id not in grouped_orders:
            grouped_orders[group_id] = {
                'id': order.id,
                'created_at': order.created_at,
                'items': [],
                'total': 0,
            }
        grouped_orders[group_id]['items'].append({
            'dish_name': position.dish_name,
            'quantity': order.quantity,
            'subtotal': order.total_price,
        })
        grouped_orders[group_id]['total'] += order.total_price

    return render_template(
        'orders.html',
        orders=list(grouped_orders.values()),
    )


@create_app.route('/my_order/<int:order_id>')
def my_order(order_id):
    user_id = session.get('user_id')
    if user_id is None:
        return redirect(url_for('login'))

    with SessionLocal() as db_session:
        requested_order = db_session.scalar(
            select(Order).where(
                Order.id == order_id,
                Order.user_id == user_id,
            )
        )
        if requested_order is None:
            return render_template('my_order.html', order=None), 404

        order_query = (
            select(Order, Position)
            .join(Position, Order.dish_id == Position.id)
            .where(Order.user_id == user_id)
        )
        if requested_order.order_group is None:
            order_query = order_query.where(Order.id == requested_order.id)
        else:
            order_query = order_query.where(
                Order.order_group == requested_order.order_group
            )
        order_items = db_session.execute(
            order_query.order_by(Order.id)
        ).all()

    order = {
        'created_at': requested_order.created_at,
        'items': [
            {
                'dish_name': item.dish_name,
                'quantity': item_order.quantity,
                'subtotal': item_order.total_price,
            }
            for item_order, item in order_items
        ],
        'total': sum(item_order.total_price for item_order, _ in order_items),
    }
    return render_template('my_order.html', order=order)


@create_app.route('/reservations', methods=['GET', 'POST'])
def reservations():
    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        reservation_time = request.form.get('reservation_time', '').strip()
        number_of_people = request.form.get('number_of_people', type=int)
        table_number = request.form.get('table_number', type=int)

        if (
            not customer_name
            or len(customer_name) > 100
            or not reservation_time
            or number_of_people is None
            or number_of_people < 1
            or table_number is None
            or table_number < 1
        ):
            return render_template(
                'reservations.html',
                message='Enter a name, a reservation time, and positive guest and table numbers.',
                form_data=request.form,
            ), 400

        try:
            parsed_time = datetime.fromisoformat(reservation_time)
        except ValueError:
            return render_template(
                'reservations.html',
                message='Enter a valid reservation date and time.',
                form_data=request.form,
            ), 400

        if parsed_time.tzinfo is not None or parsed_time <= datetime.now():
            return render_template(
                'reservations.html',
                message='Reservation time must be a future local date and time.',
                form_data=request.form,
            ), 400

        with SessionLocal() as db_session:
            db_session.add(
                Reservation(
                    customer_name=customer_name,
                    reservation_time=reservation_time,
                    number_of_people=number_of_people,
                    table_number=table_number,
                )
            )
            db_session.commit()

        flash('Your table reservation has been saved.')
        return redirect(url_for('reservations'))

    return render_template('reservations.html', form_data={})

if __name__ == '__main__':
    create_app.run(debug=True, port=5002)