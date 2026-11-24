"""Login and registration screen for the campus marketplace."""

import tkinter as tk
from pathlib import Path

from trade import Marketplace, TradeError
from market import MarketView


NAVY = '#16223e'
INK = '#172440'
MUTED = '#6b7488'
LAVENDER = '#b8c9ff'
PAGE = '#f7f8fc'
INPUT = '#eef1f8'
PURPLE = '#5040d8'
FONT = 'Microsoft YaHei'


class LoginWindow:
    def __init__(self, root, service):
        self.root = root
        self.service = service
        self.token = None
        root.title('交换实验室 - 校园二手交易')
        root.geometry('1200x750')
        root.minsize(850, 600)
        root.configure(bg=PAGE)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.left = tk.Frame(root, bg=NAVY, width=490)
        self.left.pack(side='left', fill='y')
        self.left.pack_propagate(False)
        tk.Label(self.left, text='交换实验室', bg=NAVY, fg='white',
                 font=(FONT, 28, 'bold')).place(x=55, rely=.16)
        tk.Label(self.left, text='校内闲置物品\n重新流动起来', bg=NAVY, fg='#c5d2fa',
                 font=(FONT, 21), justify='left', anchor='w').place(x=55, rely=.27)
        tk.Label(self.left, text='校园身份未核验\n请线下当面确认交易。', bg=NAVY, fg=LAVENDER,
                 font=(FONT, 13), justify='left', anchor='w').place(x=55, rely=.79)
        self.right = tk.Frame(root, bg=PAGE)
        self.right.pack(side='left', fill='both', expand=True)
        self.card = tk.Frame(self.right, bg='white', padx=65, pady=45)
        self.card.place(relx=.5, rely=.5, anchor='center', relwidth=.78)
        self.show_login()

    def clear(self):
        for child in self.card.winfo_children():
            child.destroy()
        self.error = tk.StringVar(value='')

    def heading(self, title, subtitle):
        tk.Label(self.card, text=title, bg='white', fg=INK, font=(FONT, 24, 'bold'),
                 anchor='w').pack(fill='x')
        tk.Label(self.card, text=subtitle, bg='white', fg=MUTED, font=(FONT, 12),
                 anchor='w').pack(fill='x', pady=(4, 25))

    def field(self, label, secret=False):
        tk.Label(self.card, text=label, bg='white', fg=INK, font=(FONT, 12),
                 anchor='w').pack(fill='x', pady=(4, 5))
        container = tk.Frame(self.card, bg=INPUT, padx=15, pady=8)
        container.pack(fill='x', pady=(0, 6))
        entry = tk.Entry(container, relief='flat', bg=INPUT, fg=INK,
                         font=(FONT, 12), show='●' if secret else '',
                         insertbackground=INK, highlightthickness=0)
        entry.pack(fill='x', ipady=5)
        return entry

    def error_label(self):
        tk.Label(self.card, textvariable=self.error, bg='white', fg='#bd3545',
                 font=(FONT, 10), anchor='w', wraplength=420).pack(fill='x', pady=(3, 0))

    def button(self, text, command):
        tk.Button(self.card, text=text, bg=PURPLE, fg='white', activebackground='#4030c5',
                  activeforeground='white', relief='flat', cursor='hand2',
                  font=(FONT, 13), command=command).pack(fill='x', ipady=10, pady=(8, 12))

    def link(self, text, command):
        label = tk.Label(self.card, text=text, bg='white', fg=PURPLE, cursor='hand2',
                         font=(FONT, 11), anchor='w')
        label.pack(fill='x', pady=(5, 0))
        label.bind('<Button-1>', lambda event: command())

    def show_login(self):
        self.clear()
        self.heading('欢迎回来', '使用账号管理你的商品与预约')
        username = self.field('用户名')
        password = self.field('密码', secret=True)
        self.error_label()
        def submit():
            if not username.get().strip() or not password.get():
                self.error.set('请输入用户名和密码')
                return
            try:
                result = self.service.login(username.get().strip(), password.get())
                self.token = result['token']
                self.show_logged_in(result)
            except TradeError as exc:
                self.error.set(str(exc))
        self.button('登录', submit)
        self.link('没有账号？ 普通用户注册', self.show_register)
        username.focus_set()
        username.bind('<Return>', lambda event: password.focus_set())
        password.bind('<Return>', lambda event: submit())

    def show_register(self):
        self.clear()
        self.heading('创建账号', '注册后可以发布商品、预约和举报')
        username = self.field('用户名（3–20 位字母、数字或下划线）')
        nickname = self.field('昵称')
        phone = self.field('联系电话（11 位数字）')
        password = self.field('密码（10–64 位，包含字母和数字）', secret=True)
        invitation = self.field('管理员邀请码（普通用户可留空）')
        self.error_label()
        def submit():
            try:
                self.service.register(username.get().strip(), password.get(),
                                      nickname.get().strip(), phone.get().strip(),
                                      invitation.get().strip() or None)
                self.show_login()
                self.error.set('注册成功，请登录')
            except TradeError as exc:
                self.error.set(str(exc))
        self.button('注册', submit)
        self.link('已有账号？ 返回登录', self.show_login)
        username.focus_set()

    def show_logged_in(self, account):
        self.left.pack_forget()
        self.right.pack_forget()
        self.market = MarketView(self.root, self.service, self.token, account, self.logout)
        self.market.pack(fill='both', expand=True)

    def logout(self):
        try:
            if self.token:
                self.service.logout(self.token)
        except TradeError:
            pass
        self.token = None
        if hasattr(self, 'market'):
            self.market.destroy()
            del self.market
            self.left.pack(side='left', fill='y')
            self.right.pack(side='left', fill='both', expand=True)
        self.show_login()

    def close(self):
        if self.token:
            try:
                self.service.logout(self.token)
            except TradeError:
                pass
        self.service.close()
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    LoginWindow(root, Marketplace(Path(__file__).with_name('campus_trade.sqlite3')))
    root.mainloop()
