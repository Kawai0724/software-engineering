"""Administrator dashboard using the governance-center prototype layout."""

import datetime as dt
import io
import uuid
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk
from trade import TradeError

FONT = 'Microsoft YaHei'
BG = '#f6f8fb'
SIDE = '#101827'
INK = '#182440'
MUTED = '#768195'
BLUE = '#dbe9ff'
PEACH = '#ffe0d1'
MINT = '#dcf2e5'
GREEN = '#16813e'
RED = '#dc2626'


class AdminDashboard:
    def __init__(self, parent, service, token, workspace):
        self.service = service
        self.token = token
        self.workspace = workspace
        self.items = []
        self.index = 0
        self.win = tk.Toplevel(parent)
        self.win.title('管理员治理中心')
        self.win.geometry('1200x720')
        self.win.minsize(900, 600)
        self.win.configure(bg=BG)
        self.build()
        self.refresh()

    def build(self):
        sidebar = tk.Frame(self.win, bg=SIDE, width=210)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text='治理中心', bg=SIDE, fg='white', font=(FONT, 20, 'bold')).pack(
            anchor='w', padx=28, pady=(42, 30))
        for title, command in [('审核队列', self.refresh), ('举报案件', self.workspace.admin_reports),
                               ('审计日志', self.workspace.admin_logs), ('统计报表', self.workspace.statistics),
                               ('生成邀请码', lambda: self.workspace.invitation(self.win))]:
            tk.Button(sidebar, text=title, command=command, bg=SIDE, fg='#dbe2f0' if title == '审核队列' else '#98a2b4',
                      anchor='w', activebackground=SIDE, activeforeground='white', relief='flat',
                      font=(FONT, 12), cursor='hand2').pack(fill='x', padx=25, pady=8)
        content = tk.Frame(self.win, bg=BG, padx=45, pady=28)
        content.pack(side='left', fill='both', expand=True)
        self.heading = tk.Label(content, bg=BG, fg=INK, font=(FONT, 22, 'bold'), anchor='w')
        self.heading.pack(fill='x', pady=(0, 20))
        summary = tk.Frame(content, bg=BG)
        summary.pack(fill='x', pady=(0, 30))
        self.counts = []
        for index, (title, color) in enumerate((('待审核', BLUE), ('待处理举报', PEACH), ('今日完成', MINT))):
            summary.columnconfigure(index, weight=1, uniform='summary')
            tile = tk.Frame(summary, bg=color, height=105)
            tile.grid(row=0, column=index, sticky='ew', padx=(0, 20) if index < 2 else 0)
            tile.grid_propagate(False)
            value = tk.Label(tile, text='0', bg=color, fg=INK, font=(FONT, 21))
            value.pack(side='left', padx=(24, 12))
            tk.Label(tile, text=title, bg=color, fg=MUTED, font=(FONT, 11)).pack(side='left')
            self.counts.append(value)
        self.card = tk.Frame(content, bg='white', padx=28, pady=25)
        self.card.pack(fill='both', expand=True)
        self.name = tk.Label(self.card, bg='white', fg=INK, font=(FONT, 17, 'bold'), anchor='w', wraplength=800)
        self.name.pack(fill='x')
        self.metadata = tk.Label(self.card, bg='white', fg=MUTED, font=(FONT, 10), anchor='w', wraplength=800)
        self.metadata.pack(fill='x', pady=(8, 10))
        self.description = tk.Label(self.card, bg='white', fg=INK, font=(FONT, 11), anchor='nw',
                                    justify='left', wraplength=800)
        self.description.pack(fill='both', expand=True)
        controls = tk.Frame(self.card, bg='white')
        controls.pack(fill='x', pady=(10, 0))
        self.reason = tk.Entry(controls, relief='flat', bg='#fff4e9', fg=INK, font=(FONT, 11))
        self.reason.pack(side='left', fill='x', expand=True, ipady=10)
        self.reject_btn = tk.Button(controls, text='驳回', command=lambda: self.review('reject'), bg=RED, fg='white',
                                    relief='flat', padx=14, pady=7, cursor='hand2')
        self.reject_btn.pack(side='right', padx=(12, 0))
        self.approve_btn = tk.Button(controls, text='通过', command=lambda: self.review('approve'), bg=GREEN, fg='white',
                                     relief='flat', padx=14, pady=7, cursor='hand2')
        self.approve_btn.pack(side='right', padx=(12, 0))
        navigation = tk.Frame(content, bg=BG)
        navigation.pack(fill='x', pady=(12, 0))
        self.position = tk.Label(navigation, text='', bg=BG, fg=MUTED, font=(FONT, 10))
        self.position.pack(side='left')
        tk.Button(navigation, text='查看图片', command=self.show_images, relief='flat', padx=10).pack(side='right', padx=6)
        tk.Button(navigation, text='下一条', command=lambda: self.move(1), relief='flat', padx=10).pack(side='right')
        tk.Button(navigation, text='上一条', command=lambda: self.move(-1), relief='flat', padx=10).pack(side='right', padx=6)
        tk.Label(content, text='管理员可审核、监管和查询，不可代替用户预约、确认或完成交易。',
                 bg=BG, fg=MUTED, font=(FONT, 10), anchor='w').pack(fill='x', pady=(15, 0))

    def refresh(self):
        try:
            items = []
            page = 1
            while True:
                result = self.service.products(self.token, scope='admin', states=['pending'], page=page)
                items.extend(result['items'])
                if page * 20 >= result['total']:
                    break
                page += 1
            reports = self.service.reports(self.token)
            today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
            stats = self.service.stats(self.token, today, today)
            self.items = items
            self.index = min(self.index, max(0, len(items) - 1))
            self.heading.config(text=f'审核队列  /  待处理 {len(items)}')
            values = (len(items), sum(item['status'] == 'pending' for item in reports), stats['transactions']['count'])
            for label, value in zip(self.counts, values):
                label.config(text=str(value))
            self.show_item()
        except TradeError as exc:
            messagebox.showerror('加载失败', str(exc), parent=self.win)

    def show_item(self):
        self.reason.delete(0, 'end')
        if not self.items:
            self.name.config(text='暂无待审核商品')
            self.metadata.config(text='新商品提交后会显示在这里。')
            self.description.config(text='')
            self.position.config(text='暂无待处理记录')
            self.approve_btn.config(state='disabled')
            self.reject_btn.config(state='disabled')
            return
        item = self.items[self.index]
        try:
            item = self.service.product_detail(item['id'], self.token)
        except TradeError as exc:
            messagebox.showerror('加载失败', str(exc), parent=self.win)
            return
        self.name.config(text=item['title'])
        self.metadata.config(text=f"提交版本 v{item['version']}   ·   图片 {len(item['images'])} 张   ·   检查标题和描述中的联系方式")
        self.description.config(text=item['description'])
        self.position.config(text=f'第 {self.index + 1} / {len(self.items)} 条   ·   驳回时须填写 1–500 字原因')
        self.approve_btn.config(state='normal')
        self.reject_btn.config(state='normal')

    def move(self, delta):
        if 0 <= self.index + delta < len(self.items):
            self.index += delta
            self.show_item()

    def show_images(self):
        if not self.items:
            return
        try:
            item = self.service.product_detail(self.items[self.index]['id'], self.token)
            if not item['images']:
                messagebox.showinfo('商品图片', '该商品没有图片。', parent=self.win)
                return
            popup = tk.Toplevel(self.win)
            popup.title('审核商品图片')
            popup.geometry('850x600')
            canvas = tk.Canvas(popup, bg='white')
            scrollbar = ttk.Scrollbar(popup, orient='vertical', command=canvas.yview)
            content = tk.Frame(canvas, bg='white')
            content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
            canvas.create_window((0, 0), window=content, anchor='nw')
            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side='right', fill='y')
            canvas.pack(fill='both', expand=True)
            for index, image in enumerate(item['images']):
                row = self.service.db.execute('SELECT data FROM images WHERE id=?', (image['id'],)).fetchone()
                if row:
                    with Image.open(io.BytesIO(row['data'])) as picture:
                        picture.thumbnail((360, 250))
                        photo = ImageTk.PhotoImage(picture.copy())
                    label = tk.Label(content, image=photo, bg='white', padx=10, pady=10)
                    label.image = photo
                    label.grid(row=index // 2, column=index % 2)
        except (TradeError, OSError, ValueError) as exc:
            messagebox.showerror('无法查看图片', str(exc), parent=self.win)

    def review(self, decision):
        if not self.items:
            return
        item = self.items[self.index]
        reason = self.reason.get().strip()
        if decision == 'reject' and not 1 <= len(reason) <= 500:
            messagebox.showerror('请填写驳回原因', '驳回原因须为 1–500 字。', parent=self.win)
            return
        try:
            self.service.review_product(self.token, str(uuid.uuid4()), item['id'], item['version'], decision, reason)
            self.refresh()
            self.workspace.refresh_market()
        except TradeError as exc:
            messagebox.showerror('审核失败', str(exc), parent=self.win)
            self.refresh()
