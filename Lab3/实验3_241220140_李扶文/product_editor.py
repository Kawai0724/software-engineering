"""Product editor based on the experiment's orange-and-white UI prototype."""

import io
import uuid
from decimal import Decimal
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk
from trade import CATEGORIES, CONDITIONS, TradeError

BACKGROUND = '#f7f8fc'
TEXT = '#192741'
MUTED = '#718094'
ORANGE = '#ff7116'
BUTTON = '#ed5008'
PALE = '#fff4e9'
PEACH = '#ffe1d1'
FONT = 'Microsoft YaHei'


class ProductEditor:
    def __init__(self, parent, service, token, product, after):
        self.service = service
        self.token = token
        self.product = product
        self.after = after
        self.paths = []
        self.photos = []
        self.fields = {}
        self.win = tk.Toplevel(parent)
        self.win.title('新建商品' if product is None else '编辑商品')
        self.win.configure(bg=BACKGROUND)
        self.win.geometry('1100x720')
        self.win.minsize(860, 620)
        self.build()

    def build(self):
        header = tk.Frame(self.win, bg=ORANGE, height=78)
        header.pack(fill='x')
        header.pack_propagate(False)
        tk.Label(header, text='新建商品' if self.product is None else '编辑商品', bg=ORANGE,
                 fg='white', font=(FONT, 20, 'bold')).pack(side='left', padx=(45, 30))
        for text, command in [('01  基础信息', self.focus_title),
                              ('02  上传图片', self.choose_images),
                              ('03  发布预览', self.preview)]:
            tk.Button(header, text=text, command=command, bg=ORANGE, fg='white',
                      activebackground=ORANGE, activeforeground='white', relief='flat',
                      font=(FONT, 12), cursor='hand2').pack(side='left', padx=(0, 36))
        body = tk.Frame(self.win, bg=BACKGROUND, padx=45, pady=23)
        body.pack(fill='both', expand=True)
        tk.Label(body, text='填写商品资料', bg=BACKGROUND, fg=TEXT,
                 font=(FONT, 22, 'bold'), anchor='w').pack(fill='x')
        tk.Label(body, text='保存草稿不会公开；提交审核后不能直接编辑', bg=BACKGROUND, fg=MUTED,
                 font=(FONT, 10), anchor='w').pack(fill='x', pady=(1, 20))
        content = tk.Frame(body, bg=BACKGROUND)
        content.pack(fill='both', expand=True)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(4, weight=1)
        definitions = [('title', '标题'), ('category', '类别'), ('condition', '成色'),
                       ('price', '标价'), ('description', '描述')]
        for row, (name, label) in enumerate(definitions):
            tk.Label(content, text=label, bg=BACKGROUND, fg=TEXT, font=(FONT, 12),
                     anchor='w').grid(row=row, column=0, sticky='nw', padx=(12, 35), pady=(11, 10))
            container = tk.Frame(content, bg='white', padx=17, pady=8)
            container.grid(row=row, column=1, sticky='ew' if name != 'description' else 'nsew', pady=(0, 12))
            if name in ('category', 'condition'):
                widget = ttk.Combobox(container, values=CATEGORIES if name == 'category' else CONDITIONS,
                                      state='readonly', font=(FONT, 11))
                widget.pack(fill='x', ipady=5)
            elif name == 'description':
                widget = tk.Text(container, height=3, relief='flat', bg='white', fg=TEXT,
                                 font=(FONT, 11), highlightthickness=0, wrap='word')
                widget.pack(fill='both', expand=True)
            else:
                widget = tk.Entry(container, relief='flat', bg='white', fg=TEXT,
                                  font=(FONT, 11), highlightthickness=0)
                widget.pack(fill='x', ipady=5)
            self.fields[name] = widget
        self.populate()
        image_area = tk.Frame(content, bg=PEACH, width=155, height=175, cursor='hand2')
        image_area.grid(row=0, column=2, rowspan=3, padx=(30, 0), pady=(0, 12), sticky='n')
        image_area.grid_propagate(False)
        self.image_title = tk.Label(image_area, text='图片区', bg=PEACH, fg=TEXT, font=(FONT, 15))
        self.image_title.pack(pady=(30, 8))
        self.image_status = tk.Label(image_area, text='点击选择图片\n最多 5 张', bg=PEACH, fg=MUTED,
                                     font=(FONT, 10), justify='center', wraplength=140)
        self.image_status.pack()
        for widget in (image_area, self.image_title, self.image_status):
            widget.bind('<Button-1>', lambda event: self.choose_images())
        self.status = tk.Label(body, text='', bg=BACKGROUND, fg='#bd3545', font=(FONT, 10), anchor='w')
        self.status.pack(fill='x', pady=(3, 0))
        actions = tk.Frame(body, bg=BACKGROUND)
        actions.pack(fill='x', pady=(8, 6))
        tk.Button(actions, text='提交审核', command=lambda: self.save(True), bg=BUTTON, fg='white',
                  relief='flat', padx=25, pady=10, font=(FONT, 12), cursor='hand2').pack(side='right', padx=(18, 0))
        tk.Button(actions, text='保存草稿', command=lambda: self.save(False), bg=PALE, fg='#d34a0a',
                  relief='flat', padx=25, pady=10, font=(FONT, 12), cursor='hand2').pack(side='right')

    def focus_title(self):
        self.fields['title'].focus_set()

    def populate(self):
        if not self.product:
            return
        for name, widget in self.fields.items():
            if name == 'price':
                cents = self.product['price_cents']
                value = '' if cents is None else f'{Decimal(cents) / 100:.2f}'
            else:
                value = self.product.get(name, '') or ''
            if name == 'description':
                widget.insert('1.0', value)
            elif name in ('category', 'condition'):
                widget.set(value)
            else:
                widget.insert(0, value)

    def data(self):
        return {name: (widget.get('1.0', 'end').strip() if name == 'description' else widget.get().strip())
                for name, widget in self.fields.items()}

    def choose_images(self):
        chosen = filedialog.askopenfilenames(parent=self.win, title='选择商品图片',
                                             filetypes=[('JPEG / PNG', '*.jpg *.jpeg *.png')])
        if not chosen:
            return
        existing_count = len(self.product.get('images', [])) if self.product else 0
        if len(chosen) + existing_count > 5:
            self.status.config(text='每件商品最多 5 张图片。')
            return
        for path in chosen:
            try:
                if Path(path).stat().st_size > 5 * 1024 * 1024:
                    raise ValueError('单张图片不能超过 5 MB')
                with Image.open(path) as picture:
                    if picture.format not in ('JPEG', 'PNG'):
                        raise ValueError('只支持 JPEG 或 PNG 图片')
                    picture.verify()
            except (OSError, ValueError) as exc:
                self.status.config(text='图片无法使用：' + str(exc))
                return
        self.paths = list(chosen)
        self.status.config(text='')
        self.image_status.config(text=f'已选择 {len(self.paths)} 张\n点击重新选择')

    def preview(self):
        data = self.data()
        popup = tk.Toplevel(self.win)
        popup.title('发布预览')
        popup.geometry('520x540')
        popup.configure(bg='white')
        frame = tk.Frame(popup, bg='white', padx=30, pady=25)
        frame.pack(fill='both', expand=True)
        for label, value in [('标题', data['title']), ('类别', data['category']),
                             ('成色', data['condition']), ('标价', data['price']), ('描述', data['description'])]:
            tk.Label(frame, text=f'{label}：{value or "（未填写）"}', bg='white', fg=TEXT,
                     font=(FONT, 11), anchor='w', justify='left', wraplength=440).pack(fill='x', pady=6)
        tk.Label(frame, text=f'已选新图片：{len(self.paths)} 张', bg='white', fg=MUTED,
                 font=(FONT, 10)).pack(anchor='w', pady=8)
        if self.paths:
            try:
                with Image.open(self.paths[0]) as image:
                    image.thumbnail((230, 150))
                    photo = ImageTk.PhotoImage(image.copy())
                label = tk.Label(frame, image=photo, bg='white')
                label.image = photo
                label.pack(anchor='w')
            except (OSError, ValueError):
                pass
        tk.Button(frame, text='返回编辑', command=popup.destroy, bg=ORANGE, fg='white',
                  relief='flat', padx=18, pady=7).pack(anchor='w', pady=12)

    def save(self, submit):
        data = self.data()
        try:
            # Validate the whole requested operation before writing the draft.
            self.service.product_values(data, complete=submit)
            if self.product:
                result = self.service.edit_product(self.token, str(uuid.uuid4()), self.product['id'],
                                                   self.product['version'], data)
            else:
                result = self.service.create_product(self.token, str(uuid.uuid4()), data)
            # Keep the current committed product so retry never creates a duplicate.
            self.product = result
            while self.paths:
                path = self.paths[0]
                result = self.service.add_image(self.token, str(uuid.uuid4()), result['id'], result['version'], path)
                self.product = result
                self.paths.pop(0)
            if submit:
                result = self.service.product_transition(self.token, str(uuid.uuid4()), result['id'], result['version'], 'submit')
                self.product = result
            self.win.destroy()
            self.after()
        except (TradeError, OSError, ValueError) as exc:
            self.status.config(text=str(exc))
            if self.product:
                self.after()
