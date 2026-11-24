# 校园二手交易系统

## 桌面界面

安装下方依赖并完成首次管理员初始化后，在 Windows 上双击 `login.pyw`，或在本目录运行 `python login.pyw`，打开桌面登录界面。普通用户可以通过登录界面注册；管理员可以进入治理中心。商品和预约等操作写入本地 SQLite 数据库，仓库不包含数据库或真实账号数据。

演示脚本 `demo_data.py` 只适用于已有示例管理员 `admin01` 和普通用户 `student01` 的本地教学数据库；不要用于真实账号。商品图片当前使用文件选择器，暂不支持拖入。

## 命令行接口

这是本地 Python 命令行教学原型。Python 3.9 或以上，图片校验使用 Pillow。运行 `python -m pip install -r requirements.txt` 安装依赖，在本目录执行 `python app.py --db campus_trade.sqlite3`。每行输入一个 JSON 命令，输出一行 JSON，输入 `quit` 退出；数据库首次运行时自动创建。所有数据使用虚构信息，校园身份未核验。

首次启动需在本机执行管理员初始化，初始化只能成功一次：

```json
{"method":"initialize_admin","params":{"username":"admin01","password":"AdminPass123","nickname":"管理员","phone":"13800000000"}}
{"method":"register","params":{"username":"seller01","password":"SellerPass123","nickname":"卖家","phone":"13800000001"}}
{"method":"login","params":{"username":"seller01","password":"SellerPass123"}}
```

登录返回的 `token` 需要传入受限操作。示例中的 `TOKEN`、请求标识和资源 ID 必须替换为真实值；业务请求标识可自行生成 UUID，同一操作的重试使用同一标识。商品和预约的 `version` 使用最近一次查询结果。

```json
{"method":"create_product","params":{"token":"TOKEN","request_id":"request-1","data":{"title":"线性代数","description":"教材","category":"教材书籍","condition":"正常使用","price":"12.00"}}}
{"method":"product_transition","params":{"token":"TOKEN","request_id":"request-2","product_id":"PRODUCT_ID","version":1,"transition":"submit"}}
{"method":"products","params":{"scope":"market"}}
```

命令名称和参数对应 `trade.py` 中 `Marketplace` 的公开方法。主要命令：`create_invitation`、`update_profile`、`products`（范围 `market` / `mine` / `admin`）、`edit_product`、`product_transition`（`submit` / `retract` / `withdraw`）、`review_product`（`approve` / `reject`）、`add_image`、`remove_image`、`export_image`、`reserve`、`reservations`、`reservation_transition`（`confirm` / `cancel` / `complete`）、`contact`、`submit_report`、`reports`、`resolve_report`（`reject` / `violation`）、`reviews`、`stats`、`logs`、`logout`。取消时必须传入 `confirmed: true` 和原因。管理员邀请码仅首次生成时显示，请妥善保管；密码和令牌不要提交到版本库。

`product_detail` 查询可见商品及图片标识；`history_events` 只允许预约的买卖双方查询该预约的事件。管理员使用 `logs` 查询全局审计事件。

退出程序后数据仍保存在 SQLite 文件。可以通过 `backup` 命令将数据库备份到本机文件，恢复时先停止程序并用备份替换数据库。运行测试：`python -m unittest discover -s tests -v`。

本程序是本机教学原型，命令行不提供网络服务或 HTTPS；请勿在共享终端输入真实密码或电话。线下交付不能由系统逆转，确认预约后曾被记录的电话也无法远程收回。
