from flask import Blueprint

bp_security = Blueprint('security', __name__)

# Route dekoratörlerini tetiklemek için alt-modülleri import et
from web.blueprints.security import scanning  # noqa: F401, E402
from web.blueprints.security import analysis  # noqa: F401, E402
