# automation_app/automation_engine/config.py
import os

USER_DATA_DIR_PATH = os.path.abspath(os.path.join(os.getcwd(), "chrome_profile"))
SESSION_STATE_PATH = os.path.abspath(os.path.join(os.getcwd(), "session_state.json"))

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
DEFAULT_DEVICE_SCALE_FACTOR = 1
DEFAULT_IS_MOBILE = False
DEFAULT_HAS_TOUCH = False
DEFAULT_LOCALE = "en-US"
DEFAULT_TIMEZONE = "Africa/Kigali"