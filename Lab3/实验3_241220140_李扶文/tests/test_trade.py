import concurrent.futures
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trade import Marketplace, TradeError
from PIL import Image


class MarketplaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.app = Marketplace(self.path)
        self.app.initialize_admin('admin01', 'AdminPass123', '管理员', '13800000000')
        self.admin = self.app.login('admin01', 'AdminPass123')['token']
        self.seller = self.user('seller01', '13800000001')
        self.buyer = self.user('buyer001', '13800000002')
        self.other = self.user('buyer002', '13800000003')

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def user(self, name, phone):
        self.app.register(name, 'Password123', name, phone)
        return self.app.login(name, 'Password123')['token']

    def published(self):
        data = {'title': '教材', 'description': '九成新', 'category': '教材书籍',
                'condition': '近新', 'price': '12.30'}
        product = self.app.create_product(self.seller, 'p-create', data)
        product = self.app.product_transition(self.seller, 'p-submit', product['id'], product['version'], 'submit')
        return self.app.review_product(self.admin, 'p-review', product['id'], product['version'], 'approve')

    def test_trade_flow_privacy_replay_and_snapshots(self):
        p = self.published()
        r = self.app.reserve(self.buyer, 'reserve-1', p['id'], p['version'])
        self.assertEqual(r['snapshot']['price_cents'], 1230)
        with self.assertRaises(TradeError):
            self.app.contact(self.buyer, r['id'])
        self.assertEqual(r['id'], self.app.reserve(self.buyer, 'reserve-2', p['id'], 1)['id'])
        with self.assertRaises(TradeError):
            self.app.reserve(self.other, 'other-reserve', p['id'], p['version'])
        with self.assertRaises(TradeError):
            self.app.reservation_transition(self.buyer, 'bad-confirm', r['id'], r['version'], 'confirm')
        r = self.app.reservation_transition(self.seller, 'confirm', r['id'], r['version'], 'confirm')
        self.assertEqual(self.app.contact(self.buyer, r['id'])['phone'], '13800000001')
        self.app.update_profile(self.seller, 'profile', '新昵称', '13800000009')
        self.assertEqual(self.app.contact(self.buyer, r['id'])['phone'], '13800000009')
        r = self.app.reservation_transition(self.buyer, 'complete', r['id'], r['version'], 'complete')
        self.assertEqual(r['status'], 'completed')
        self.assertEqual(self.app.reserve(self.buyer, 'reserve-1', p['id'], p['version'])['status'], 'completed')
        with self.assertRaises(TradeError):
            self.app.contact(self.buyer, r['id'])
        self.assertEqual(self.app.stats(self.buyer)['buyer'], {'count': 1, 'price_cents': 1230})
        self.assertEqual(self.app.products(scope='market')['total'], 0)

    def test_version_cancel_and_report_violation(self):
        p = self.published()
        r = self.app.reserve(self.buyer, 'r1', p['id'], p['version'])
        with self.assertRaises(TradeError):
            self.app.reservation_transition(self.buyer, 'bad-cancel', r['id'], r['version'], 'cancel', '不需要')
        r = self.app.reservation_transition(self.seller, 'cancel', r['id'], r['version'], 'cancel', '时间不合适', True)
        self.assertEqual(r['status'], 'cancelled')
        p = self.app.products(scope='market')['items'][0]
        r = self.app.reserve(self.buyer, 'r2', p['id'], p['version'])
        report = self.app.submit_report(self.other, 'report', p['id'], '虚假或误导信息', '信息不实')
        p = self.app.products(self.admin, scope='admin')['items'][0]
        with self.assertRaises(TradeError):
            self.app.resolve_report(self.admin, 'old', report['id'], report['version'], p['version'] - 1, 'violation', '核实违规')
        self.app.resolve_report(self.admin, 'resolve', report['id'], report['version'], p['version'], 'violation', '核实违规')
        self.assertEqual(self.app.reservations(self.buyer)[0]['status'], 'cancelled')
        self.assertEqual(self.app.products(scope='market')['total'], 0)

    def test_concurrent_reservation_one_winner(self):
        p = self.published()
        tokens = [self.buyer, self.other]
        for i in range(18):
            tokens.append(self.user('user%04d' % i, '139%08d' % i))
        def attempt(pair):
            index, token = pair
            service = Marketplace(self.path)
            try:
                service.reserve(token, 'race-' + str(index), p['id'], p['version'])
                return True
            except TradeError:
                return False
            finally:
                service.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(attempt, enumerate(tokens)))
        self.assertEqual(sum(results), 1)
        count = self.app.db.execute("SELECT COUNT(*) FROM reservations WHERE status IN ('pending','confirmed')").fetchone()[0]
        self.assertEqual(count, 1)

    def test_bad_inputs_and_audit_secrecy(self):
        with self.assertRaises(TradeError):
            self.app.register('SELLER01', 'Password123', '重复', '13800000004')
        with self.assertRaises(TradeError):
            self.app.create_product(self.seller, 'bad', {'price': '1.001'})
        with self.assertRaises(TradeError):
            self.app.logs(self.buyer)
        logs = json.dumps(self.app.logs(self.admin), ensure_ascii=False)
        self.assertNotIn('Password123', logs)
        self.assertNotIn('13800000001', logs)

    def test_invitation_is_single_use_and_role_is_separate(self):
        with self.assertRaises(TradeError):
            self.app.create_invitation(self.buyer, 'forbidden')
        invite = self.app.create_invitation(self.admin, 'invite')
        self.assertIn('code', invite)
        self.assertNotIn('code', self.app.create_invitation(self.admin, 'invite'))
        new = self.app.register('admin02', 'Password123', '管理员2', '13800000004', invite['code'])
        self.assertEqual(new['role'], 'admin')
        with self.assertRaises(TradeError):
            self.app.register('admin03', 'Password123', '管理员3', '13800000005', invite['code'])
        with self.assertRaises(TradeError):
            self.app.create_product(self.admin, 'invalid', {})

    def test_image_validation_and_access(self):
        image = Path(self.temp.name) / 'image.png'
        Image.new('RGB', (3, 3), 'blue').save(image)
        bad = Path(self.temp.name) / 'fake.png'
        bad.write_bytes(b'not an image')
        product = self.app.create_product(self.seller, 'draft', {})
        with self.assertRaises(TradeError):
            self.app.add_image(self.seller, 'bad-image', product['id'], product['version'], str(bad))
        product = self.app.add_image(self.seller, 'image', product['id'], product['version'], str(image))
        self.assertEqual(len(product['images']), 1)
        image_id = product['images'][0]['id']
        with self.assertRaises(TradeError):
            self.app.export_image(self.other, image_id, str(Path(self.temp.name) / 'leak.png'))
        out = Path(self.temp.name) / 'copy.png'
        self.app.export_image(self.seller, image_id, str(out))
        self.assertEqual(image.read_bytes(), out.read_bytes())
        product = self.app.remove_image(self.seller, 'remove', product['id'], product['version'], image_id)
        self.assertEqual(product['images'], [])

    def test_lockout_and_session_invalidation(self):
        for _ in range(5):
            with self.assertRaises(TradeError):
                self.app.login('buyer001', 'wrong')
        with self.assertRaises(TradeError):
            self.app.login('buyer001', 'Password123')
        self.app.logout(self.buyer)
        with self.assertRaises(TradeError):
            self.app.profile(self.buyer)
        account = self.app.db.execute("SELECT * FROM accounts WHERE username='buyer001'").fetchone()
        self.app.db.execute('UPDATE accounts SET locked_until=1 WHERE id=?', (account['id'],))
        self.assertTrue(self.app.login('buyer001', 'Password123')['token'])

    def test_idempotency_checks_payload_and_no_duplicate_success(self):
        data = {'title': '书', 'price': '10'}
        product = self.app.create_product(self.seller, 'same-key', data)
        for _ in range(10):
            self.assertEqual(self.app.create_product(self.seller, 'same-key', data)['id'], product['id'])
        with self.assertRaises(TradeError):
            self.app.create_product(self.seller, 'same-key', {'title': '另一件'})
        count = self.app.db.execute("SELECT COUNT(*) FROM audit_events WHERE operation='product_create' "
                                    "AND result='success'").fetchone()[0]
        self.assertEqual(count, 1)

    def test_uml_market_browse_filter_sort_and_access(self):
        first = self.published()
        second = self.app.create_product(self.seller, 'second', {
            'title': 'Python入门', 'description': '学习用书', 'category': '教材书籍',
            'condition': '全新', 'price': '30.00'})
        second = self.app.product_transition(self.seller, 'second-submit', second['id'], second['version'], 'submit')
        second = self.app.review_product(self.admin, 'second-review', second['id'], second['version'], 'approve')
        draft = self.app.create_product(self.seller, 'hidden', {'title': '秘密草稿'})
        market = self.app.products(keyword='python', category='教材书籍', minimum='20.00', maximum='40.00')
        self.assertEqual([item['id'] for item in market['items']], [second['id']])
        market = self.app.products(sort='price_asc')
        self.assertEqual([item['id'] for item in market['items']], [first['id'], second['id']])
        self.assertEqual(self.app.products(self.seller, scope='mine')['total'], 3)
        with self.assertRaises(TradeError):
            self.app.product_detail(draft['id'])
        with self.assertRaises(TradeError):
            self.app.products(self.other, scope='admin')
        with self.assertRaises(TradeError):
            self.app.products(minimum='40', maximum='20')

    def test_uml_product_lifecycle_and_review(self):
        data = {'title': '文具', 'description': '钢笔', 'category': '学习用品',
                'condition': '正常使用', 'price': '8.00'}
        p = self.app.create_product(self.seller, 'life-create', data)
        self.assertEqual(p['status'], 'draft')
        with self.assertRaises(TradeError):
            self.app.product_transition(self.other, 'not-owner', p['id'], p['version'], 'submit')
        p = self.app.product_transition(self.seller, 'life-submit', p['id'], p['version'], 'submit')
        old_version = p['version']
        p = self.app.product_transition(self.seller, 'life-retract', p['id'], p['version'], 'retract')
        with self.assertRaises(TradeError):
            self.app.review_product(self.admin, 'stale-review', p['id'], old_version, 'approve')
        p = self.app.product_transition(self.seller, 'life-submit2', p['id'], p['version'], 'submit')
        p = self.app.review_product(self.admin, 'reject', p['id'], p['version'], 'reject', '说明不足')
        self.assertEqual(p['status'], 'rejected')
        self.assertEqual(self.app.reviews(self.seller, p['id'])[0]['reason'], '说明不足')
        p = self.app.edit_product(self.seller, 'edit', p['id'], p['version'], data)
        self.assertEqual(p['status'], 'draft')
        p = self.app.product_transition(self.seller, 'life-submit3', p['id'], p['version'], 'submit')
        p = self.app.review_product(self.admin, 'approve', p['id'], p['version'], 'approve')
        p = self.app.product_transition(self.seller, 'withdraw', p['id'], p['version'], 'withdraw')
        self.assertEqual(p['status'], 'withdrawn')
        self.assertEqual(self.app.products(scope='market')['total'], 0)
        self.assertEqual(self.app.db.execute('SELECT COUNT(*) FROM submissions WHERE product_id=?', (p['id'],)).fetchone()[0], 3)

    def test_uml_confirm_role_version_and_atomic_audit(self):
        p = self.published()
        r = self.app.reserve(self.buyer, 'atomic-reserve', p['id'], p['version'])
        with self.assertRaises(TradeError):
            self.app.reservation_transition(self.other, 'unauthorized', r['id'], r['version'], 'confirm')
        with self.assertRaises(TradeError):
            self.app.reservation_transition(self.seller, 'old-confirm', r['id'], r['version'] + 1, 'confirm')
        self.app.db.execute("CREATE TRIGGER reject_confirm BEFORE INSERT ON audit_events "
                            "WHEN NEW.operation='reservation_confirm' AND NEW.result='success' "
                            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(Exception):
            self.app.reservation_transition(self.seller, 'injected', r['id'], r['version'], 'confirm')
        self.assertEqual(self.app.one('reservations', r['id'])['status'], 'pending')
        self.assertEqual(self.app.db.execute("SELECT COUNT(*) FROM idempotency WHERE request_id='injected'").fetchone()[0], 0)
        self.app.db.execute('DROP TRIGGER reject_confirm')
        r = self.app.reservation_transition(self.seller, 'confirm-ok', r['id'], r['version'], 'confirm')
        event = self.app.db.execute("SELECT * FROM audit_events WHERE request_id='confirm-ok'").fetchone()
        self.assertEqual((r['status'], event['before_state'], event['after_state']),
                         ('confirmed', 'pending', 'confirmed'))
        self.assertEqual(self.app.reservation_transition(self.seller, 'confirm-ok', r['id'], 1, 'confirm')['id'], r['id'])

    def test_uml_report_privacy_rejection_and_statistics(self):
        p = self.published()
        report = self.app.submit_report(self.buyer, 'report-create', p['id'], '其他', '需要核查')
        self.assertEqual(self.app.reports(self.buyer)[0]['id'], report['id'])
        self.assertEqual(self.app.reports(self.other), [])
        with self.assertRaises(TradeError):
            self.app.resolve_report(self.other, 'not-admin', report['id'], report['version'], p['version'], 'reject', '无违规')
        result = self.app.resolve_report(self.admin, 'report-reject', report['id'], report['version'], p['version'], 'reject', '无违规')
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(self.app.product_detail(p['id'])['status'], 'published')
        self.assertEqual(self.app.stats(self.admin)['states']['published'], 1)
        self.assertGreater(self.app.logs(self.admin, {'operation': 'report_resolve'})['total'], 0)

    def test_uml_backup_and_persistent_relations(self):
        p = self.published()
        r = self.app.reserve(self.buyer, 'persist', p['id'], p['version'])
        backup = Path(self.temp.name) / 'backup.sqlite3'
        self.app.backup(backup)
        restored = Marketplace(backup)
        try:
            reservation = restored.one('reservations', r['id'])
            product = restored.one('products', p['id'])
            self.assertEqual((reservation['product_id'], reservation['seller_id']), (p['id'], product['seller_id']))
            self.assertEqual(json.loads(reservation['snapshot'])['title'], '教材')
            self.assertEqual(restored.db.execute('PRAGMA foreign_key_check').fetchall(), [])
        finally:
            restored.close()


if __name__ == '__main__':
    unittest.main()
