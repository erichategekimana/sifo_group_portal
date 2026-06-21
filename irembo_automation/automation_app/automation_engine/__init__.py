# automation_app/automation_engine/__init__.py
from .browser import BrowserMixin
from .interceptors import InterceptorMixin
from .navigation import NavigationMixin
from .identity import IdentityMixin
from .selectors import SelectorsMixin
from .polling import PollingMixin
from .final import FinalizationMixin
from .utils import UtilsMixin
from .validator import ValidatorMixin
from .error_detector import ErrorDetectionMixin

class IremboAutomationEngine(
    BrowserMixin,
    InterceptorMixin,
    NavigationMixin,
    IdentityMixin,
    SelectorsMixin,
    PollingMixin,
    FinalizationMixin,
    UtilsMixin,
    ValidatorMixin,
    ErrorDetectionMixin
):
    def __init__(self, booking_record=None):
        self.user_data_dir = None
        from .config import USER_DATA_DIR_PATH
        self.user_data_dir = USER_DATA_DIR_PATH
        self.browser = None
        self.context = None
        self.page = None
        self.booking_record = booking_record