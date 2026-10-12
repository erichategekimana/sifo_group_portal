# automation_app/automation_engine/locations.py
"""
Location & Exam Site Management Module.

Provides object-oriented strategies for evaluating exam centers across different
districts in Rwanda.
- Kicukiro: Supports multiple sites ("BUSANZA AUTOMATED CENTER" vs "KICUKIRO - BUSANZA SITE (KIC)")
- All other districts: Supports standard single-center sites automatically.
"""

from abc import ABC, abstractmethod


class LocationStrategy(ABC):
    """
    Abstract base strategy defining how a district and its exam centers
    are evaluated and matched during slot polling.
    """

    def __init__(self, district: str, working_site: str | None = None):
        self.district = (district or "Kicukiro").strip()
        self.working_site = (working_site or "").strip()

    @abstractmethod
    def matches_center(self, center_text: str) -> bool:
        """
        Determines whether the given center description string matches
        the desired working site for this applicant.
        """
        pass

    @abstractmethod
    def get_target_name(self) -> str:
        """
        Returns a human-readable name of the target site for logging and telemetry.
        """
        pass

    def get_refresh_district(self) -> str:
        """
        Returns an alternate district used to toggle the Angular dropdown
        to trigger a natural refresh on Irembo.
        """
        if self.district.strip().lower() == "gasabo":
            return "Kicukiro"
        return "Gasabo"


class KicukiroLocationStrategy(LocationStrategy):
    """
    Strategy for Kicukiro district, which uniquely contains two distinct centers:
    1. 'BUSANZA AUTOMATED CENTER' (Automated test)
    2. 'KICUKIRO - BUSANZA SITE (KIC)' (Manual test)
    """

    def __init__(self, working_site: str | None = None):
        super().__init__(district="Kicukiro", working_site=working_site)

    def is_manual_site(self) -> bool:
        site_upper = self.working_site.upper()
        return "SITE (KIC)" in site_upper or "BUSANZA SITE" in site_upper

    def matches_center(self, center_text: str) -> bool:
        center_upper = (center_text or "").upper()

        if self.is_manual_site():
            # Manual site requires 'SITE (KIC)' or 'BUSANZA SITE', and must NOT be the automated center
            is_manual = "SITE (KIC)" in center_upper or "BUSANZA SITE" in center_upper
            is_auto = "AUTOMATED" in center_upper or "AUTOMATIQUE" in center_upper or "AUTOMATIS" in center_upper
            return is_manual and not is_auto
        else:
            # Default / Automated center: requires 'AUTOMATED' or 'AUTOMATIQUE' and excludes the manual site
            is_auto = "AUTOMATED" in center_upper or "AUTOMATIQUE" in center_upper or "AUTOMATIS" in center_upper
            is_manual = "SITE (KIC)" in center_upper or "BUSANZA SITE" in center_upper
            return is_auto and not is_manual

    def get_target_name(self) -> str:
        if self.is_manual_site():
            return "KICUKIRO - BUSANZA SITE (KIC)"
        return "BUSANZA AUTOMATED CENTER"


class StandardDistrictLocationStrategy(LocationStrategy):
    """
    Strategy for all standard districts in Rwanda (outside Kicukiro)
    which operate a single official examination center.
    Accepts any active, valid appointment slot for that district.
    """

    def matches_center(self, center_text: str) -> bool:
        # For standard districts, any active center presented by Irembo for this district is valid
        return bool(center_text and center_text.strip())

    def get_target_name(self) -> str:
        if self.working_site:
            return f"{self.district} ({self.working_site})"
        return f"{self.district} Center"


def get_location_strategy(district: str | None, working_site: str | None = None) -> LocationStrategy:
    """
    Factory function returning the appropriate LocationStrategy
    based on the applicant's district and selected working site.
    """
    dist_clean = (district or "Kicukiro").strip()

    if dist_clean.lower() == "kicukiro":
        return KicukiroLocationStrategy(working_site=working_site)

    return StandardDistrictLocationStrategy(district=dist_clean, working_site=working_site)
