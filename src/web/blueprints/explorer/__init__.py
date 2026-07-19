from flask import Blueprint

bp_explorer = Blueprint('explorer', __name__)

# Route dekoratörlerini tetiklemek için alt-modülleri import et
from web.blueprints.explorer import core        # noqa: F401, E402
from web.blueprints.explorer import pods        # noqa: F401, E402
from web.blueprints.explorer import controllers # noqa: F401, E402
from web.blueprints.explorer import network     # noqa: F401, E402
from web.blueprints.explorer import storage     # noqa: F401, E402
from web.blueprints.explorer import config      # noqa: F401, E402
from web.blueprints.explorer import cluster     # noqa: F401, E402
from web.blueprints.explorer import scaling     # noqa: F401, E402
