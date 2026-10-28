"""Offline private invitation issuer. No AI requests or server credentials."""
import argparse
import csv
import hashlib
import hmac
import os
from pathlib import Path
import secrets
from datetime import datetime, timezone


def issue(secret, limit, days):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError('次数须为 1–100 / Attempts must be 1–100.')
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 30:
        raise ValueError('有效天数须为 1–30 / Days must be 1–30.')
    if len(secret) != 64 or any(c not in '0123456789abcdef' for c in secret):
        raise ValueError('Invalid issuer key.')
    body = f'MIRROR.{secrets.token_hex(12)}.{limit}.{days}'
    signature = hmac.new(bytes.fromhex(secret), body.encode(), hashlib.sha256).hexdigest()
    return body + '.' + signature


def main():
    parser = argparse.ArgumentParser(description='Mirror 私人测试码生成器（离线生成，不消耗 AI 费用）')
    parser.add_argument('--attempts', type=int)
    parser.add_argument('--days', type=int)
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parents[2] / 'private-fixtures' / 'beta-admin')
    args = parser.parse_args()
    try:
        attempts = args.attempts if args.attempts is not None else int(input('生成次数（1–100，例如 3）：'))
        days = args.days if args.days is not None else int(input('首次使用后有效天数（1–30，例如 7）：'))
        # Validate before creating any files.
        issue('0' * 64, attempts, days)
        folder = args.directory.expanduser()
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        keyfile = folder / 'issuer-secret.txt'
        try:
            fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'w') as stream:
                stream.write(secrets.token_hex(32))
            print('首次配置：需将 issuer-secret.txt 内容配置为 Vercel 的 MAKEUP_BETA_CODE_SECRET，再部署。未完成前生成的码不能兑换。')
        code = issue(keyfile.read_text().strip(), attempts, days)
        history = folder / 'issued-codes.csv'
        fd = os.open(history, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a', newline='') as stream:
            writer = csv.writer(stream)
            if history.stat().st_size == 0:
                writer.writerow(['Created UTC', 'Code', 'Attempts', 'Days after activation'])
            writer.writerow([datetime.now(timezone.utc).isoformat(), code, attempts, days])
        print(f'\n测试码（复制整行）：\n{code}\n\n共 {attempts} 次；首次兑换后 {days} 天有效。\n同码多人共用总额度；重复兑换不重置。\n记录保存在：{history}\n不要公开分享管理密钥。')
    except (ValueError, OSError) as exc:
        parser.exit(1, f'无法生成测试码：{exc}\n')
    except (EOFError, KeyboardInterrupt):
        parser.exit(1, '\n已取消。\n')


if __name__ == '__main__':
    main()
