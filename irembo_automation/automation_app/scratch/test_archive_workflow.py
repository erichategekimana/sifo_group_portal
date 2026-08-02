import os
import sys
import django
from django.test import RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage

sys.path.insert(0, '/home/eric/working_space/irembo_bot/irembo_automation')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'irembo_project.settings')
django.setup()
from django.conf import settings
settings.ALLOWED_HOSTS = ['*']
from django.test.utils import setup_test_environment
setup_test_environment()

from automation_app.models import ClientApplication, Teacher
from automation_app.views import (
    dashboard, archived_dashboard, archive_application, unarchive_application,
    bulk_action, start_automation
)

from django.test import Client

def run_tests():
    print("--- Starting Archive Workflow Unit Tests ---")
    client = Client()

    # Create dummy teacher & test application
    teacher = Teacher.objects.create(name="Test Teacher Archive")
    app1 = ClientApplication.objects.create(
        first_name="ArchiveTest",
        last_name="UserOne",
        national_id="1199580099998888",
        birth_date="1995-05-05",
        phone_number="0788998877",
        category="B",
        teacher=teacher
    )

    app2 = ClientApplication.objects.create(
        first_name="ArchiveTest",
        last_name="UserTwo",
        national_id="1199580099998889",
        birth_date="1996-06-06",
        phone_number="0788998876",
        category="C"
    )

    try:
        # Test 1: Verify new apps default to is_archived=False
        assert app1.is_archived is False, "app1 should default to is_archived=False"
        assert app2.is_archived is False, "app2 should default to is_archived=False"
        print("[PASS] Test 1: New applications default to is_archived=False.")

        # Test 2: Archive app1 via single view
        resp = client.post(f'/archive/{app1.id}/')
        assert resp.status_code == 302, "archive_application should redirect"
        app1.refresh_from_db()
        assert app1.is_archived is True, "app1 should be archived (is_archived=True)"
        print("[PASS] Test 2: Single archive_application succeeded.")

        # Test 3: Verify active dashboard excludes app1 and includes app2
        resp = client.get('/')
        if resp.status_code != 200:
            print("Test 3 Status Code:", resp.status_code, getattr(resp, 'url', ''))
        assert resp.context is not None, f"Response context is None! Status: {resp.status_code}"
        applications_in_dash = resp.context['applications']
        app_ids_in_dash = [a.id for a in applications_in_dash]
        assert app1.id not in app_ids_in_dash, "app1 should NOT be in active dashboard"
        assert app2.id in app_ids_in_dash, "app2 SHOULD be in active dashboard"
        print("[PASS] Test 3: Active dashboard excludes archived applications.")

        # Test 4: Verify archived_dashboard contains app1 and excludes app2
        resp = client.get('/archived/', HTTP_HOST='localhost:8000')
        applications_in_archived = resp.context['applications']
        app_ids_in_archived = [a.id for a in applications_in_archived]
        assert app1.id in app_ids_in_archived, "app1 SHOULD be in archived dashboard"
        assert app2.id not in app_ids_in_archived, "app2 should NOT be in archived dashboard"
        print("[PASS] Test 4: Archived dashboard includes only archived applications.")

        # Test 5: Verify start_automation blocks archived app1
        resp = client.get(f'/start/{app1.id}/')
        assert resp.url == '/archived/', f"start_automation on archived app should redirect to /archived/, got {resp.url}"
        print("[PASS] Test 5: Automation ignition blocked for archived application.")

        # Test 6: Unarchive app1
        resp = client.post(f'/unarchive/{app1.id}/')
        assert resp.status_code == 302, "unarchive_application should redirect"
        app1.refresh_from_db()
        assert app1.is_archived is False, "app1 should be restored (is_archived=False)"
        print("[PASS] Test 6: Single unarchive_application succeeded.")

        # Test 7: Bulk archive action on app1 & app2
        resp = client.post('/bulk-action/', {'action': 'archive', 'selected_ids': [str(app1.id), str(app2.id)]})
        assert resp.status_code == 302, "bulk_action should redirect"
        app1.refresh_from_db()
        app2.refresh_from_db()
        assert app1.is_archived is True, "app1 bulk archive failed"
        assert app2.is_archived is True, "app2 bulk archive failed"
        print("[PASS] Test 7: Bulk archive action succeeded.")

        # Test 8: Bulk unarchive action
        resp = client.post('/bulk-action/', {'action': 'unarchive', 'selected_ids': [str(app1.id), str(app2.id)]})
        assert resp.status_code == 302, "bulk_action should redirect"
        app1.refresh_from_db()
        app2.refresh_from_db()
        assert app1.is_archived is False, "app1 bulk unarchive failed"
        assert app2.is_archived is False, "app2 bulk unarchive failed"
        print("[PASS] Test 8: Bulk unarchive action succeeded.")

        print("\n=== ALL ARCHIVE WORKFLOW TESTS PASSED 100% ===")

    finally:
        app1.delete()
        app2.delete()
        teacher.delete()

if __name__ == '__main__':
    run_tests()
