"""Four-column reservation workspace driven by actual reservation records."""

import uuid
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from trade import TradeError

FONT = 'Microsoft YaHei'
BG = '#f7f8fc'
INK = '#182440'
MUTED = '#718094'
PURPLE = '#5040d8'
HEADER = '#2e287a'
COLORS = ('#ffe0d1', '#dbe9ff', '#d9f2e4', '#ebe5fb')


def reservation_column(item, user_id):
    """Map each transaction to the participant's appropriate workspace column."""
    if item['status'] in ('cancelled', 'completed'):
        return 3
    if item['status'] == 'confirmed':
        return 2
    if item['status'] == 'pending':
        return 0 if item['seller_id'] == user_id else 1
    return 3


class ReservationBoard:
    def __init__(self, parent, service, token, account, refresh_market, report_form):
        self.service = service
        self.token = token
        self.account = account
        self.refresh_market = refresh_market
        self.report_form = report_form
        self.win = tk.Toplevel(parent)
        self.win.title('预约工作台')
        self.win.geometry('1200x720')
        self.win.minsize(900, 600)
        self.win.configure(bg=BG)
        self.columns = []
        self.build()
        self.refresh()

    def build(self):
        bar = tk.Frame(self.win, bg=HEADER, height=74)
        bar.pack(fill='x')
        bar.pack_propagate(False)
        tk.Label(bar, text='预约工作台', bg=HEADER, fg='white', font=(FONT, 21, 'bold')).pack(side='left', padx=40)
        tk.Button(bar, text='刷新', command=self.refresh, bg=HEADER, fg='white',
                  activebackground=HEADER, activeforeground='white', relief='flat',
                  font=(FONT, 11), cursor='hand2').pack(side='right', padx=40)
        body = tk.Frame(self.win, bg=BG, padx=40, pady=24)
        body.pack(fill='both', expand=True)
        tk.Label(body, text='交易进度', bg=BG, fg=INK, font=(FONT, 22, 'bold'), anchor='w').pack(fill='x')
        tk.Label(body, text='联系方式仅在“卖家已确认”阶段向双方开放', bg=BG, fg=MUTED,
                 font=(FONT, 11), anchor='w').pack(fill='x', pady=(1, 20))
        container = tk.Frame(body, bg=BG)
        container.pack(fill='both', expand=True)
        for index, title in enumerate(('待我确认', '待对方确认', '线下交付中', '历史记录')):
            container.columnconfigure(index, weight=1, uniform='boards')
            panel = tk.Frame(container, bg='white', padx=14, pady=14)
            panel.grid(row=0, column=index, sticky='nsew', padx=(0, 16) if index < 3 else 0)
            tk.Label(panel, text=title, bg='white', fg=INK, font=(FONT, 14, 'bold'),
                     anchor='w').pack(fill='x', pady=(0, 10))
            canvas = tk.Canvas(panel, bg='white', highlightthickness=0, width=175)
            scrollbar = ttk.Scrollbar(panel, orient='vertical', command=canvas.yview)
            inner = tk.Frame(canvas, bg='white')
            inner.bind('<Configure>', lambda event, c=canvas: c.configure(scrollregion=c.bbox('all')))
            canvas.create_window((0, 0), window=inner, anchor='nw', tags='content')
            canvas.bind('<Configure>', lambda event, c=canvas: c.itemconfigure('content', width=event.width))
            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side='right', fill='y')
            canvas.pack(side='left', fill='both', expand=True)
            self.columns.append(inner)
        container.rowconfigure(0, weight=1)
        tk.Label(body, text='取消预约需要二次确认与原因；系统不逆转已完成的线下钱物交付。',
                 bg=BG, fg=MUTED, font=(FONT, 10), anchor='w').pack(fill='x', pady=(18, 0))

    def refresh(self):
        try:
            items = self.service.reservations(self.token)
        except TradeError as exc:
            messagebox.showerror('无法获取预约', str(exc), parent=self.win)
            return
        for column in self.columns:
            for child in column.winfo_children():
                child.destroy()
        groups = [[], [], [], []]
        for item in items:
            groups[reservation_column(item, self.account['id'])].append(item)
        for index, group in enumerate(groups):
            if not group:
                tk.Label(self.columns[index], text='暂无记录', bg='white', fg=MUTED,
                         font=(FONT, 10)).pack(anchor='w', pady=8)
            for item in group:
                self.card(self.columns[index], item, index)

    def card(self, parent, item, index):
        card = tk.Frame(parent, bg=COLORS[index], padx=12, pady=11)
        card.pack(fill='x', pady=(0, 12))
        tk.Label(card, text=item['snapshot']['title'], bg=COLORS[index], fg=INK,
                 font=(FONT, 12, 'bold'), anchor='w', wraplength=185, justify='left').pack(fill='x')
        if index == 0:
            status = '买家已申请'
        elif index == 1:
            status = '等待卖家确认'
        elif index == 2:
            status = '双方已确认'
        else:
            status = '已完成' if item['status'] == 'completed' else '已取消'
        tk.Label(card, text=status, bg=COLORS[index], fg=MUTED,
                 font=(FONT, 10), anchor='w').pack(fill='x', pady=(6, 8))
        buttons = tk.Frame(card, bg=COLORS[index])
        buttons.pack(fill='x')
        if index == 0:
            self.button(buttons, '确认', lambda: self.transition(item, 'confirm'))
        elif index == 2 and item['buyer_id'] == self.account['id']:
            self.button(buttons, '完成', lambda: self.transition(item, 'complete'))
        else:
            self.button(buttons, '详情', lambda: self.detail(item))
        if index in (0, 1, 2):
            self.button(buttons, '取消', lambda: self.cancel(item))
        if index == 2:
            self.button(buttons, '电话', lambda: self.contact(item))

    @staticmethod
    def button(parent, label, command):
        tk.Button(parent, text=label, command=command, bg=PURPLE, fg='white', relief='flat',
                  activebackground='#4030c5', activeforeground='white', padx=7,
                  font=(FONT, 9), cursor='hand2').pack(side='left', padx=(0, 5))

    def transition(self, item, operation, reason='', confirmed=False):
        try:
            self.service.reservation_transition(self.token, str(uuid.uuid4()), item['id'],
                                                item['version'], operation, reason, confirmed)
        except TradeError as exc:
            messagebox.showerror('操作失败', str(exc), parent=self.win)
            self.refresh()
            return
        self.refresh()
        self.refresh_market()

    def cancel(self, item):
        reason = simpledialog.askstring('取消原因', '请输入取消原因（1–500 字）：', parent=self.win)
        if reason is None:
            return
        if not messagebox.askyesno('确认取消', '确定取消预约吗？系统无法逆转线下交付。', parent=self.win):
            return
        self.transition(item, 'cancel', reason, True)

    def contact(self, item):
        try:
            result = self.service.contact(self.token, item['id'])
            messagebox.showinfo('交易对方联系方式', result['phone'] + '\n' + result['notice'], parent=self.win)
        except TradeError as exc:
            messagebox.showerror('无法查看', str(exc), parent=self.win)
            self.refresh()

    def detail(self, item):
        popup = tk.Toplevel(self.win)
        popup.title('预约详情')
        popup.geometry('480x390')
        popup.configure(bg='white')
        body = tk.Frame(popup, bg='white', padx=25, pady=20)
        body.pack(fill='both', expand=True)
        snap = item['snapshot']
        info = (f"商品：{snap['title']}\n分类：{snap['category']}\n"
                f"预约时标价：¥ {Decimal(snap['price_cents']) / 100:.2f}\n"
                f"预约状态：{ {'pending': '待卖家确认', 'confirmed': '已确认', 'cancelled': '已取消', 'completed': '已完成'}.get(item['status'], item['status']) }")
        tk.Label(body, text=info, bg='white', fg=INK, font=(FONT, 11), justify='left',
                 anchor='w').pack(fill='x')
        if item['status'] == 'cancelled':
            tk.Label(body, text='取消原因：' + (item['cancel_reason'] or ''), bg='white', fg=MUTED,
                     wraplength=400, justify='left', anchor='w').pack(fill='x', pady=8)
        if item['buyer_id'] == self.account['id']:
            tk.Button(body, text='举报此商品', command=lambda: self.report_form(item['product_id'], popup),
                      bg=PURPLE, fg='white', relief='flat', padx=12, pady=5).pack(anchor='w', pady=15)
