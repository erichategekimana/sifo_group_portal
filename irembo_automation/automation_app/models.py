from django.db import models
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.utils import timezone

# ---------------------------------------------------------------------------
# Validators (Data Integrity & Security at Entry Point)
# ---------------------------------------------------------------------------

# Enforces exactly 16 digits for Rwandan National ID
national_id_validator = RegexValidator(
    regex=r'^\d{16}$',
    message="National ID must be exactly 16 digits and contain only numbers."
)

# Enforces exactly 10 digits for Rwandan mobile phone numbers (e.g., 0788123456)
rwanda_phone_validator = RegexValidator(
    regex=r'^07[2389]\d{7}$',
    message="Phone number must be exactly 10 digits and start with 07 followed by 8 digits."
)


class ClientApplication(models.Model):
    class ProcessStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending Slot Check'
        PROCESSING = 'PROCESSING', 'Filling Form on Irembo'
        FINALIZING = 'FINALIZING', 'Slot Secured — Submitting Application'
        SUCCESS = 'SUCCESS', 'Registration Completed Successfully'
        FAILED = 'FAILED', 'Process Failed/Aborted'
        CANCELED = 'CANCELED', 'Process Canceled by User'
        MANUAL_REVIEW_NEEDED = 'MANUAL_REVIEW_NEEDED', 'Manual Review Required'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PAID = 'PAID', 'Paid'
        EXPIRED = 'EXPIRED', 'Payment Code Expired'

    # Personal Information (with robust validators)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    national_id = models.CharField(
        max_length=16, 
        unique=True, 
        validators=[national_id_validator],
        help_text="16-digit Rwandan National ID"
    )
    birth_date = models.DateField()
    phone_number = models.CharField(
        max_length=15, 
        validators=[rwanda_phone_validator],
        help_text="Primary phone linked to Irembo profile"
    )
    email = models.EmailField(blank=True, null=True)
    
    # -----------------------------------------------------------------------
    # UPDATED: Separated Licensing & Application Schema
    # -----------------------------------------------------------------------
    category = models.CharField(
        max_length=10, 
        help_text="Target driving category selection (e.g., A, B, B2, C1, D)"
    )
    provisional_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Provisional license string. Required for new Definitive applications; leave blank for Category Upgrades."
    )

    # Automation State Machine
    status = models.CharField(
        max_length=20,
        choices=ProcessStatus.choices,
        default=ProcessStatus.PENDING
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID
    )
    
    # Handshake & Output Fields
    billing_number = models.CharField(max_length=50, blank=True, null=True)
    application_number = models.CharField(max_length=50, blank=True, null=True)
    failure_reason = models.CharField(max_length=255, blank=True, null=True, help_text="Stored Kinyarwanda reason code for automation failure")
    comment = models.TextField(blank=True, null=True, help_text="User comments about this application")
    retry_attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, null=True)
    log_output = models.TextField(blank=True, null=True, help_text="Detailed execution logs for the application task")
    user_response = models.CharField(max_length=50, blank=True, null=True, help_text="Temporary field for user interaction during process")

    # Metadata Audit Trail
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Client Application"
        verbose_name_plural = "Client Applications"
        
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['national_id']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.national_id}) - {self.status}"

    # ---------------------------------------------------------------------------
    # Business Logic Guardrails (Model Validation)
    # ---------------------------------------------------------------------------
    @property
    def is_upgrade_application(self):
        """
        Helper property: Returns True if the user is upgrading an existing definitive license.
        """
        return not bool(self.provisional_number)

    def clean(self):
        """
        Custom validation rules to maintain business logic integrity before saving.
        """
        super().clean()
        
        # 1. Age Restriction: Ensure the client is at least 18 years old to apply
        today = timezone.now().date()
        age = today.year - self.birth_date.year - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        if age < 18:
            raise ValidationError({'birth_date': "Client must be at least 18 years old to register for a driving license."})

        # Provisional number required for definitive license applications
        if not self.is_upgrade_application and not self.provisional_number:
            pass  # Handled at the engine level with clear error messages

class ApplicationRunHistory(models.Model):
    """
    Records the outcome of each automation attempt for a given application.
    This prevents data loss if an application is re-run (e.g., if a payment code expires).
    """
    application = models.ForeignKey(ClientApplication, on_delete=models.CASCADE, related_name='run_history')
    run_date = models.DateTimeField(auto_now_add=True)
    
    # Snapshot of the state when the run completed
    status = models.CharField(max_length=20)
    payment_status = models.CharField(max_length=20)
    billing_number = models.CharField(max_length=50, blank=True, null=True)
    failure_reason = models.CharField(max_length=255, blank=True, null=True)
    log_output = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-run_date']
        verbose_name = "Application Run History"
        verbose_name_plural = "Application Run Histories"

    def __str__(self):
        return f"Run for {self.application.national_id} at {self.run_date.strftime('%Y-%m-%d %H:%M:%S')} - {self.status}"

class SystemActivityLog(models.Model):
    """
    Records a high-level discrete event in the system (creation, edit, delete, bulk action, engine results).
    """
    class ActionType(models.TextChoices):
        CREATE = 'CREATE', 'Application Created'
        EDIT = 'EDIT', 'Application Updated'
        DELETE = 'DELETE', 'Application Deleted'
        BULK = 'BULK', 'Bulk Action'
        ENGINE = 'ENGINE', 'Automation Engine'

    action_type = models.CharField(max_length=20, choices=ActionType.choices)
    description = models.TextField()
    application_name = models.CharField(max_length=255, blank=True, null=True)
    application_id = models.IntegerField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "System Activity Log"
        verbose_name_plural = "System Activity Logs"

    def __str__(self):
        return f"[{self.action_type}] {self.description[:50]}"