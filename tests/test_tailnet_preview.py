"""The proxy boundary cannot bypass actor selection, CSRF or network isolation."""
import json
import unittest

from flask import Flask, jsonify, request, session
from werkzeug.test import Client
from werkzeug.wrappers import Response

from contextledger.tailnet_preview import TailnetPreview


class TailnetPreviewTests(unittest.TestCase):
    def setUp(self):
        self.public = 'https://demo.tailtest.ts.net:8444'
        self.local = 'http://127.0.0.1:17862'
        self.app = Flask(__name__)
        self.app.secret_key = 'fixture-only'
        self.app.config['SESSION_COOKIE_SECURE'] = True
        @self.app.route('/', methods=['GET', 'POST'])
        def endpoint():
            session['preview'] = True
            return jsonify(host=request.host_url.rstrip('/'), origin=request.headers.get('Origin'),
                           login=request.headers.get('Tailscale-User-Login'), body=request.get_json(silent=True),
                           csrf=request.headers.get('X-CSRF-Token'))
        self.client = Client(TailnetPreview(self.app, public_url=self.public, local_url=self.local,
                             allowed_logins=['owner@example.test']), Response)
        self.headers = {'Tailscale-User-Login': 'owner@example.test', 'Origin': self.public}

    def call(self, **kwargs):
        return self.client.open('/', base_url=self.public, headers=kwargs.pop('headers', self.headers),
                                environ_overrides=kwargs.pop('environ_overrides', {'REMOTE_ADDR': '127.0.0.1'}), **kwargs)

    def test_trusted_serve_preserves_body_csrf_and_secure_session(self):
        response = self.call(method='POST', json={'user_id': 'fixed-demo-id'},
                             headers=self.headers | {'X-CSRF-Token': 'existing-csrf'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['host'], self.local)
        self.assertEqual(data['origin'], self.local)
        self.assertEqual(data['body'], {'user_id': 'fixed-demo-id'})
        self.assertEqual(data['csrf'], 'existing-csrf')
        self.assertIsNone(data['login'])
        self.assertIn('Secure;', response.headers['Set-Cookie'])
        self.assertIn('HttpOnly;', response.headers['Set-Cookie'])

    def test_untrusted_peer_missing_identity_or_other_user_cannot_enter(self):
        for overrides, headers in [({'REMOTE_ADDR': '100.64.0.1'}, self.headers),
                                    ({'REMOTE_ADDR': '127.0.0.1'}, {}),
                                    ({'REMOTE_ADDR': '127.0.0.1'}, self.headers | {'Tailscale-User-Login': 'other@example.test'})]:
            with self.subTest(headers=headers):
                self.assertEqual(self.call(environ_overrides=overrides, headers=headers).status_code, 403)

    def test_cross_origin_or_missing_post_origin_cannot_be_rewritten(self):
        for origin in [None, 'https://other.test', self.local]:
            headers = {'Tailscale-User-Login': 'owner@example.test'}
            if origin is not None:
                headers['Origin'] = origin
            self.assertEqual(self.call(method='POST', headers=headers).status_code, 403)
        self.assertEqual(self.call(headers=self.headers | {'Origin': 'https://other.test'}).status_code, 403)

    def test_wrong_host_and_non_tailnet_configuration_are_rejected(self):
        self.assertEqual(self.call(headers=self.headers | {'Host': 'other.tailtest.ts.net:8444'}).status_code, 403)
        for public in ['http://demo.tailtest.ts.net', 'https://public.example.test', self.public + '/path']:
            with self.subTest(public=public), self.assertRaises(ValueError):
                TailnetPreview(self.app, public_url=public, local_url=self.local, allowed_logins=['owner@example.test'])
        with self.assertRaises(ValueError):
            TailnetPreview(self.app, public_url=self.public, local_url=self.local, allowed_logins=[])
