import os
from web.app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=os.environ.get('FLASK_DEBUG', '0') == '1')
