from datetime import date, datetime, timezone
from decimal import Decimal
import logging
import uuid
import pyodbc
from flask import Flask, g, jsonify, render_template
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException
from .config import settings
from .errors import ApiError
from .db import translate_error
from .security import protect_request

class JSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(obj):
        if isinstance(obj, datetime):
            return obj.replace(tzinfo=timezone.utc).isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return str(obj)  # preserve money precision over JSON
        return DefaultJSONProvider.default(obj)

def create_app(test_config=None):
    app = Flask(__name__)
    app.json = JSONProvider(app)
    app.config.update(settings())
    if test_config:
        app.config.update(test_config)

    @app.before_request
    def before():
        g.request_id = uuid.uuid4().hex[:12]
        protect_request()

    @app.after_request
    def headers(response):
        response.headers.update({'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
            'Referrer-Policy': 'same-origin', 'Cache-Control': 'no-store',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"})
        response.headers['X-Request-ID'] = getattr(g, 'request_id', '')
        return response

    @app.errorhandler(ApiError)
    def api_error(error):
        return jsonify(error={'code': error.code, 'message': error.message, 'request_id': getattr(g, 'request_id', '')}), error.status

    @app.errorhandler(pyodbc.Error)
    def db_error(error):
        translated = translate_error(error)
        # Do not log connection strings, driver error bodies or passenger payloads.
        app.logger.warning('Database failure request=%s code=%s', g.request_id, translated.code)
        return api_error(translated)

    @app.errorhandler(HTTPException)
    def http_error(error):
        return api_error(ApiError('Yêu cầu không hợp lệ hoặc tài nguyên không tồn tại.', error.code, 'HTTP_ERROR'))

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.error('Unhandled failure request=%s type=%s', getattr(g, 'request_id', ''), type(error).__name__)
        return api_error(ApiError('Có lỗi hệ thống. Vui lòng thử lại sau.', 500, 'INTERNAL_ERROR'))

    @app.get('/')
    def index():
        return render_template('index.html')

    from .routes.auth import bp as auth
    from .routes.flights import bp as flights
    from .routes.bookings import bp as bookings
    from .routes.admin import bp as admin
    for bp in (auth, flights, bookings, admin):
        app.register_blueprint(bp)
    return app
