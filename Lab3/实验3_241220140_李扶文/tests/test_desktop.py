"""Smoke tests for the desktop navigation against a temporary database."""

import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from market import MarketView
from product_editor import ProductEditor
from reservation_board import ReservationBoard, reservation_column
from admin_dashboard import AdminDashboard
from trade import Marketplace


class DesktopNavigationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Marketplace(Path(self.temp.name) / 'test.sqlite3')
        self.service.initialize_admin('admin01', 'AdminPass123', '管理员', '13800000000')
        self.service.register('user001', 'Password123', '普通用户', '13800000001')
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()
        self.service.close()
        self.temp.cleanup()

    def open_view(self, name, password):
        account = self.service.login(name, password)
        market = MarketView(self.root, self.service, account['token'], account, lambda: None)
        market.pack()
        self.root.update()
        return market

    def test_user_navigation_opens_connected_workspaces(self):
        view = self.open_view('user001', 'Password123')
        for method in (view.workspace.my_products, view.workspace.reservations,
                       view.workspace.messages, view.workspace.profile, view.workspace.statistics):
            before = set(view.winfo_children())
            method()
            self.root.update()
            opened = set(view.winfo_children()) - before
            self.assertEqual(len(opened), 1, method.__name__)
            for window in opened:
                window.destroy()

    def test_admin_navigation_opens_connected_workspaces(self):
        view = self.open_view('admin01', 'AdminPass123')
        for method in (view.workspace.admin, view.workspace.review_queue,
                       view.workspace.admin_reports, view.workspace.admin_logs, view.workspace.statistics):
            before = set(view.winfo_children())
            method()
            self.root.update()
            opened = set(view.winfo_children()) - before
            self.assertEqual(len(opened), 1, method.__name__)
            for window in opened:
                window.destroy()

    def test_product_editor_saves_draft_and_submits(self):
        account = self.service.login('user001', 'Password123')
        editor = ProductEditor(self.root, self.service, account['token'], None, lambda: None)
        editor.fields['title'].insert(0, '教材')
        editor.fields['category'].set('教材书籍')
        editor.fields['condition'].set('正常使用')
        editor.fields['price'].insert(0, '28.00')
        editor.fields['description'].insert('1.0', '线下交易')
        editor.save(True)
        items = self.service.products(account['token'], scope='mine')['items']
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]['title'], items[0]['price_cents'], items[0]['status']), ('教材', 2800, 'pending'))

    def test_product_editor_invalid_submission_does_not_create_draft(self):
        account = self.service.login('user001', 'Password123')
        editor = ProductEditor(self.root, self.service, account['token'], None, lambda: None)
        editor.fields['title'].insert(0, '教材')
        editor.save(True)
        self.assertEqual(self.service.products(account['token'], scope='mine')['total'], 0)
        self.assertTrue(editor.status.cget('text'))
        editor.win.destroy()

    def test_reservation_board_groups_and_confirms(self):
        self.service.register('buyer001', 'Password123', '买家', '13800000002')
        seller = self.service.login('user001', 'Password123')
        buyer = self.service.login('buyer001', 'Password123')
        admin = self.service.login('admin01', 'AdminPass123')
        product = self.service.create_product(seller['token'], 'create', {
            'title': '教材', 'description': '教学用', 'category': '教材书籍',
            'condition': '正常使用', 'price': '28.00'})
        product = self.service.product_transition(seller['token'], 'submit', product['id'], product['version'], 'submit')
        product = self.service.review_product(admin['token'], 'review', product['id'], product['version'], 'approve')
        reservation = self.service.reserve(buyer['token'], 'reserve', product['id'], product['version'])
        self.assertEqual(reservation_column(reservation, seller['id']), 0)
        self.assertEqual(reservation_column(reservation, buyer['id']), 1)
        board = ReservationBoard(self.root, self.service, seller['token'], seller, lambda: None, lambda *_: None)
        self.root.update()
        board.transition(reservation, 'confirm')
        result = self.service.reservations(seller['token'])[0]
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(reservation_column(result, buyer['id']), 2)
        self.assertEqual(self.service.contact(buyer['token'], result['id'])['phone'], '13800000001')
        board.win.destroy()

    def test_admin_dashboard_shows_and_reviews_pending_product(self):
        user = self.service.login('user001', 'Password123')
        admin = self.service.login('admin01', 'AdminPass123')
        product = self.service.create_product(user['token'], 'product-1', {
            'title': '测试教材', 'description': '无联系方式', 'category': '教材书籍',
            'condition': '近新', 'price': '20.00'})
        product = self.service.product_transition(user['token'], 'submit-1', product['id'], product['version'], 'submit')
        view = MarketView(self.root, self.service, admin['token'], admin, lambda: None)
        dashboard = AdminDashboard(self.root, self.service, admin['token'], view.workspace)
        self.root.update()
        self.assertEqual(dashboard.name.cget('text'), '测试教材')
        self.assertEqual(dashboard.counts[0].cget('text'), '1')
        dashboard.review('approve')
        self.assertEqual(self.service.product_detail(product['id'])['status'], 'published')
        self.assertEqual(dashboard.counts[0].cget('text'), '0')
        dashboard.win.destroy()


if __name__ == '__main__':
    unittest.main()
