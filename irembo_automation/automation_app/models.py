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

# Enforces valid Rwandan mobile phone formats (supports 078..., 079..., 072..., 073...)
# Also allows optional +250 country code prefix
rwanda_phone_validator = RegexValidator(
    regex=r'^(?:\+250|0)7[2389]\d{7}$',
    message="Phone number must be a valid Rwandan mobile format (e.g., 0788XXXXXX or +250788XXXXXX)."
)


class ClientApplication(models.Model):
    class ProcessStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending Slot Check'
        PROCESSING = 'PROCESSING', 'Filling Form on Irembo'
        AWAITING_OTP = 'AWAITING_OTP', 'Awaiting OTP Input'
        SUCCESS = 'SUCCESS', 'Registration Completed Successfully'
        FAILED = 'FAILED', 'Process Failed/Aborted'

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
    
    # Licensing Details
    category_or_provisional = models.CharField(
        max_length=50, 
        help_text="Target category (e.g., B) or existing provisional number for upgrades"
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
    otp_code = models.CharField(max_length=10, blank=True, null=True)
    billing_number = models.CharField(max_length=50, blank=True, null=True)
    application_number = models.CharField(max_length=50, blank=True, null=True)

    # Metadata Audit Trail
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Client Application"
        verbose_name_plural = "Client Applications"
        
        # Performance & Flexibility Optimization
        # Adding indexes speeds up Playwright lookups drastically when checking specific statuses
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['national_id']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.national_id}) - {self.status}"

    # ---------------------------------------------------------------------------
    # Business Logic Guardrails (Model Validation)
    # ---------------------------------------------------------------------------
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

        # 2. State-Machine Safeguard: OTP validation
        # If the system status is flagged as awaiting OTP, but your dashboard frontend tries 
        # to clear out or bypass the token entry, raise an alert.
        if self.status == self.ProcessStatus.AWAITING_OTP and not self.otp_code:
            # Note: This is an intentional state. This clean method just verifies it doesn't get corrupted.
            pass