"""Desktop workspaces connected to the marketplace business service."""

import json
import uuid
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from trade import REPORT_REASONS, TradeError
from product_editor import ProductEditor
from reservation_board import ReservationBoard
from admin_dashboard import AdminDashboard

FONT = 'Microsoft YaHei'
INK = '#192741'
BG = '#f7f8fc'
GREEN = '#0d7771'
STATES = {'draft': '草稿', 'pending': '待处理', 'rejected': '已驳回',
          'published': '已发布', 'reserved': '已预约', 'withdrawn': '已下架',
          'sold': '已售出', 'banned': '违规下架', 'confirmed': '已确认',
          'cancelled': '已取消', 'completed': '已完成', 'handled': '已处理'}


def request_id():
    return str(uuid.uuid4())


class Workspace:
    def __init__(self, parent, service, token, account, refresh_market):
        self.parent, self.service, self.token = parent, service, token
        self.account, self.refresh_market = account, refresh_market

    def window(self, title, size='950x650'):
        win = tk.Toplevel(self.parent)
        win.title(title)
        win.geometry(size)
        win.minsize(650, 450)
        win.configure(bg=BG)
        return win

    def heading(self, parent, title, subtitle=''):
        tk.Label(parent, text=title, bg=BG, fg=INK, font=(FONT, 19, 'bold'),
                 anchor='w').pack(fill='x', padx=25, pady=(20, 0))
        if subtitle:
            tk.Label(parent, text=subtitle, bg=BG, fg='#778294', font=(FONT, 10),
                     anchor='w').pack(fill='x', padx=25, pady=(4, 12))

    def action(self, fn):
        try:
            return fn()
        except TradeError as exc:
            messagebox.showerror('操作失败', str(exc), parent=self.parent)
        except (OSError, ValueError) as exc:
            messagebox.showerror('操作失败', str(exc), parent=self.parent)
        return None

    def table(self, parent, columns):
        frame = ttk.Frame(parent, padding=20)
        frame.pack(fill='both', expand=True)
        tree = ttk.Treeview(frame, columns=[x[0] for x in columns], show='headings', selectmode='browse')
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=60)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        tree.pack(side='left', fill='both', expand=True)
        return tree

    def selected(self, tree, rows):
        selection = tree.selection()
        if not selection:
            messagebox.showinfo('请选择', '请先选择一条记录。', parent=tree)
            return None
        return rows.get(selection[0])

    def buttons(self, parent, pairs):
        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill='x', padx=20, pady=(0, 18))
        for label, callback in pairs:
            tk.Button(frame, text=label, command=callback, bg=GREEN, fg='white', relief='flat',
                      padx=13, pady=6, font=(FONT, 10), cursor='hand2').pack(side='left', padx=(0, 8))

    def my_products(self):
        if self.account['role'] != 'user':
            messagebox.showinfo('角色限制', '管理员不参与商品买卖。', parent=self.parent)
            return
        win = self.window('我的发布')
        self.heading(win, '我的发布', '管理自己的草稿、审核和上架商品')
        tree = self.table(win, [('title', '商品', 260), ('category', '分类', 130),
                                ('price', '价格（元）', 100), ('status', '状态', 120), ('version', '版本', 70)])
        rows = {}
        def refresh():
            tree.delete(*tree.get_children())
            rows.clear()
            page = 1
            while True:
                result = self.action(lambda: self.service.products(self.token, scope='mine', page=page))
                if result is None:
                    return
                for item in result['items']:
                    price = '' if item['price_cents'] is None else f"{Decimal(item['price_cents']) / 100:.2f}"
                    key = tree.insert('', 'end', values=(item['title'] or '（无标题）', item['category'],
                                                        price, STATES.get(item['status'], item['status']), item['version']))
                    rows[key] = item
                if page * 20 >= result['total']:
                    break
                page += 1
        def edit():
            item = self.selected(tree, rows)
            if item:
                detail = self.action(lambda: self.service.product_detail(item['id'], self.token))
                if detail:
                    self.product_form(win, detail, refresh)
        def transition(name):
            item = self.selected(tree, rows)
            if not item:
                return
            result = self.action(lambda: self.service.product_transition(self.token, request_id(),
                                                                          item['id'], item['version'], name))
            if result:
                refresh()
                self.refresh_market()
        def reviews():
            item = self.selected(tree, rows)
            if not item:
                return
            result = self.action(lambda: self.service.reviews(self.token, item['id']))
            if result is not None:
                text = '\n\n'.join(f"{x['created_at']}  {x['decision']}\n{x['reason']}" for x in result)
                messagebox.showinfo('审核记录', text or '暂无审核记录', parent=win)
        def remove_image():
            item = self.selected(tree, rows)
            if not item:
                return
            detail = self.action(lambda: self.service.product_detail(item['id'], self.token))
            if not detail or not detail['images']:
                messagebox.showinfo('商品图片', '该商品没有图片。', parent=win)
                return
            names = '\n'.join(f"{i + 1}. {image['filename']}" for i, image in enumerate(detail['images']))
            number = simpledialog.askinteger('删除图片', names + '\n输入要删除的图片序号：',
                                             parent=win, minvalue=1, maxvalue=len(detail['images']))
            if number is None:
                return
            result = self.action(lambda: self.service.remove_image(self.token, request_id(), detail['id'],
                                                                    detail['version'], detail['images'][number - 1]['id']))
            if result:
                refresh()
                self.refresh_market()
        self.buttons(win, [('新建商品', lambda: self.product_form(win, None, refresh)), ('编辑', edit),
                           ('提交审核', lambda: transition('submit')), ('撤回审核', lambda: transition('retract')),
                           ('下架', lambda: transition('withdraw')), ('删除图片', remove_image),
                           ('查看审核', reviews), ('刷新', refresh)])
        refresh()

    def product_form(self, parent, product, after):
        def finished():
            after()
            self.refresh_market()
        ProductEditor(parent, self.service, self.token, product, finished)

    def reservations(self):
        if self.account['role'] != 'user':
            messagebox.showinfo('????', '??????????', parent=self.parent)
            return
        ReservationBoard(self.parent, self.service, self.token, self.account,
                         self.refresh_market, self.report_form)

    def report_form(self, product_id, parent):
        win = self.window('举报商品', '560x460')
        self.heading(win, '举报商品', '请选择原因并填写说明，不接受附件')
        frame = tk.Frame(win, bg=BG, padx=30)
        frame.pack(fill='both', expand=True)
        tk.Label(frame, text='举报原因', bg=BG, fg=INK).pack(anchor='w')
        reason = ttk.Combobox(frame, values=REPORT_REASONS, state='readonly')
        reason.current(0)
        reason.pack(fill='x', pady=(5, 15))
        tk.Label(frame, text='说明（1–500 字）', bg=BG, fg=INK).pack(anchor='w')
        text = tk.Text(frame, height=6)
        text.pack(fill='both', expand=True, pady=5)
        def submit():
            result = self.action(lambda: self.service.submit_report(
                self.token, request_id(), product_id, reason.get(), text.get('1.0', 'end').strip()))
            if result:
                messagebox.showinfo('提交成功', '举报已提交，可在消息中心查看结果。', parent=win)
                win.destroy()
        self.buttons(win, [('提交举报', submit)])

    def messages(self):
        if self.account['role'] == 'admin':
            self.admin_reports()
            return
        win = self.window('消息中心')
        self.heading(win, '消息中心', '查看本人提交的举报及处理结果')
        tree = self.table(win, [('reason', '举报原因', 210), ('details', '说明', 260),
                                ('status', '状态', 100), ('note', '处理说明', 260)])
        def refresh():
            items = self.action(lambda: self.service.reports(self.token))
            if items is None:
                return
            tree.delete(*tree.get_children())
            for item in items:
                tree.insert('', 'end', values=(item['reason'], item['details'],
                                               STATES.get(item['status'], item['status']), item['handling_note']))
        self.buttons(win, [('刷新', refresh)])
        refresh()

    def profile(self):
        data = self.action(lambda: self.service.profile(self.token))
        if data is None:
            return
        win = self.window('账户设置', '560x420')
        self.heading(win, '账户设置', '用户名和角色不可修改，联系电话仅按预约状态向交易对方开放')
        frame = tk.Frame(win, bg=BG, padx=30)
        frame.pack(fill='both', expand=True)
        tk.Label(frame, text='用户名：' + data['username'], bg=BG, fg=INK).pack(anchor='w', pady=8)
        tk.Label(frame, text='昵称', bg=BG, fg=INK).pack(anchor='w')
        nick = ttk.Entry(frame)
        nick.insert(0, data['nickname'])
        nick.pack(fill='x', pady=(4, 12))
        tk.Label(frame, text='联系电话', bg=BG, fg=INK).pack(anchor='w')
        phone = ttk.Entry(frame)
        phone.insert(0, data['phone'])
        phone.pack(fill='x', pady=(4, 12))
        def save():
            result = self.action(lambda: self.service.update_profile(self.token, request_id(), nick.get(), phone.get()))
            if result:
                messagebox.showinfo('保存成功', '资料已更新。', parent=win)
                win.destroy()
        if self.account['role'] == 'user':
            self.buttons(win, [('保存', save), ('我的交易统计', self.statistics)])
        else:
            tk.Label(frame, text='管理员账号资料仅可查看', bg=BG, fg='#778294').pack(anchor='w')

    def admin(self):
        if self.account['role'] != 'admin':
            messagebox.showerror('????', '????????????', parent=self.parent)
            return
        AdminDashboard(self.parent, self.service, self.token, self)

    def invitation(self, parent):
        result = self.action(lambda: self.service.create_invitation(self.token, request_id()))
        if result and 'code' in result:
            messagebox.showinfo('一次性管理员邀请码', result['code'] + '\n仅显示一次，请妥善保存。', parent=parent)

    def review_queue(self):
        win = self.window('商品审核队列')
        self.heading(win, '审核队列', '审核当前提交版本；驳回时必须填写原因')
        tree = self.table(win, [('title', '商品', 260), ('description', '描述', 300),
                                ('price', '价格', 100), ('version', '版本', 70)])
        rows = {}
        def refresh():
            tree.delete(*tree.get_children())
            rows.clear()
            page = 1
            while True:
                result = self.action(lambda: self.service.products(self.token, scope='admin', states=['pending'], page=page))
                if result is None:
                    return
                for item in result['items']:
                    key = tree.insert('', 'end', values=(item['title'], item['description'],
                                                         f"{Decimal(item['price_cents']) / 100:.2f}", item['version']))
                    rows[key] = item
                if page * 20 >= result['total']:
                    break
                page += 1
        def review(decision):
            item = self.selected(tree, rows)
            if not item:
                return
            reason = ''
            if decision == 'reject':
                reason = simpledialog.askstring('驳回原因', '请输入驳回原因（1–500 字）：', parent=win)
                if reason is None:
                    return
            result = self.action(lambda: self.service.review_product(self.token, request_id(), item['id'],
                                                                      item['version'], decision, reason))
            if result:
                refresh()
                self.refresh_market()
        self.buttons(win, [('通过', lambda: review('approve')), ('驳回', lambda: review('reject')), ('刷新', refresh)])
        refresh()

    def admin_reports(self):
        if self.account['role'] != 'admin':
            return
        win = self.window('举报案件')
        self.heading(win, '举报案件', '确认违规时将撤回相关商品并取消其有效预约')
        tree = self.table(win, [('reason', '举报原因', 180), ('details', '说明', 250),
                                ('status', '状态', 100), ('note', '处置说明', 250)])
        rows = {}
        def refresh():
            items = self.action(lambda: self.service.reports(self.token))
            if items is None:
                return
            tree.delete(*tree.get_children())
            rows.clear()
            for item in items:
                key = tree.insert('', 'end', values=(item['reason'], item['details'],
                                                     STATES.get(item['status'], item['status']), item['handling_note']))
                rows[key] = item
        def resolve(decision):
            item = self.selected(tree, rows)
            if not item:
                return
            product = self.action(lambda: self.service.product_detail(item['product_id'], self.token))
            if product is None:
                return
            note = simpledialog.askstring('处置说明', '请输入处置说明（1–500 字）：', parent=win)
            if note is None:
                return
            result = self.action(lambda: self.service.resolve_report(self.token, request_id(), item['id'],
                                                                      item['version'], product['version'], decision, note))
            if result:
                refresh()
                self.refresh_market()
        self.buttons(win, [('驳回举报', lambda: resolve('reject')), ('确认违规', lambda: resolve('violation')),
                           ('刷新', refresh)])
        refresh()

    def admin_logs(self):
        win = self.window('审计日志')
        self.heading(win, '审计日志', '仅管理员可查看；日志不展示密码、令牌或电话')
        tree = self.table(win, [('time', '时间', 200), ('operation', '操作', 180),
                                ('resource', '资源', 250), ('result', '结果', 100)])
        page = [1]
        def refresh():
            result = self.action(lambda: self.service.logs(self.token, page=page[0]))
            if result is None:
                return
            tree.delete(*tree.get_children())
            for item in result['items']:
                tree.insert('', 'end', values=(item['occurred_at'], item['operation'],
                                               item['resource_id'] or '', item['result']))
            win.title(f"审计日志 - 第 {page[0]} 页，共 {result['total']} 条")
        def turn(delta):
            target = page[0] + delta
            if target < 1:
                return
            result = self.action(lambda: self.service.logs(self.token, page=target))
            if result is not None and (target - 1) * 20 < result['total']:
                page[0] = target
                refresh()
        self.buttons(win, [('上一页', lambda: turn(-1)), ('下一页', lambda: turn(1)), ('刷新', refresh)])
        refresh()

    def statistics(self):
        win = self.window('统计报表', '750x550')
        self.heading(win, '统计报表', '完成交易标价合计不是支付流水或实际收款证明')
        frame = tk.Frame(win, bg=BG, padx=25)
        frame.pack(fill='both', expand=True)
        tk.Label(frame, text='开始日期（YYYY-MM-DD，可留空）', bg=BG).pack(anchor='w')
        start = ttk.Entry(frame)
        start.pack(fill='x', pady=5)
        tk.Label(frame, text='结束日期（YYYY-MM-DD，可留空）', bg=BG).pack(anchor='w')
        end = ttk.Entry(frame)
        end.pack(fill='x', pady=5)
        output = tk.Text(frame, height=12, wrap='word')
        output.pack(fill='both', expand=True, pady=10)
        def refresh():
            result = self.action(lambda: self.service.stats(self.token, start.get() or None, end.get() or None))
            if result is not None:
                output.delete('1.0', 'end')
                output.insert('end', json.dumps(result, ensure_ascii=False, indent=2))
        self.buttons(win, [('查询统计', refresh)])
        refresh()
