"""Field-service Demo (/field-service): role access, fictional-only page, no database writes."""
import json
from pathlib import Path
import re
import sqlite3
import unittest
from unittest.mock import patch

import test_integration_api as fixtures
import field_service_google
import test_virtual_office as office
import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'static'
WRITE_SQL = re.compile(r'^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER)\b', re.I)


class RecordingConn(office.OfficeConn):
    log = []

    def execute(self, sql, params=()):
        RecordingConn.log.append(sql)
        return super().execute(sql, params)


class TestFieldServiceDemo(fixtures.ApiTestCase):
    def setUp(self):
        super().setUp()                      # fictional SQLite fixtures only
        self.tokens = []
        self.mutate("INSERT INTO Users (user_id,username,password,role,name,is_active) VALUES (99,'fictional-admin','fictional','admin','Fiction Admin',1)")
        self.mutate("INSERT INTO Users (user_id,username,password,role,name,is_active) VALUES (98,'fictional-sales','fictional','sales','Fiction Sales',1)")

    def tearDown(self):
        for token in self.tokens:
            app.SESSIONS.pop(token, None)
        super().tearDown()

    def request(self, *args, **kwargs):
        return office.TestVirtualOffice.request(self, *args, **kwargs)

    def page(self, user_id, method='GET'):
        return self.request('/field-service/demo', user_id=user_id, method=method, query='')

    def config(self, html):
        return json.loads(re.search(r'id="fsd-config" type="application/json">(.*?)</script>', html, re.S).group(1))

    def fingerprint(self):
        raw = sqlite3.connect(self.path)
        try:
            return {t: raw.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall()
                    for t in ('Tickets', 'Ticket_Status_History', 'Spare_Parts', 'Users', 'Notifications', 'Devices', 'Customers')}
        finally:
            raw.close()

    def test_admin_sees_all_views_and_clear_demo_label(self):
        status, _, html = self.page(99)
        self.assertEqual(status, 200)
        config = self.config(html)
        self.assertEqual({k: config[k] for k in ('views', 'defaultView', 'role')}, {'views': ['control', 'tech', 'customer', 'route'], 'defaultView': 'control', 'role': 'admin'})
        self.assertEqual(config['google']['routing'], False)          # no key configured in tests
        self.assertIsNone(config['google']['mapsKey'])
        self.assertIn('Demo / ข้อมูลจำลอง', html)
        self.assertIn('href="/field-service"', html)
        for asset in ('field-service-core.js', 'field-service-data.js', 'field-service-demo.js', 'field-service-tour.js', 'field-service-demo.css'):
            self.assertIn('/static/' + asset, html)
        self.assertIn('ไม่ใช่เส้นทางถนนจริง', html)

    def test_configured_page_gets_browser_key_but_never_server_key(self):
        with patch.dict('os.environ', {'GOOGLE_ROUTES_API_KEY': 'server-secret-not-real', 'GOOGLE_MAPS_BROWSER_KEY': 'browser-key-not-real'}):
            html = self.page(99)[2]
        self.assertNotIn('server-secret-not-real', html)
        google = self.config(html)['google']
        self.assertEqual((google['routing'], google['mapsKey']), (True, 'browser-key-not-real'))

    def test_page_embeds_no_real_records(self):
        html = self.page(99)[2]
        for sentinel in ('SENTINEL_CUSTOMER', 'SENTINEL_PHONE', 'SENTINEL_ADDR', 'SENTINEL_ISSUE', 'SENTINEL_NOTES', 'FAKE-SN-', 'Fiction Printer', 'SENTINEL_LOGIN'):
            self.assertNotIn(sentinel, html)

    def test_role_scoped_views(self):
        for uid, role, views in ((21, 'manager', ['control', 'tech', 'customer', 'route']),
                                 (12, 'technician_lead', ['control', 'tech', 'customer', 'route']),
                                 (11, 'technician', ['tech', 'route']),
                                 (98, 'sales', ['control', 'customer'])):
            status, _, html = self.page(uid)
            self.assertEqual(status, 200, role)
            self.assertEqual(self.config(html)['views'], views, role)
            self.assertEqual(self.config(html)['defaultView'], views[0], role)
            self.assertIn('href="/field-service"', html, role)

    def test_customer_and_anonymous_are_refused(self):
        for uid in (20,):
            status, _, html = self.page(uid)
            self.assertEqual(status, 403, uid)
            self.assertNotIn('fsd-config', html)
        status, headers, _ = self.request('/field-service', user_id=999999, query='')
        self.assertEqual(status, 302)
        self.assertEqual(headers['Location'], '/login')
        self.assertNotIn('href="/field-service"', self.request('/customer/tickets', user_id=20, query='')[2])

    def test_viewing_and_posting_never_write_to_database(self):
        before = self.fingerprint()
        RecordingConn.log = []
        with patch.object(app.db, 'get_conn', side_effect=lambda: RecordingConn(self.path)):
            for uid in (99, 21, 12, 11, 98):
                self.page(uid)
            post_status = self.page(99, method='POST')[0]
        self.assertEqual(post_status, 404)            # there is no POST endpoint for the Demo
        writes = [sql for sql in RecordingConn.log if WRITE_SQL.match(sql)]
        self.assertEqual(writes, [])
        self.assertFalse(any('Field' in sql or 'field' in sql for sql in RecordingConn.log))
        self.assertEqual(self.fingerprint(), before)




class TestFieldServiceStaticFiles(unittest.TestCase):
    def test_demo_scripts_have_no_network_writes_or_location_requests(self):
        for name in ('field-service-core.js', 'field-service-data.js', 'field-service-demo.js'):
            src = (STATIC / name).read_text(encoding='utf-8')
            for banned in ('XMLHttpRequest', 'sendBeacon', 'navigator.geolocation', 'getCurrentPosition', '.submit(', 'localStorage', "method: 'POST'"):
                self.assertNotIn(banned, src, f'{name}: {banned}')
        demo = (STATIC / 'field-service-demo.js').read_text(encoding='utf-8')
        self.assertEqual(demo.count('fetch('), 1)                      # single helper, GET only
        self.assertEqual(sorted(set(re.findall(r"getJson\('([^'?]+)", demo))), ['/field-service/google/matrix', '/field-service/google/route'])
        self.assertEqual(re.findall(r"'(https://[^/']+)", demo), ['https://maps.googleapis.com'])
        self.assertNotIn('GOOGLE_ROUTES_API_KEY', demo)
        tour = (STATIC / 'field-service-tour.js').read_text(encoding='utf-8')
        self.assertEqual(re.findall(r"fetch\('([^']+)'", tour), ['/static/field-service-voice/manifest.json'])
        self.assertNotIn('speechSynthesis', tour)     # no substitute voice for the owner's narration

    def test_fictional_data_markers(self):
        data = (STATIC / 'field-service-data.js').read_text(encoding='utf-8')
        serials = re.findall(r"serial: '([^']+)'", data)
        phones = re.findall(r"phone: '([^']+)'", data)
        self.assertGreaterEqual(len(serials), 10)
        self.assertTrue(all(s.startswith('DEMO-') for s in serials))
        self.assertTrue(all(p.startswith('02-000-') for p in phones))
        self.assertGreaterEqual(len(re.findall(r'\(ตัวละครสมมติ\)', data)), 5)
        coords = dict((cid, (float(a), float(b))) for cid, a, b in re.findall(r"(C\d): \{ id: '\1'.*?lat: ([\d.]+), lng: ([\d.]+) \}", data))
        hq = re.search(r"id: 'HQ'.*?lat: ([\d.]+), lng: ([\d.]+)", data)
        coords['HQ'] = (float(hq.group(1)), float(hq.group(2)))
        self.assertEqual(coords, field_service_google.DEMO_POINTS)   # one set of fictional points, browser == server
        for lat, lng in coords.values():                              # all near the service centre (Bangkok east)
            self.assertTrue(13.7 < lat < 13.95 and 100.55 < lng < 100.8)

    def test_voice_manifest_only_maps_current_tour_lines_to_existing_files(self):
        tour = (STATIC / 'field-service-tour.js').read_text(encoding='utf-8')
        lines = re.findall(r"step\('[^']*', '[^']*', '[^']*', '([^']*)'\)", tour)
        self.assertGreaterEqual(len(lines), 15)
        self.assertTrue(any('แผน' in t for t in lines) and any('หมุด' in t for t in lines))
        voice = STATIC / 'field-service-voice'
        manifest = json.loads((voice / 'manifest.json').read_text(encoding='utf-8'))
        for text, file in manifest.items():
            self.assertIn(text, lines, 'stale narration: ' + text[:30])
            self.assertRegex(file, r'^[a-f0-9]{16}\.mp3$')
            self.assertTrue((voice / file).is_file(), file)
        self.assertFalse(any(p.suffix in ('.wav', '.flac', '.m4a') for p in voice.iterdir()))


class FakeGoogle:
    """Records outbound calls instead of contacting Google."""
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, url, body, key, field_mask):
        self.calls.append({'url': url, 'body': body, 'key': key, 'mask': field_mask})
        if self.fail:
            raise field_service_google.ApiError(*self.fail)
        if 'distanceMatrix' in url:
            n = len(body['origins'])
            return [{'originIndex': o, 'destinationIndex': d, 'distanceMeters': 1000 * (o + d + 1), 'duration': f'{60 * (o + d + 2)}s', 'condition': 'ROUTE_EXISTS'}
                    for o in range(n) for d in range(n)]
        legs = 1 + len(body['intermediates'])
        return {'routes': [{'distanceMeters': 5000, 'duration': '900s', 'polyline': {'encodedPolyline': 'abc'},
                            'legs': [{'distanceMeters': 2500, 'duration': '450s'}] * legs}]}


class TestFieldServiceGoogleProxy(unittest.TestCase):
    ENV = {'GOOGLE_ROUTES_API_KEY': 'test-server-key-not-real', 'GOOGLE_MAPS_BROWSER_KEY': 'test-browser-key-not-real',
           'FIELD_SERVICE_GOOGLE_DAILY_CAP': '200'}

    def setUp(self):
        field_service_google.reset_state()
        self.env = patch.dict('os.environ', self.ENV)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        field_service_google.reset_state()

    def call(self, path, query, role='admin', uid=1, fake=None):
        captured = {}
        user = {'user_id': uid, 'role': role} if role else None
        body = field_service_google.handle(path, {'QUERY_STRING': query}, user,
                                           lambda status, headers: captured.update(status=int(status.split()[0]), headers=dict(headers)),
                                           app.FIELD_SERVICE_DEMO_VIEWS, fetch=fake or FakeGoogle())
        return captured['status'], captured['headers'], json.loads(b''.join(body))

    def test_matrix_sends_only_coordinates_traffic_unaware_with_key_in_header(self):
        fake = FakeGoogle()
        status, headers, data = self.call('/field-service/google/matrix', 'ids=HQ,C1,C3', fake=fake)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(len(data['pairs']), 6)
        self.assertEqual(data['pairs']['HQ>C1'], {'km': 2.0, 'minutes': 3})
        sent = fake.calls[0]
        self.assertEqual(sent['body']['routingPreference'], 'TRAFFIC_UNAWARE')
        self.assertNotIn('departureTime', sent['body'])
        self.assertEqual(sent['key'], 'test-server-key-not-real')
        self.assertNotIn('key=', sent['url'])
        text = json.dumps(sent['body'], ensure_ascii=False)
        for private in ('สมมติ', 'บริษัท', '02-000', 'DEMO-'):
            self.assertNotIn(private, text)
        self.assertNotIn('test-server-key-not-real', json.dumps(data))

    def test_route_essentials_limits_polyline_and_cache(self):
        fake = FakeGoogle()
        status, _, data = self.call('/field-service/google/route', 'seq=HQ,C1,C3,C2,HQ', fake=fake)
        self.assertEqual(status, 200)
        self.assertEqual(len(data['legs']), 4)
        self.assertEqual(data['polyline'], 'abc')
        body = fake.calls[0]['body']
        self.assertEqual(body['routingPreference'], 'TRAFFIC_UNAWARE')
        self.assertLessEqual(len(body['intermediates']), 10)
        self.assertNotIn('optimizeWaypointOrder', body)
        self.assertNotIn('traffic', fake.calls[0]['mask'].lower())
        status, _, again = self.call('/field-service/google/route', 'seq=HQ,C1,C3,C2,HQ', fake=fake)
        self.assertTrue(again['cached'])
        self.assertEqual(len(fake.calls), 1)                 # served from cache, no second billable call

    def test_rejects_unknown_points_duplicates_roles_and_missing_key(self):
        for q in ('ids=HQ,C9', 'ids=HQ,HQ', 'ids=HQ', 'ids=' + ','.join(['HQ', 'C1', "C1"])):
            self.assertEqual(self.call('/field-service/google/matrix', q)[0], 400, q)
        self.assertEqual(self.call('/field-service/google/route', 'seq=HQ,lat:13,100')[0], 400)
        self.assertEqual(self.call('/field-service/google/matrix', 'ids=HQ,C1', role=None)[0], 401)
        for role in ('customer',):
            self.assertEqual(self.call('/field-service/google/matrix', 'ids=HQ,C1', role=role)[0], 403)
        self.assertEqual(self.call('/field-service/google/other', '')[0], 404)
        with patch.dict('os.environ', {'GOOGLE_ROUTES_API_KEY': ''}):
            self.assertEqual(self.call('/field-service/google/matrix', 'ids=HQ,C1')[2], {'ok': False, 'error': 'not_configured'})

    def test_rate_limit_daily_cap_and_sanitized_upstream_errors(self):
        import itertools
        seqs = [','.join(p) for p in itertools.permutations(['HQ', 'C1', 'C2', 'C3', 'C4', 'C5'], 2)][:field_service_google.USER_RATE_PER_MIN]
        for seq in seqs:                                       # distinct trips -> each is a billable call
            self.assertEqual(self.call('/field-service/google/route', 'seq=' + seq)[0], 200)
        self.assertEqual(self.call('/field-service/google/matrix', 'ids=HQ,C1,C2,C3')[0], 429)
        field_service_google.reset_state()
        with patch.dict('os.environ', {'FIELD_SERVICE_GOOGLE_DAILY_CAP': '1'}):
            self.assertEqual(self.call('/field-service/google/matrix', 'ids=HQ,C1')[0], 200)
            status, _, data = self.call('/field-service/google/matrix', 'ids=HQ,C2', uid=2)
            self.assertEqual((status, data['error']), (429, 'daily_cap_reached'))
        field_service_google.reset_state()
        status, _, data = self.call('/field-service/google/matrix', 'ids=HQ,C1', fake=FakeGoogle(fail=(502, 'upstream_error')))
        self.assertEqual((status, data), (502, {'ok': False, 'error': 'upstream_error'}))

    def test_page_config_exposes_browser_key_only(self):
        cfg = field_service_google.page_config()
        self.assertEqual(cfg['mapsKey'], 'test-browser-key-not-real')
        self.assertTrue(cfg['routing'])
        self.assertNotIn('test-server-key-not-real', json.dumps(cfg))
        with patch.dict('os.environ', {'FIELD_SERVICE_HQ_LATLNG': '13.8,100.7'}):
            self.assertEqual(field_service_google.page_config()['points']['HQ'], {'lat': 13.8, 'lng': 100.7})
        with patch.dict('os.environ', {'FIELD_SERVICE_HQ_LATLNG': 'nonsense'}):
            self.assertEqual(field_service_google.page_config()['points']['HQ']['lat'], 13.827)
