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


class TestRetiredFieldServiceExample(fixtures.ApiTestCase):
    def setUp(self):
        super().setUp();self.tokens=[]
        self.mutate("INSERT INTO Users(user_id,username,password,role,name,is_active) VALUES(99,'example-admin','unused','admin','Admin',1)")
    def tearDown(self):
        for token in self.tokens:app.SESSIONS.pop(token,None)
        super().tearDown()
    def test_legacy_example_redirects_without_writes(self):
        before=sqlite3.connect(self.path).execute('SELECT COUNT(*) FROM Field_Service_Jobs').fetchone()[0]
        status,headers,_=office.TestVirtualOffice.request(self,'/field-service/demo',user_id=99)
        self.assertEqual(status,302);self.assertEqual(headers['Location'],'/field-service')
        self.assertEqual(sqlite3.connect(self.path).execute('SELECT COUNT(*) FROM Field_Service_Jobs').fetchone()[0],before)
    def test_no_sample_ui_or_fictional_google_routes_are_served(self):
        for url in ('/static/field-service-data.js','/static/field-service-demo.js','/static/field-service-tour.js','/field-service/google/route'):
            self.assertEqual(office.TestVirtualOffice.request(self,url,user_id=99)[0],404,url)
        template=(ROOT/'templates/field_service_live.html').read_text()
        self.assertNotIn('field-service-data.js',template)
        self.assertNotIn('/field-service/demo',template)


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
                                           {role:['route'] for role in ('admin','manager','technician_lead','technician','sales')}, fetch=fake or FakeGoogle())
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
