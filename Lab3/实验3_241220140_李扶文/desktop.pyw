"""Desktop front end for the campus marketplace service."""

import inspect
import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from trade import Marketplace, TradeError


OPERATIONS = {
    '浏览商品': 'products', '商品详情': 'product_detail',
    '注册账号': 'register', '登录': 'login', '退出登录': 'logout',
    '我的资料': 'profile', '修改资料': 'update_profile',
    '创建商品草稿': 'create_product', '编辑商品': 'edit_product',
    '提交/撤回/下架商品': 'product_transition', '查看审核记录': 'reviews',
    '添加商品图片': 'add_image', '删除商品图片': 'remove_image',
    '创建预约': 'reserve', '我的预约': 'reservations',
    '确认/取消/完成预约': 'reservation_transition', '查看对方电话': 'contact',
    '查看预约事件': 'history_events', '举报商品': 'submit_report',
    '查看举报': 'reports', '审核商品（管理员）': 'review_product',
    '处置举报（管理员）': 'resolve_report', '统计': 'stats',
    '审计日志（管理员）': 'logs', '生成邀请码（管理员）': 'create_invitation',
}
LABELS = {
    'username': '用户名', 'password': '密码', 'nickname': '昵称', 'phone': '电话',
    'invitation': '管理员邀请码（可选）', 'request_id': '请求标识（自动生成）',
    'product_id': '商品 ID', 'reservation_id': '预约 ID', 'report_id': '举报 ID',
    'image_id': '图片 ID', 'version': '版本号', 'product_version': '商品版本号',
    'data': '商品数据（JSON 对象）', 'scope': '范围 market / mine / admin',
    'keyword': '关键词', 'category': '分类', 'minimum': '最低价格', 'maximum': '最高价格',
    'states': '状态列表（JSON 数组）', 'sort': '排序 newest / price_asc / price_desc',
    'page': '页码', 'transition': '操作：submit / retract / withdraw 或 confirm / cancel / complete',
    'decision': '决定：approve / reject / violation', 'reason': '原因', 'details': '举报说明',
    'note': '处置说明', 'confirmed': '二次确认 true / false', 'path': '图片文件路径',
    'start': '起始日期 YYYY-MM-DD', 'end': '结束日期 YYYY-MM-DD', 'filters': '日志筛选（JSON 对象）',
}


class Desktop:
    def __init__(self, root):
        import uuid
        self.uuid = uuid
        self.root = root
        self.service = Marketplace(Path(__file__).with_name('campus_trade.sqlite3'))
        self.token = None
        self.inputs = {}
        root.title('校园二手交易系统 - 教学原型')
        root.geometry('1050x760')
        root.minsize(800, 600)
        root.protocol('WM_DELETE_WINDOW', self.close)
        top = ttk.Frame(root, padding=12)
        top.pack(fill='x')
        ttk.Label(top, text='校园二手交易系统', font=('Microsoft YaHei', 17, 'bold')).pack(side='left')
        self.identity = ttk.Label(top, text='游客 · 校园身份未核验')
        self.identity.pack(side='right')
        ttk.Label(root, text='预约不会自动释放；线下交付不能由系统逆转。', foreground='#9a5b00').pack(anchor='w', padx=12)
        area = ttk.Frame(root, padding=12)
        area.pack(fill='both', expand=True)
        left = ttk.Frame(area)
        left.pack(side='left', fill='both', expand=True)
        right = ttk.Frame(area)
        right.pack(side='right', fill='both', expand=True, padx=(18, 0))
        ttk.Label(left, text='选择功能', font=('Microsoft YaHei', 11, 'bold')).pack(anchor='w')
        self.choice = ttk.Combobox(left, values=list(OPERATIONS), state='readonly')
        self.choice.pack(fill='x', pady=8)
        self.choice.bind('<<ComboboxSelected>>', self.make_form)
        self.form = ttk.Frame(left)
        self.form.pack(fill='both', expand=True)
        ttk.Button(left, text='执行', command=self.execute).pack(fill='x', pady=8)
        ttk.Label(right, text='运行结果', font=('Microsoft YaHei', 11, 'bold')).pack(anchor='w')
        self.output = tk.Text(right, wrap='word', font=('Consolas', 10))
        self.output.pack(fill='both', expand=True, pady=8)
        self.choice.set('浏览商品')
        self.make_form()

    def make_form(self, event=None):
        for child in self.form.winfo_children():
            child.destroy()
        self.inputs = {}
        method = getattr(self.service, OPERATIONS[self.choice.get()])
        for param in inspect.signature(method).parameters.values():
            if param.name == 'token':
                continue
            ttk.Label(self.form, text=LABELS.get(param.name, param.name), wraplength=480).pack(anchor='w')
            entry = ttk.Entry(self.form, show='*' if param.name == 'password' else '')
            entry.pack(fill='x', pady=(0, 7))
            if param.name == 'request_id':
                entry.insert(0, str(self.uuid.uuid4()))
            elif param.name == 'data':
                entry.insert(0, json.dumps({'title': '', 'description': '', 'category': '教材书籍',
                                            'condition': '正常使用', 'price': ''}, ensure_ascii=False))
            elif param.default is not inspect.Parameter.empty and param.default not in (None, ''):
                entry.insert(0, json.dumps(param.default) if isinstance(param.default, bool) else str(param.default))
            self.inputs[param.name] = (entry, param)

    def execute(self):
        method = getattr(self.service, OPERATIONS[self.choice.get()])
        parameters = inspect.signature(method).parameters
        args = {}
        if 'token' in parameters:
            args['token'] = self.token
        try:
            for name, (widget, param) in self.inputs.items():
                value = widget.get().strip()
                if not value and param.default is not inspect.Parameter.empty:
                    continue
                if name in ('version', 'product_version', 'page'):
                    value = int(value)
                elif name in ('data', 'states', 'filters', 'confirmed'):
                    value = json.loads(value)
                args[name] = value
            result = method(**args)
            if self.choice.get() == '登录':
                self.token = result['token']
                self.identity.config(text=result['nickname'] + ' · ' + result['role'] + ' · 校园身份未核验')
                result = {key: value for key, value in result.items() if key != 'token'}
            elif self.choice.get() == '退出登录':
                self.token = None
                self.identity.config(text='游客 · 校园身份未核验')
            self.output.delete('1.0', 'end')
            self.output.insert('end', json.dumps(result, ensure_ascii=False, indent=2))
            if 'request_id' in self.inputs:
                widget = self.inputs['request_id'][0]
                widget.delete(0, 'end')
                widget.insert(0, str(self.uuid.uuid4()))
        except (TradeError, ValueError, TypeError, OSError) as exc:
            messagebox.showerror('操作失败', str(exc))

    def close(self):
        self.service.close()
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    Desktop(root)
    root.mainloop()
