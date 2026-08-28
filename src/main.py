import os
from web.app import app

if __name__ == "__main__":
    _allow_network = os.environ.get('KUBESEC_ALLOW_NETWORK_BIND', '').lower() in ('1', 'true', 'yes', 'on')
    host = "0.0.0.0" if _allow_network else "127.0.0.1"
    app.run(host=host, port=8080, debug=os.environ.get('FLASK_DEBUG', '0') == '1')
