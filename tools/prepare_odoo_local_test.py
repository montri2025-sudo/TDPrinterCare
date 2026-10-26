"""Create ignored local test credentials. Never overwrite existing configuration."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / '.env.local-test'
if target.exists():
    print('Existing .env.local-test preserved.')
else:
    values = {}
    for line in (root / '.env.example').read_text().splitlines():
        if line and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key] = value
    values.update(PG_PASSWORD=secrets.token_urlsafe(32), ODOO_DB_PASSWORD=secrets.token_urlsafe(32),
                  ODOO_MASTER_PASSWORD=secrets.token_urlsafe(32), ODOO_URL='http://odoo:8069',
                  ODOO_DB='tdprinter_test', ODOO_USERNAME='td-test-admin', ODOO_API_KEY=secrets.token_urlsafe(32),
                  SEED_DEMO_DATA='0', INITIAL_ADMIN_USERNAME='td-test-admin',
                  INITIAL_ADMIN_PASSWORD=secrets.token_urlsafe(24), COOKIE_SECURE='0',
                  PUBLIC_BASE_URL='http://127.0.0.1:18865')
    # Exclusive mode avoids replacing another process's newly-created credentials.
    with target.open('x') as handle:
        handle.write('\n'.join(key+'='+value for key,value in values.items())+'\n')
    target.chmod(0o600)
    print('Created .env.local-test with random credentials; no secrets printed.')
