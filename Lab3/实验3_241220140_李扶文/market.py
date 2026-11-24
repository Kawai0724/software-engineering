"""Product market view backed by the marketplace service."""

import io
import tkinter as tk
import uuid
from decimal import Decimal
from tkinter import messagebox, ttk

from trade import CATEGORIES, TradeError
from workspace import Workspace
from PIL import Image, ImageTk

FONT = 'Microsoft YaHei'
BG = '#f7f8fc'
INK = '#192741'
GREEN = '#0d7771'
SIDEBAR = '#0a3938'


class MarketView(tk.Frame):
    def __init__(self, parent, service, token, account, on_logout):
        super().__init__(parent, bg=BG)
        self.service, self.token, self.account, self.on_logout = service, token, account, on_logout
        self.workspace = Workspace(self, service, token, account, self.refresh)
        self.page = 1
        self.total = 0
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.sidebar = tk.Frame(self, bg=SIDEBAR, width=210)
        self.sidebar.grid(row=0, column=0, sticky='ns')
        self.sidebar.grid_propagate(False)
        tk.Label(self.sidebar, text='回收站', bg=SIDEBAR, fg='white',
                 font=(FONT, 20, 'bold')).pack(anchor='w', padx=32, pady=(48, 35))
        for name, handler in [('探索商品', self.search), ('我的发布', self.workspace.my_products),
                              ('预约箱', self.workspace.reservations), ('消息中心', self.workspace.messages),
                              ('账户设置', self.workspace.profile)]:
            tk.Button(self.sidebar, text=name, command=handler, anchor='w', bg=SIDEBAR,
                      fg='white' if name == '探索商品' else '#9bbdbb', activebackground=SIDEBAR,
                      activeforeground='white', relief='flat', font=(FONT, 13), cursor='hand2').pack(
                          fill='x', padx=30, pady=9)
        if account['role'] == 'admin':
            tk.Button(self.sidebar, text='治理中心', command=self.workspace.admin, anchor='w', bg=SIDEBAR,
                      fg='#9bbdbb', activebackground=SIDEBAR, activeforeground='white', relief='flat',
                      font=(FONT, 13), cursor='hand2').pack(fill='x', padx=30, pady=9)
        tk.Button(self.sidebar, text='退出登录', command=self.on_logout, anchor='w', bg=SIDEBAR,
                  fg='#9bbdbb', relief='flat', font=(FONT, 11), cursor='hand2').pack(side='bottom', anchor='w', padx=30, pady=30)
        content = tk.Frame(self, bg=BG, padx=35, pady=30)
        content.grid(row=0, column=1, sticky='nsew')
        content.rowconfigure(3, weight=1)
        content.columnconfigure(0, weight=1)
        header = tk.Frame(content, bg='white', padx=24, pady=16)
        header.grid(row=0, column=0, sticky='ew')
        tk.Label(header, text='商品市场', bg='white', fg=INK, font=(FONT, 19, 'bold')).pack(side='left')
        tk.Label(header, text='按分类、价格与发布时间筛选', bg='white', fg='#788294',
                 font=(FONT, 11)).pack(side='left', padx=35)
        search = tk.Frame(content, bg='white', padx=20, pady=14)
        search.grid(row=1, column=0, sticky='ew', pady=(22, 8))
        self.keyword = tk.Entry(search, relief='flat', font=(FONT, 12), fg=INK)
        self.keyword.pack(side='left', fill='x', expand=True, ipady=5)
        self.keyword.bind('<Return>', lambda event: self.search())
        tk.Button(search, text='开始搜索', command=self.search, bg=GREEN, fg='white',
                  relief='flat', font=(FONT, 10), padx=16, cursor='hand2').pack(side='right')
        filters = tk.Frame(content, bg=BG)
        filters.grid(row=2, column=0, sticky='ew', pady=(4, 12))
        tk.Label(filters, text='分类', bg=BG, fg=INK, font=(FONT, 10)).pack(side='left')
        self.category = ttk.Combobox(filters, values=['全部'] + list(CATEGORIES), state='readonly', width=12)
        self.category.set('全部')
        self.category.pack(side='left', padx=(5, 12))
        tk.Label(filters, text='价格', bg=BG, fg=INK, font=(FONT, 10)).pack(side='left')
        self.minimum = tk.Entry(filters, width=7, relief='solid', bd=1)
        self.minimum.pack(side='left', padx=5)
        tk.Label(filters, text='—', bg=BG).pack(side='left')
        self.maximum = tk.Entry(filters, width=7, relief='solid', bd=1)
        self.maximum.pack(side='left', padx=5)
        self.sort = ttk.Combobox(filters, values=['最新发布', '价格从低到高', '价格从高到低'], state='readonly', width=15)
        self.sort.set('最新发布')
        self.sort.pack(side='left', padx=12)
        self.listing = tk.Frame(content, bg=BG)
        self.listing.grid(row=3, column=0, sticky='nsew')
        self.footer = tk.Frame(content, bg=BG)
        self.footer.grid(row=4, column=0, sticky='ew', pady=(12, 0))
        self.summary = tk.Label(self.footer, bg=BG, fg='#728091', font=(FONT, 10))
        self.summary.pack(side='left')
        tk.Button(self.footer, text='下一页', command=lambda: self.change_page(1)).pack(side='right', padx=4)
        tk.Button(self.footer, text='上一页', command=lambda: self.change_page(-1)).pack(side='right')
        self.refresh()

    def search(self):
        self.page = 1
        self.refresh()

    def change_page(self, offset):
        target = self.page + offset
        if target < 1 or (target - 1) * 20 >= self.total:
            return
        self.page = target
        self.refresh()

    def refresh(self):
        sort = {'最新发布': 'newest', '价格从低到高': 'price_asc', '价格从高到低': 'price_desc'}[self.sort.get()]
        try:
            result = self.service.products(token=self.token, scope='market', keyword=self.keyword.get(),
                                           category='' if self.category.get() == '全部' else self.category.get(),
                                           minimum=self.minimum.get().strip(), maximum=self.maximum.get().strip(),
                                           sort=sort, page=self.page)
        except TradeError as exc:
            messagebox.showerror('查询失败', str(exc), parent=self)
            return
        self.total = result['total']
        for child in self.listing.winfo_children():
            child.destroy()
        self.summary.config(text=f'共 {self.total} 件商品  ·  第 {self.page} 页  ·  校园身份未核验')
        if not result['items']:
            tk.Label(self.listing, text='暂无符合条件的商品', bg=BG, fg='#7e8999',
                     font=(FONT, 14)).pack(pady=80)
            return
        canvas = tk.Canvas(self.listing, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(self.listing, orient='vertical', command=canvas.yview)
        grid = tk.Frame(canvas, bg=BG)
        grid.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=grid, anchor='nw')
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        for index, product in enumerate(result['items']):
            self.card(grid, product, index)

    def card(self, parent, product, index):
        card = tk.Frame(parent, bg='white', padx=14, pady=14, width=245, height=265)
        card.grid(row=index // 3, column=index % 3, padx=(0, 20), pady=(0, 20), sticky='n')
        card.grid_propagate(False)
        palette = ['#ffd6aa', '#c4eddf', '#dfd1fa']
        block = tk.Label(card, bg=palette[index % len(palette)], text=product['category'],
                         fg='#607276', font=(FONT, 12))
        block.pack(fill='x', ipady=38)
        try:
            details = self.service.product_detail(product['id'], self.token)
            if details['images']:
                row = self.service.db.execute('SELECT data FROM images WHERE id=?',
                                              (details['images'][0]['id'],)).fetchone()
                if row:
                    with Image.open(io.BytesIO(row['data'])) as picture:
                        picture.thumbnail((215, 135))
                        block.photo = ImageTk.PhotoImage(picture.copy())
                    block.configure(image=block.photo, text='')
                    block.pack_configure(ipady=0)
        except (TradeError, OSError, ValueError):
            pass
        tk.Label(card, text=product['title'], bg='white', fg=INK, font=(FONT, 13, 'bold'),
                 anchor='w', wraplength=210).pack(fill='x', pady=(15, 5))
        bottom = tk.Frame(card, bg='white')
        bottom.pack(fill='x')
        tk.Label(bottom, text=f"¥ {Decimal(product['price_cents']) / 100:.2f}", bg='white',
                 fg='#c54810', font=(FONT, 13)).pack(side='left')
        text = '已预约' if product['status'] == 'reserved' else '查看详情'
        tk.Button(bottom, text=text, bg=GREEN, fg='white', relief='flat', cursor='hand2',
                  command=lambda: self.detail(product['id'])).pack(side='right')

    def detail(self, product_id):
        try:
            product = self.service.product_detail(product_id, self.token)
        except TradeError as exc:
            messagebox.showerror('无法查看', str(exc), parent=self)
            return
        popup = tk.Toplevel(self)
        popup.title('商品详情')
        popup.geometry('480x400')
        popup.configure(bg='white')
        body = tk.Frame(popup, bg='white', padx=30, pady=25)
        body.pack(fill='both', expand=True)
        tk.Label(body, text=product['title'], bg='white', fg=INK, font=(FONT, 18, 'bold'),
                 wraplength=400).pack(anchor='w')
        tk.Label(body, text=f"{product['category']} · {product['condition']} · ¥ {Decimal(product['price_cents']) / 100:.2f}",
                 bg='white', fg=GREEN, font=(FONT, 12)).pack(anchor='w', pady=12)
        tk.Label(body, text=product['description'], bg='white', fg=INK, font=(FONT, 11),
                 justify='left', wraplength=400).pack(anchor='w')
        if product['status'] == 'published' and self.account['role'] == 'user':
            def reserve():
                try:
                    self.service.reserve(self.token, str(uuid.uuid4()), product_id, product['version'])
                    messagebox.showinfo('预约成功', '预约已提交，等待卖家确认。预约不会自动释放。', parent=popup)
                    popup.destroy()
                    self.refresh()
                except TradeError as exc:
                    messagebox.showerror('预约失败', str(exc), parent=popup)
            tk.Button(body, text='预约商品', command=reserve, bg=GREEN, fg='white', relief='flat',
                      padx=20, pady=8, cursor='hand2').pack(anchor='w', pady=20)
        elif self.account['role'] == 'admin':
            tk.Label(body, text='管理员账号不可参与交易', bg='white', fg='#7c8797').pack(anchor='w', pady=20)
        if self.account['role'] == 'user':
            tk.Button(body, text='举报商品', command=lambda: self.workspace.report_form(product_id, popup),
                      relief='flat', fg=GREEN, bg='white', cursor='hand2').pack(anchor='w', pady=4)
