"""Add clearly fictional teaching data through the normal business workflow."""

import uuid
from pathlib import Path
from trade import Marketplace


def key():
    return str(uuid.uuid4())


def ensure_user(app, name, nickname, phone):
    if not app.db.execute('SELECT 1 FROM accounts WHERE username=?', (name,)).fetchone():
        app.register(name, 'DemoPass123', nickname, phone)
    return app.login(name, 'DemoPass123')


def add_product(app, seller, admin, title, category, price):
    existing = app.db.execute('SELECT id FROM products WHERE title=? AND seller_id=?',
                              (title, seller['id'])).fetchone()
    if existing:
        return app.product_detail(existing['id'], seller['token'])
    product = app.create_product(seller['token'], key(), {
        'title': title, 'description': '课程演示数据，线下当面交易。',
        'category': category, 'condition': '正常使用', 'price': price,
    })
    product = app.product_transition(seller['token'], key(), product['id'], product['version'], 'submit')
    return app.review_product(admin['token'], key(), product['id'], product['version'], 'approve')


def reserve_once(app, buyer, product):
    existing = app.db.execute('SELECT id FROM reservations WHERE product_id=? AND buyer_id=? '
                              'ORDER BY created_at DESC LIMIT 1', (product['id'], buyer['id'])).fetchone()
    if existing:
        return next(row for row in app.reservations(buyer['token']) if row['id'] == existing['id'])
    return app.reserve(buyer['token'], key(), product['id'], product['version'])


def main():
    app = Marketplace(Path(__file__).with_name('campus_trade.sqlite3'))
    try:
        admin = app.login('admin01', 'AdminPass123')
        student = app.login('student01', 'StudentPass123')
        seller = ensure_user(app, 'demo_seller', '演示卖家', '13800000002')
        buyer = ensure_user(app, 'demo_buyer', '演示买家', '13800000003')
        cases = [
            (student, buyer, '机械键盘（演示）', '数码产品', '55.00', 'pending'),
            (seller, student, '电热水壶（演示）', '生活用品', '29.00', 'pending'),
            (seller, student, '线性代数教材（演示）', '教材书籍', '16.00', 'confirmed'),
            (seller, student, '羽毛球拍（演示）', '运动用品', '35.00', 'cancelled'),
        ]
        for owner, purchaser, title, category, price, target in cases:
            product = add_product(app, owner, admin, title, category, price)
            reservation = reserve_once(app, purchaser, product)
            if target == 'confirmed' and reservation['status'] == 'pending':
                app.reservation_transition(owner['token'], key(), reservation['id'], reservation['version'], 'confirm')
            elif target == 'cancelled' and reservation['status'] in ('pending', 'confirmed'):
                app.reservation_transition(purchaser['token'], key(), reservation['id'], reservation['version'],
                                           'cancel', '演示取消预约', True)
        for title, category, price in [('折叠台灯（演示）', '生活用品', '29.00'),
                                       ('跑步腰包（演示）', '运动用品', '35.00'),
                                       ('概率论教材（演示）', '教材书籍', '16.00')]:
            add_product(app, seller, admin, title, category, price)
        print('已准备虚构演示商品与预约。')
    finally:
        app.close()


if __name__ == '__main__':
    main()
