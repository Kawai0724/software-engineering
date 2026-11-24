"""Local campus marketplace service. All business changes use SQLite transactions."""

import datetime as dt
import io
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path


CATEGORIES = ('教材书籍', '数码产品', '学习用品', '运动用品', '生活用品', '其他')
CONDITIONS = ('全新', '近新', '正常使用', '明显磨损')
REPORT_REASONS = ('违禁或不适宜商品', '虚假或误导信息', '泄露联系方式', '其他')
ACTIVE = ('pending', 'confirmed')
VISIBLE = ('published', 'reserved')


class TradeError(Exception):
    """A safe, user-facing business error."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def identifier():
    return str(uuid.uuid4())


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def require_text(value, name, low, high):
    if not isinstance(value, str):
        raise TradeError(name + '必须是文本')
    value = value.strip()
    if not low <= len(value) <= high:
        raise TradeError(f'{name}长度须为 {low} 至 {high} 字')
    return value


def money(value):
    if value in ('', None):
        return None
    try:
        text = str(value)
        if not re.fullmatch(r'\d+(?:\.\d{1,2})?', text):
            raise ValueError
        amount = Decimal(text)
        cents = int(amount * 100)
        if not 1 <= cents <= 9999999:
            raise ValueError
        return cents
    except (ValueError, InvalidOperation):
        raise TradeError('价格须在 0.01 至 99999.99 元之间，最多两位小数')


def account_fields(username, password, nickname, phone):
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{3,20}', username):
        raise TradeError('用户名须为 3 至 20 位字母、数字或下划线')
    if (not isinstance(password, str) or not 10 <= len(password) <= 64
            or not re.search(r'[A-Za-z]', password) or not re.search(r'[0-9]', password)):
        raise TradeError('密码须为 10 至 64 字符且包含字母和数字')
    nickname = require_text(nickname, '昵称', 1, 20)
    if not isinstance(phone, str) or not re.fullmatch(r'[0-9]{11}', phone):
        raise TradeError('电话须为 11 位数字')
    return username, password, nickname, phone


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()


class Marketplace:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self.db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=30000')
        schema = Path(__file__).with_name('schema.sql').read_text(encoding='utf-8')
        self.db.executescript(schema)

    def close(self):
        self.db.close()

    def begin(self):
        self.db.execute('BEGIN IMMEDIATE')

    def audit(self, actor, operation, kind, resource=None, request=None,
              result='success', reason='', before=None, after=None):
        self.db.execute(
            'INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (identifier(), now(), actor, operation, kind, resource, request,
             result, reason, before, after))

    def one(self, table, item_id):
        if table not in ('accounts', 'products', 'reservations', 'reports'):
            raise ValueError('invalid table')
        row = self.db.execute(f'SELECT * FROM {table} WHERE id=?', (item_id,)).fetchone()
        if row is None:
            raise TradeError('资源不存在或无权访问', 404)
        return row

    def initialize_admin(self, username, password, nickname, phone):
        self.begin()
        try:
            if self.db.execute("SELECT 1 FROM accounts WHERE role='admin'").fetchone():
                raise TradeError('管理员已初始化', 409)
            result = self._register(username, password, nickname, phone, 'admin')
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def _register(self, username, password, nickname, phone, role):
        username, password, nickname, phone = account_fields(username, password, nickname, phone)
        account_id, salt = identifier(), secrets.token_hex(16)
        try:
            self.db.execute('INSERT INTO accounts(id,username,password_hash,salt,nickname,phone,role) '
                            'VALUES (?,?,?,?,?,?,?)',
                            (account_id, username, password_hash(password, salt), salt,
                             nickname, phone, role))
        except sqlite3.IntegrityError:
            raise TradeError('用户名已被使用', 409)
        self.audit(account_id, 'register', 'account', account_id)
        return {'id': account_id, 'role': role}

    def register(self, username, password, nickname, phone, invitation=None):
        self.begin()
        try:
            role = 'user'
            if invitation:
                invite = self.db.execute('SELECT * FROM invitations WHERE code_hash=?',
                                         (digest(invitation),)).fetchone()
                if not invite or invite['consumed_by']:
                    raise TradeError('邀请码无效或已使用')
                role = 'admin'
            result = self._register(username, password, nickname, phone, role)
            if invitation:
                self.db.execute('UPDATE invitations SET consumed_by=? WHERE code_hash=?',
                                (result['id'], digest(invitation)))
                self.audit(result['id'], 'consume_invitation', 'account', result['id'])
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def login(self, username, password):
        self.begin()
        try:
            user = self.db.execute('SELECT * FROM accounts WHERE username=?', (username,)).fetchone()
            timestamp = time.time()
            if user and user['locked_until'] > timestamp:
                self.audit(user['id'], 'login', 'account', user['id'], result='failure', reason='locked')
                self.db.commit()
                raise TradeError('登录失败或账号暂时锁定', 401)
            valid = (user is not None and isinstance(password, str)
                     and hmac.compare_digest(password_hash(password, user['salt']), user['password_hash']))
            if not valid:
                if user:
                    failures = (0 if user['locked_until'] else user['fail_count']) + 1
                    self.db.execute('UPDATE accounts SET fail_count=?, locked_until=? WHERE id=?',
                                    (failures, timestamp + 900 if failures >= 5 else 0, user['id']))
                self.audit(user['id'] if user else None, 'login', 'account',
                           user['id'] if user else None, result='failure', reason='credentials')
                self.db.commit()
                raise TradeError('登录失败或账号暂时锁定', 401)
            token = secrets.token_urlsafe(32)
            self.db.execute('UPDATE accounts SET fail_count=0, locked_until=0 WHERE id=?', (user['id'],))
            self.db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), user['id'], timestamp))
            self.audit(user['id'], 'login', 'account', user['id'])
            self.db.commit()
            return {'token': token, 'id': user['id'], 'role': user['role'], 'nickname': user['nickname']}
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def actor(self, token, role=None):
        if not isinstance(token, str):
            raise TradeError('请先登录', 401)
        row = self.db.execute('SELECT a.*, s.last_active FROM sessions s JOIN accounts a '
                              'ON a.id=s.account_id WHERE s.token_hash=?', (digest(token),)).fetchone()
        if not row or time.time() - row['last_active'] >= 1800:
            if row:
                self.db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token),))
            raise TradeError('会话失效，请重新登录', 401)
        if role and row['role'] != role:
            raise TradeError('没有权限', 403)
        self.db.execute('UPDATE sessions SET last_active=? WHERE token_hash=?', (time.time(), digest(token)))
        return row

    def logout(self, token):
        actor = self.actor(token)
        self.begin()
        try:
            self.db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token),))
            self.audit(actor['id'], 'logout', 'account', actor['id'])
            self.db.commit()
            return {'ok': True}
        except Exception:
            self.db.rollback()
            raise

    def mutate(self, token, operation, request_id, payload, action, role=None):
        actor = self.actor(token, role)
        request_id = require_text(request_id, '请求标识', 1, 128)
        payload_hash = digest(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')))
        self.begin()
        try:
            existing = self.db.execute('SELECT * FROM idempotency WHERE actor_id=? AND operation=? '
                                       'AND request_id=?', (actor['id'], operation, request_id)).fetchone()
            if existing:
                if existing['payload_hash'] != payload_hash:
                    raise TradeError('请求标识已用于不同内容', 409)
                result = self.read_resource(actor, existing['resource_type'], existing['resource_id'])
                self.db.commit()
                return result
            kind, resource_id, before, after = action(actor)
            self.db.execute('INSERT INTO idempotency VALUES (?,?,?,?,?,?)',
                            (actor['id'], operation, request_id, payload_hash, kind, resource_id))
            if before != after or before is None:
                self.audit(actor['id'], operation, kind, resource_id, request_id, before=before, after=after)
            result = self.read_resource(actor, kind, resource_id)
            self.db.commit()
            return result
        except Exception as exc:
            self.db.rollback()
            if isinstance(exc, TradeError):
                self.audit(actor['id'], operation, 'request', request=request_id,
                           result='failure', reason=str(exc.status))
            raise

    def read_resource(self, actor, kind, item_id):
        if kind == 'account':
            row = self.one('accounts', item_id)
            if actor['id'] != item_id:
                raise TradeError('无权访问', 403)
            return {key: row[key] for key in ('id', 'username', 'nickname', 'phone', 'role')}
        if kind == 'product':
            row = self.one('products', item_id)
            if actor['role'] != 'admin' and actor['id'] != row['seller_id'] and row['status'] not in VISIBLE:
                raise TradeError('资源不存在或无权访问', 404)
            result = dict(row)
            result['images'] = [dict(x) for x in self.db.execute('SELECT id,filename,mime FROM images '
                                                                   'WHERE product_id=?', (item_id,))]
            return result
        if kind == 'reservation':
            row = self.one('reservations', item_id)
            if actor['role'] != 'admin' and actor['id'] not in (row['buyer_id'], row['seller_id']):
                raise TradeError('资源不存在或无权访问', 404)
            result = dict(row)
            result['snapshot'] = json.loads(result['snapshot'])
            return result
        if kind == 'report':
            row = self.one('reports', item_id)
            if actor['role'] != 'admin' and actor['id'] != row['reporter_id']:
                raise TradeError('资源不存在或无权访问', 404)
            return dict(row)
        if kind == 'invitation':
            # Invitation codes are deliberately never persisted in replay results.
            return {'id': item_id, 'message': '邀请码已生成；重放不会显示明文'}
        raise TradeError('资源类型无效')

    def profile(self, token):
        actor = self.actor(token)
        return self.read_resource(actor, 'account', actor['id'])

    def product_detail(self, product_id, token=None):
        if token:
            return self.read_resource(self.actor(token), 'product', product_id)
        product = self.one('products', product_id)
        if product['status'] not in VISIBLE or product['violation']:
            raise TradeError('资源不存在或无权访问', 404)
        result = dict(product)
        result['images'] = [dict(row) for row in self.db.execute(
            'SELECT id,filename,mime FROM images WHERE product_id=?', (product_id,))]
        return result

    def history_events(self, token, reservation_id):
        actor = self.actor(token, 'user')
        item = self.one('reservations', reservation_id)
        if actor['id'] not in (item['buyer_id'], item['seller_id']):
            raise TradeError('资源不存在或无权访问', 404)
        rows = self.db.execute('SELECT id,occurred_at,operation,resource_id,result,before_state,after_state '
                               "FROM audit_events WHERE resource_type='reservation' AND resource_id=? "
                               'ORDER BY occurred_at,id', (reservation_id,)).fetchall()
        return [dict(row) for row in rows]

    def update_profile(self, token, request_id, nickname, phone):
        payload = {'nickname': nickname, 'phone': phone}
        def action(actor):
            nick = require_text(nickname, '昵称', 1, 20)
            if not isinstance(phone, str) or not re.fullmatch(r'[0-9]{11}', phone):
                raise TradeError('电话须为 11 位数字')
            self.db.execute('UPDATE accounts SET nickname=?, phone=? WHERE id=?', (nick, phone, actor['id']))
            return 'account', actor['id'], None, None
        return self.mutate(token, 'profile_update', request_id, payload, action, 'user')

    def create_invitation(self, token, request_id):
        code = secrets.token_urlsafe(24)
        def action(actor):
            self.db.execute('INSERT INTO invitations(code_hash,created_by) VALUES (?,?)',
                            (digest(code), actor['id']))
            return 'invitation', digest(code), None, None
        result = self.mutate(token, 'invitation_create', request_id, {}, action, 'admin')
        if result['id'] == digest(code):
            result['code'] = code
        return result

    def check_version(self, row, version):
        if not isinstance(version, int) or row['version'] != version:
            raise TradeError('版本已变化，请刷新后重试', 409)

    def product_values(self, data, complete=False):
        result = {}
        for name, label, maximum in [('title', '标题', 50), ('description', '描述', 2000)]:
            value = data.get(name, '')
            if not isinstance(value, str):
                raise TradeError(label + '必须是文本')
            value = value.strip()
            if len(value) > maximum or (complete and not value):
                raise TradeError(label + '长度不符合要求')
            result[name] = value
        for name, choices, label in [('category', CATEGORIES, '分类'), ('condition', CONDITIONS, '成色')]:
            value = data.get(name, '')
            if value not in choices and (value or complete):
                raise TradeError(label + '无效')
            result[name] = value
        result['price_cents'] = money(data.get('price'))
        if complete and result['price_cents'] is None:
            raise TradeError('请填写价格')
        return result

    def create_product(self, token, request_id, data):
        def action(actor):
            values = self.product_values(data)
            product_id, stamp = identifier(), now()
            self.db.execute('INSERT INTO products(id,seller_id,title,description,category,condition,price_cents,'
                            'status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                            (product_id, actor['id'], values['title'], values['description'],
                             values['category'], values['condition'], values['price_cents'], 'draft', stamp, stamp))
            return 'product', product_id, None, 'draft'
        return self.mutate(token, 'product_create', request_id, data, action, 'user')

    def edit_product(self, token, request_id, product_id, version, data):
        payload = {'product_id': product_id, 'version': version, 'data': data}
        def action(actor):
            product = self.one('products', product_id)
            if product['seller_id'] != actor['id']:
                raise TradeError('资源不存在或无权访问', 404)
            self.check_version(product, version)
            if product['status'] not in ('draft', 'rejected', 'published', 'withdrawn'):
                raise TradeError('当前商品状态不允许编辑', 409)
            values = self.product_values(data)
            self.db.execute('UPDATE products SET title=?,description=?,category=?,condition=?,price_cents=?,'
                            "status='draft',version=version+1,updated_at=? WHERE id=?",
                            (values['title'], values['description'], values['category'], values['condition'],
                             values['price_cents'], now(), product_id))
            return 'product', product_id, product['status'], 'draft'
        return self.mutate(token, 'product_edit', request_id, payload, action, 'user')

    def product_transition(self, token, request_id, product_id, version, transition):
        payload = {'product_id': product_id, 'version': version, 'transition': transition}
        def action(actor):
            product = self.one('products', product_id)
            if product['seller_id'] != actor['id']:
                raise TradeError('资源不存在或无权访问', 404)
            self.check_version(product, version)
            allowed = {'submit': (('draft', 'withdrawn'), 'pending'),
                       'retract': (('pending',), 'draft'), 'withdraw': (('published',), 'withdrawn')}
            if transition not in allowed or product['status'] not in allowed[transition][0]:
                raise TradeError('当前状态不允许此操作', 409)
            target = allowed[transition][1]
            if transition == 'submit':
                self.product_values({'title': product['title'], 'description': product['description'],
                                     'category': product['category'], 'condition': product['condition'],
                                     'price': str(Decimal(product['price_cents']) / 100)
                                     if product['price_cents'] is not None else ''}, complete=True)
                snapshot = json.dumps({k: product[k] for k in ('title', 'description', 'category', 'condition', 'price_cents')},
                                      ensure_ascii=False)
                self.db.execute('INSERT INTO submissions VALUES (?,?,?,?,?)',
                                (identifier(), product_id, product['version'] + 1, snapshot, now()))
            self.db.execute('UPDATE products SET status=?,version=version+1,updated_at=? WHERE id=?',
                            (target, now(), product_id))
            return 'product', product_id, product['status'], target
        return self.mutate(token, 'product_' + transition, request_id, payload, action, 'user')

    def review_product(self, token, request_id, product_id, version, decision, reason=''):
        payload = {'product_id': product_id, 'version': version, 'decision': decision, 'reason': reason}
        def action(actor):
            product = self.one('products', product_id)
            self.check_version(product, version)
            if product['status'] != 'pending' or decision not in ('approve', 'reject'):
                raise TradeError('审核状态或决定无效', 409)
            note = require_text(reason, '驳回原因', 1, 500) if decision == 'reject' else ''
            if decision == 'approve' and re.search(r'(?<!\d)1\d{10}(?!\d)', product['title'] + product['description']):
                raise TradeError('内容包含明显联系方式，请驳回并说明原因')
            target = 'published' if decision == 'approve' else 'rejected'
            stamp = now()
            snapshot = json.dumps({k: product[k] for k in ('title', 'description', 'category', 'condition', 'price_cents')}, ensure_ascii=False)
            self.db.execute('INSERT INTO reviews VALUES (?,?,?,?,?,?,?)',
                            (identifier(), product_id, actor['id'], decision, note, snapshot, stamp))
            self.db.execute('UPDATE products SET status=?,version=version+1,updated_at=?,published_at=? WHERE id=?',
                            (target, stamp, stamp if target == 'published' else product['published_at'], product_id))
            return 'product', product_id, 'pending', target
        return self.mutate(token, 'product_review', request_id, payload, action, 'admin')

    def reserve(self, token, request_id, product_id, version):
        payload = {'product_id': product_id, 'version': version}
        def action(actor):
            product = self.one('products', product_id)
            existing = self.db.execute("SELECT * FROM reservations WHERE product_id=? AND buyer_id=? "
                                       "AND status IN ('pending','confirmed')", (product_id, actor['id'])).fetchone()
            if existing:
                return 'reservation', existing['id'], existing['status'], existing['status']
            if product['seller_id'] == actor['id'] or product['status'] != 'published':
                raise TradeError('商品当前不能预约', 409)
            self.check_version(product, version)
            reservation_id = identifier()
            snapshot = json.dumps({k: product[k] for k in ('title', 'category', 'price_cents')}, ensure_ascii=False)
            self.db.execute('INSERT INTO reservations(id,product_id,buyer_id,seller_id,status,snapshot,created_at) '
                            "VALUES (?,?,?,?, 'pending',?,?)",
                            (reservation_id, product_id, actor['id'], product['seller_id'], snapshot, now()))
            self.db.execute("UPDATE products SET status='reserved',version=version+1,updated_at=? WHERE id=?",
                            (now(), product_id))
            return 'reservation', reservation_id, None, 'pending'
        return self.mutate(token, 'reservation_create', request_id, payload, action, 'user')

    def reservation_transition(self, token, request_id, reservation_id, version, transition,
                               reason='', confirmed=False):
        payload = {'reservation_id': reservation_id, 'version': version, 'transition': transition,
                   'reason': reason, 'confirmed': confirmed}
        def action(actor):
            item = self.one('reservations', reservation_id)
            if actor['id'] not in (item['buyer_id'], item['seller_id']):
                raise TradeError('资源不存在或无权访问', 404)
            self.check_version(item, version)
            stamp = now()
            if transition == 'confirm':
                if actor['id'] != item['seller_id'] or item['status'] != 'pending':
                    raise TradeError('只有卖家可确认待确认预约', 403)
                self.db.execute("UPDATE reservations SET status='confirmed',confirmed_at=?,version=version+1 WHERE id=?",
                                (stamp, reservation_id))
                target = 'confirmed'
            elif transition == 'complete':
                if actor['id'] != item['buyer_id'] or item['status'] != 'confirmed':
                    raise TradeError('只有买家可完成已确认预约', 403)
                self.db.execute("UPDATE reservations SET status='completed',completed_at=?,version=version+1 WHERE id=?",
                                (stamp, reservation_id))
                self.db.execute("UPDATE products SET status='sold',version=version+1,updated_at=? WHERE id=?",
                                (stamp, item['product_id']))
                target = 'completed'
            elif transition == 'cancel':
                if item['status'] not in ACTIVE:
                    raise TradeError('预约已结束', 409)
                if confirmed is not True:
                    raise TradeError('请二次确认取消')
                note = require_text(reason, '取消原因', 1, 500)
                self.db.execute("UPDATE reservations SET status='cancelled',cancelled_at=?,cancelled_by=?,"
                                'cancel_reason=?,version=version+1 WHERE id=?',
                                (stamp, actor['id'], note, reservation_id))
                self.db.execute("UPDATE products SET status='published',version=version+1,updated_at=? WHERE id=?",
                                (stamp, item['product_id']))
                target = 'cancelled'
            else:
                raise TradeError('未知操作')
            return 'reservation', reservation_id, item['status'], target
        return self.mutate(token, 'reservation_' + transition, request_id, payload, action, 'user')

    def contact(self, token, reservation_id):
        actor = self.actor(token, 'user')
        item = self.one('reservations', reservation_id)
        if actor['id'] not in (item['buyer_id'], item['seller_id']) or item['status'] != 'confirmed':
            raise TradeError('当前无权查看联系方式', 403)
        other = item['seller_id'] if actor['id'] == item['buyer_id'] else item['buyer_id']
        phone = self.one('accounts', other)['phone']
        self.audit(actor['id'], 'contact_view', 'reservation', reservation_id)
        return {'phone': phone, 'notice': '已记录或截图的号码无法远程收回。'}

    def submit_report(self, token, request_id, product_id, reason, details):
        payload = {'product_id': product_id, 'reason': reason, 'details': details}
        def action(actor):
            product = self.one('products', product_id)
            history = self.db.execute('SELECT 1 FROM reservations WHERE product_id=? AND buyer_id=?',
                                      (product_id, actor['id'])).fetchone()
            if product['seller_id'] == actor['id'] or (product['status'] not in VISIBLE and not history):
                raise TradeError('资源不存在或无权访问', 404)
            if reason not in REPORT_REASONS:
                raise TradeError('举报原因无效')
            note = require_text(details, '举报说明', 1, 500)
            existing = self.db.execute("SELECT id FROM reports WHERE product_id=? AND reporter_id=? AND status='pending'",
                                       (product_id, actor['id'])).fetchone()
            if existing:
                return 'report', existing['id'], 'pending', 'pending'
            report_id = identifier()
            self.db.execute('INSERT INTO reports(id,product_id,reporter_id,reason,details,status,created_at) '
                            "VALUES (?,?,?,?,?,'pending',?)", (report_id, product_id, actor['id'], reason, note, now()))
            return 'report', report_id, None, 'pending'
        return self.mutate(token, 'report_create', request_id, payload, action, 'user')

    def resolve_report(self, token, request_id, report_id, version, product_version, decision, note):
        payload = {'report_id': report_id, 'version': version, 'product_version': product_version,
                   'decision': decision, 'note': note}
        def action(actor):
            report = self.one('reports', report_id)
            product = self.one('products', report['product_id'])
            self.check_version(report, version)
            self.check_version(product, product_version)
            if report['status'] != 'pending' or decision not in ('reject', 'violation'):
                raise TradeError('举报状态或处置决定无效', 409)
            text = require_text(note, '处置说明', 1, 500)
            stamp = now()
            status = 'rejected' if decision == 'reject' else 'handled'
            if decision == 'violation':
                target = 'sold' if product['status'] == 'sold' else 'banned'
                self.db.execute('UPDATE products SET status=?,violation=1,violation_reason=?,'
                                'version=version+1,updated_at=? WHERE id=?', (target, text, stamp, product['id']))
                self.db.execute("UPDATE reservations SET status='cancelled',cancelled_at=?,cancelled_by=?,"
                                "cancel_reason=?,version=version+1 WHERE product_id=? AND status IN ('pending','confirmed')",
                                (stamp, actor['id'], '管理员违规处置', product['id']))
            self.db.execute('UPDATE reports SET status=?,handling_note=?,handled_at=?,version=version+1 WHERE id=?',
                            (status, text, stamp, report_id))
            return 'report', report_id, 'pending', status
        return self.mutate(token, 'report_resolve', request_id, payload, action, 'admin')

    def products(self, token=None, scope='market', keyword='', category='', minimum='', maximum='',
                 states=None, sort='newest', page=1):
        actor = self.actor(token) if token else None
        conditions, params = [], []
        if scope == 'market':
            conditions.append("status IN ('published','reserved') AND violation=0")
            permitted = set(VISIBLE)
        elif scope == 'mine' and actor and actor['role'] == 'user':
            conditions.append('seller_id=?')
            params.append(actor['id'])
            permitted = {'draft', 'pending', 'rejected', 'published', 'reserved', 'withdrawn', 'sold', 'banned'}
        elif scope == 'admin' and actor and actor['role'] == 'admin':
            permitted = {'draft', 'pending', 'rejected', 'published', 'reserved', 'withdrawn', 'sold', 'banned'}
        else:
            raise TradeError('无权查询此范围', 403)
        if not isinstance(keyword, str) or len(keyword.strip()) > 50:
            raise TradeError('关键词不能超过 50 字')
        if keyword.strip():
            conditions.append('(instr(lower(title),lower(?))>0 OR instr(lower(description),lower(?))>0)')
            params.extend([keyword.strip(), keyword.strip()])
        if category:
            if category not in CATEGORIES:
                raise TradeError('分类无效')
            conditions.append('category=?')
            params.append(category)
        low, high = money(minimum), money(maximum)
        if low is not None and high is not None and low > high:
            raise TradeError('价格下限不能大于上限')
        if low is not None:
            conditions.append('price_cents>=?')
            params.append(low)
        if high is not None:
            conditions.append('price_cents<=?')
            params.append(high)
        if states:
            if not isinstance(states, list) or not set(states) <= permitted:
                raise TradeError('状态筛选无效')
            conditions.append('status IN (' + ','.join('?' for _ in states) + ')')
            params.extend(states)
        ordering = {'newest': ('updated_at DESC' if scope == 'mine' else 'published_at DESC'),
                    'price_asc': 'price_cents ASC', 'price_desc': 'price_cents DESC'}
        if sort not in ordering or not isinstance(page, int) or page < 1:
            raise TradeError('排序或页码无效')
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        total = self.db.execute('SELECT COUNT(*) FROM products' + where, params).fetchone()[0]
        rows = self.db.execute('SELECT * FROM products' + where + ' ORDER BY ' + ordering[sort] + ', id ASC LIMIT 20 OFFSET ?',
                               params + [(page - 1) * 20]).fetchall()
        return {'total': total, 'page': page, 'items': [dict(row) for row in rows], 'notice': '校园身份未核验'}

    def reservations(self, token):
        actor = self.actor(token)
        if actor['role'] == 'admin':
            rows = self.db.execute('SELECT * FROM reservations ORDER BY created_at DESC').fetchall()
        else:
            rows = self.db.execute('SELECT * FROM reservations WHERE buyer_id=? OR seller_id=? ORDER BY created_at DESC',
                                   (actor['id'], actor['id'])).fetchall()
        return [self.read_resource(actor, 'reservation', row['id']) for row in rows]

    def reports(self, token):
        actor = self.actor(token)
        if actor['role'] == 'admin':
            rows = self.db.execute('SELECT * FROM reports ORDER BY created_at DESC').fetchall()
        else:
            rows = self.db.execute('SELECT * FROM reports WHERE reporter_id=? ORDER BY created_at DESC',
                                   (actor['id'],)).fetchall()
        return [dict(row) for row in rows]

    def reviews(self, token, product_id):
        actor = self.actor(token)
        product = self.one('products', product_id)
        if actor['role'] != 'admin' and actor['id'] != product['seller_id']:
            raise TradeError('资源不存在或无权访问', 404)
        return [dict(row) for row in self.db.execute('SELECT * FROM reviews WHERE product_id=? ORDER BY created_at DESC',
                                                      (product_id,))]

    def stats(self, token, start=None, end=None):
        actor = self.actor(token)
        try:
            first = dt.date.fromisoformat(start) if start else None
            last = dt.date.fromisoformat(end) if end else None
        except (ValueError, TypeError):
            raise TradeError('日期格式应为 YYYY-MM-DD')
        if first and last and first > last:
            raise TradeError('开始日期不能晚于结束日期')
        tz = dt.timezone(dt.timedelta(hours=8))
        conditions = ["status='completed'"]
        params = []
        if first:
            conditions.append('completed_at>=?')
            params.append(dt.datetime.combine(first, dt.time.min, tz).astimezone(dt.timezone.utc).isoformat())
        if last:
            conditions.append('completed_at<?')
            params.append(dt.datetime.combine(last + dt.timedelta(days=1), dt.time.min, tz).astimezone(dt.timezone.utc).isoformat())
        rows = self.db.execute('SELECT * FROM reservations WHERE ' + ' AND '.join(conditions), params).fetchall()
        def aggregate(items):
            return {'count': len(items), 'price_cents': sum(json.loads(x['snapshot'])['price_cents'] for x in items)}
        result = {'notice': '标价合计不是支付流水或实际收款证明'}
        if actor['role'] == 'admin':
            result['states'] = {x['status']: x['count'] for x in self.db.execute(
                'SELECT status,COUNT(*) AS count FROM products GROUP BY status')}
            result['transactions'] = aggregate(rows)
            result['by_category'] = {category: aggregate([x for x in rows if json.loads(x['snapshot'])['category'] == category])
                                     for category in CATEGORIES}
            result['violations'] = self.db.execute('SELECT COUNT(*) FROM products WHERE violation=1').fetchone()[0]
        else:
            result['buyer'] = aggregate([x for x in rows if x['buyer_id'] == actor['id']])
            result['seller'] = aggregate([x for x in rows if x['seller_id'] == actor['id']])
        return result

    def logs(self, token, filters=None, page=1):
        actor = self.actor(token, 'admin')
        del actor
        filters = filters or {}
        if not isinstance(page, int) or page < 1:
            raise TradeError('页码无效')
        conditions, args = [], []
        for key in ('actor_id', 'resource_id', 'operation', 'result'):
            if filters.get(key):
                conditions.append(key + '=?')
                args.append(filters[key])
        for key, op in [('start', '>='), ('end', '<=')]:
            if filters.get(key):
                conditions.append('occurred_at' + op + '?')
                args.append(filters[key])
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        total = self.db.execute('SELECT COUNT(*) FROM audit_events' + where, args).fetchone()[0]
        rows = self.db.execute('SELECT * FROM audit_events' + where + ' ORDER BY occurred_at DESC, id LIMIT 20 OFFSET ?',
                               args + [(page - 1) * 20]).fetchall()
        return {'total': total, 'page': page, 'items': [dict(x) for x in rows]}

    def backup(self, destination):
        target = sqlite3.connect(str(destination))
        try:
            self.db.backup(target)
        finally:
            target.close()

    def add_image(self, token, request_id, product_id, version, path):
        from PIL import Image, UnidentifiedImageError
        file_path = Path(path)
        try:
            content = file_path.read_bytes()
            if len(content) > 5 * 1024 * 1024:
                raise TradeError('图片不能超过 5 MB')
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
                image_type = image.format
            with Image.open(io.BytesIO(content)) as image:
                image.load()
            if image_type not in ('JPEG', 'PNG'):
                raise TradeError('只接受 JPEG 或 PNG 图片')
        except (OSError, UnidentifiedImageError, ValueError):
            raise TradeError('图片无法读取或解码')
        payload = {'product_id': product_id, 'version': version, 'content_hash': hashlib.sha256(content).hexdigest()}
        def action(actor):
            product = self.one('products', product_id)
            if product['seller_id'] != actor['id']:
                raise TradeError('资源不存在或无权访问', 404)
            self.check_version(product, version)
            if product['status'] not in ('draft', 'rejected', 'published', 'withdrawn'):
                raise TradeError('当前商品状态不能修改图片', 409)
            count = self.db.execute('SELECT COUNT(*) FROM images WHERE product_id=?', (product_id,)).fetchone()[0]
            if count >= 5:
                raise TradeError('每个商品最多 5 张图片')
            image_id = identifier()
            mime = 'image/jpeg' if image_type == 'JPEG' else 'image/png'
            self.db.execute('INSERT INTO images VALUES (?,?,?,?,?)',
                            (image_id, product_id, image_id + ('.jpg' if image_type == 'JPEG' else '.png'), mime, content))
            self.db.execute("UPDATE products SET status='draft',version=version+1,updated_at=? WHERE id=?",
                            (now(), product_id))
            return 'product', product_id, product['status'], 'draft'
        return self.mutate(token, 'image_add', request_id, payload, action, 'user')

    def remove_image(self, token, request_id, product_id, version, image_id):
        payload = {'product_id': product_id, 'version': version, 'image_id': image_id}
        def action(actor):
            product = self.one('products', product_id)
            if product['seller_id'] != actor['id']:
                raise TradeError('资源不存在或无权访问', 404)
            self.check_version(product, version)
            if product['status'] not in ('draft', 'rejected', 'published', 'withdrawn'):
                raise TradeError('当前商品状态不能修改图片', 409)
            cursor = self.db.execute('DELETE FROM images WHERE id=? AND product_id=?', (image_id, product_id))
            if cursor.rowcount != 1:
                raise TradeError('图片不存在', 404)
            self.db.execute("UPDATE products SET status='draft',version=version+1,updated_at=? WHERE id=?",
                            (now(), product_id))
            return 'product', product_id, product['status'], 'draft'
        return self.mutate(token, 'image_remove', request_id, payload, action, 'user')

    def export_image(self, token, image_id, destination):
        row = self.db.execute('SELECT * FROM images WHERE id=?', (image_id,)).fetchone()
        if not row:
            raise TradeError('图片不存在', 404)
        product = self.one('products', row['product_id'])
        actor = self.actor(token) if token else None
        if product['status'] not in VISIBLE or product['violation']:
            if not actor or (actor['role'] != 'admin' and actor['id'] != product['seller_id']):
                raise TradeError('图片不存在', 404)
        Path(destination).write_bytes(row['data'])
        return {'mime': row['mime'], 'path': str(destination)}
