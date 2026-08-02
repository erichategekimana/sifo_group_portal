# automation_app/automation_engine/error_detector.py
from .utils import run_in_db_thread

class ErrorDetectionMixin:
    # Map error texts (exact or partial, lowercased) to Kinyarwanda reason codes
    ERROR_MESSAGES = [
        ("asanzwe afite uruhushya", "ASANZWE_AFITE_URUHUSHYA"),
        ("rwatakaje agaciro", "RWATAKAJE_AGACIRO"),
        ("nomero ya perimi yabuze", "PERIMI_YABUZE"),
        ("nimero ya permis yabuze", "PERIMI_YABUZE"),
        ("perimi yabuze", "PERIMI_YABUZE"),
        ("permis yabuze", "PERIMI_YABUZE"),
        ("mwamaze kwiyandikisha", "YAMAZ_KWIYANDIKISHA"),
        ("yamaze kwiyandikisha", "YAMAZ_KWIYANDIKISHA"),
        ("ntidushoboye kubona umwirondoro wanyu muri sisiteme ya nida", "NIDA_NTIBONETSE"),
        ("umwirondoro wanyu ntushoboye kuboneka", "UMWIRONDORO_NTUBONETSE"),
        ("ibisobanuro byatanzwe ntibihuye", "IBISOBANURO_NTIBIHUYE"),
        ("ntabwo wemerewe iyi serivisi", "NTABWO_WEMEREWE"),
        ("bileyi nomero", "BILEYI_IRAKORESHEJWE"),
        ("ntabwo mufite uburenganzira", "NTA_BURENGANZIRA"),
    ]

    # Whitelist of informational announcements, service updates, or form validation placeholders to ignore
    IGNORED_MESSAGES = [
        "amakuru mashya",
        "itangazo",
        "automatique",
        "uyu mwanya ni ngombwa",
    ]

    def _scan_for_errors(self):
        """
        Scan the current page for any known error messages or visible danger/alert banners.
        Returns: (found, reason_code, raw_text)
        """
        try:
            # Expand error containers to catch 100% of visible error alerts, toasts, and validation banners
            error_elements = self.page.locator(
                '.alert-fill-danger, .alert-fill-warning, .alert-danger, .alert-warning, '
                '.text-danger, mat-error, app-user-messages, div[role="alert"], '
                '.error-message, mat-dialog-container small.text-danger, .toast-error, .notification-error'
            )
            for elem in error_elements.all():
                try:
                    if elem.is_visible():
                        text = elem.inner_text().strip()
                        if not text:
                            continue
                        text_lower = text.lower()

                        # 0. Check against whitelisted informational announcements or non-error placeholders
                        if any(ignored in text_lower for ignored in self.IGNORED_MESSAGES):
                            continue

                        # 1. Check against known error messages dictionary
                        for err_msg, reason in self.ERROR_MESSAGES:
                            if err_msg in text_lower:
                                return True, reason, text
                        
                        # 2. Universal Alert Capture fallback:
                        # If a danger/alert banner has visible text but isn't in our dictionary,
                        # ignore generic validation placeholders like "*" unless it's an actual banner
                        if len(text) > 5 and "*" != text:
                            return True, "IKOSA_RITAZWI", text
                except Exception:
                    continue
            
            # Also check the whole page body as fallback for known errors
            body_text = self.page.locator('body').inner_text().lower()
            for err_msg, reason in self.ERROR_MESSAGES:
                if err_msg in body_text:
                    return True, reason, err_msg
                    
            # Ultimate fallback: check raw HTML content for known errors
            raw_html = self.page.content().lower()
            for err_msg, reason in self.ERROR_MESSAGES:
                if err_msg in raw_html:
                    return True, reason, err_msg
                    
        except Exception as e:
            print(f"[ErrorDetector] Scan failed: {e}")
            
        return False, None, None

    def capture_error_if_any(self):
        """
        Check for errors; if found, update DB with reason, save full error text, and raise ValueError.
        """
        found, reason, raw = self._scan_for_errors()
        if found and self.booking_record:
            print(f"[ErrorDetector] Error detected: {reason} - {raw}")
            # Store reason in failure_reason, full string in last_error, and append banner to log_output
            record = self.booking_record
            def _update():
                record.failure_reason = reason
                record.last_error = raw
                error_banner = f"\n=== [IKOSA RYABONETSE / ERROR DETECTED] ===\nReason Code: {reason}\nMessage: {raw}\n============================================\n"
                record.log_output = (record.log_output or "") + error_banner
                record.status = 'FAILED'
                record.save(update_fields=["failure_reason", "last_error", "log_output", "status"])
            run_in_db_thread(_update)
            raise ValueError(f"Irembo Error: {reason} - {raw}")
        return found
