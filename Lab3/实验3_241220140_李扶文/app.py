"""JSON-lines command interface for the local campus marketplace."""

import argparse
import json
import sys
from pathlib import Path

from trade import Marketplace, TradeError


PUBLIC_METHODS = {
    'register', 'login', 'logout', 'profile', 'update_profile', 'create_invitation',
    'create_product', 'edit_product', 'product_transition', 'review_product',
    'reserve', 'reservation_transition', 'contact', 'submit_report', 'resolve_report',
    'products', 'product_detail', 'reservations', 'history_events', 'reports', 'reviews', 'stats', 'logs',
    'add_image', 'remove_image', 'export_image', 'backup',
}


def main():
    parser = argparse.ArgumentParser(description='校内二手交易系统：JSON 行命令接口')
    parser.add_argument('--db', default='campus_trade.sqlite3', help='SQLite 数据库路径')
    args = parser.parse_args()
    service = Marketplace(Path(args.db))
    print('校园身份未核验。每行输入一个 JSON 命令；输入 quit 退出。', file=sys.stderr)
    print('预约不会自动释放；系统无法逆转线下交付。', file=sys.stderr)
    try:
        for line in sys.stdin:
            if line.strip() == 'quit':
                break
            try:
                command = json.loads(line)
                method = command.get('method')
                if method not in PUBLIC_METHODS and method != 'initialize_admin':
                    raise TradeError('未知命令')
                values = command.get('params', {})
                if not isinstance(values, dict):
                    raise TradeError('params 必须是对象')
                result = getattr(service, method)(**values)
                print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False), flush=True)
            except TradeError as exc:
                print(json.dumps({'ok': False, 'status': exc.status, 'error': str(exc)}, ensure_ascii=False), flush=True)
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                print(json.dumps({'ok': False, 'status': 400, 'error': '命令或参数无效: ' + str(exc)},
                                 ensure_ascii=False), flush=True)
    finally:
        service.close()


if __name__ == '__main__':
    main()
