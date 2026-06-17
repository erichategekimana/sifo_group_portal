# automation_app/automation_engine/__init__.py
from .browser import BrowserMixin
from .interceptors import InterceptorMixin
from .navigation import NavigationMixin
from .identity import IdentityMixin
from .selectors import SelectorsMixin
from .polling import PollingMixin
from .final import FinalizationMixin
from .utils import UtilsMixin

class IremboAutomationEngine(
    BrowserMixin,
    InterceptorMixin,
    NavigationMixin,
    IdentityMixin,
    SelectorsMixin,
    PollingMixin,
    FinalizationMixin,
    UtilsMixin,
):
    def __init__(self, booking_record=None):
        self.state_file = None  # Will be set in browser init? Or we can set here using config
        # We'll set state_file in __init__ using config.STATE_FILE_PATH
        # But config is not imported yet; we'll import it.
        from .config import STATE_FILE_PATH
        self.state_file = STATE_FILE_PATH
        self.browser = None
        self.context = None
        self.page = None
        self.booking_record = booking_record