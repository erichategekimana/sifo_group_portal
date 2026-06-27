# automation_app/automation_engine/error_detector.py
from .utils import run_in_db_thread

class ErrorDetectionMixin:
    # Map error texts (exact or partial) to Kinyarwanda reason codes
    ERROR_MESSAGES = [
        ("Umuturage uhujwe niyi nyandiko asanzwe afite uruhushya.", "ASANZWE_AFITE_URUHUSHYA"),
        ("Uruhushya rwanyu rw'agateganyo rwatakaje agaciro", "RWATAKAJE_AGACIRO"),
        ("Nomero ya Perimi yabuze.", "PERIMI_YABUZE"),
        ("Mwamaze kwiyandikisha ku kizamini.", "YAMAZ_KWIYANDIKISHA"),
        ("Ntidushoboye kubona umwirondoro wanyu muri sisiteme ya NIDA.", "NIDA_NTIBONETSE"),
        ("Ibisobanuro byatanzwe ntibihuye nibyo twahawe na NIDA", "IBISOBANURO_NTIBIHUYE"),
        ("Mutwihanginira, umwirondoro wanyu ntushoboye kuboneka nonaha. Mwongere mukanya.", "UMWIRONDORO_NTUBONETSE"),
        ("Ntabwo wemerewe iyi serivisi.", "NTABWO_WEMEREWE"),
    ]

    def _scan_for_errors(self):
        """
        Scan the current page for any known error messages.
        Returns: (found, reason_code, raw_text)
        """
        try:
            # Get all visible text from common error containers, including the verification modal
            error_elements = self.page.locator('.alert-fill-danger, .alert-danger, .text-danger, mat-error, app-user-messages, .error-message, mat-dialog-container small.text-danger')
            for elem in error_elements.all():
                if elem.is_visible():
                    text = elem.inner_text().strip()
                    text_lower = text.lower()
                    for err_msg, reason in self.ERROR_MESSAGES:
                        if err_msg.lower() in text_lower:
                            return True, reason, text
            
            # Also check the whole page body as fallback, using case-insensitive search
            body_text = self.page.locator('body').inner_text().lower()
            for err_msg, reason in self.ERROR_MESSAGES:
                if err_msg.lower() in body_text:
                    return True, reason, err_msg
                    
            # Ultimate fallback: check raw HTML content
            raw_html = self.page.content().lower()
            for err_msg, reason in self.ERROR_MESSAGES:
                if err_msg.lower() in raw_html:
                    return True, reason, err_msg
                    
        except Exception as e:
            print(f"[ErrorDetector] Scan failed: {e}")
            
        return False, None, None

    def capture_error_if_any(self):
        """
        Check for errors; if found, update DB with reason and raise ValueError.
        """
        found, reason, raw = self._scan_for_errors()
        if found and self.booking_record:
            print(f"[ErrorDetector] Error detected: {reason} - {raw}")
            # Store reason in failure_reason
            record = self.booking_record
            def _update():
                record.failure_reason = reason
                record.status = 'FAILED'
                record.save(update_fields=["failure_reason", "status"])
            run_in_db_thread(_update)
            raise ValueError(f"Irembo Error: {reason} - {raw}")
        return found
