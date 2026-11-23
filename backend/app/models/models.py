"""SQLAlchemy models. All money is Decimal (see database.types.Money)."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.database.types import Money, UTCDateTime, utcnow


class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String(20), unique=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    tax_id: Mapped[str | None] = mapped_column(String(40), index=True)
    country: Mapped[str] = mapped_column(String(60), default="India")
    approval_status: Mapped[str] = mapped_column(String(20), default="APPROVED")  # APPROVED|INACTIVE|BLOCKED
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="vendor")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(40), unique=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    issue_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    subtotal: Mapped[Decimal] = mapped_column(Money)
    tax_amount: Mapped[Decimal] = mapped_column(Money)
    authorized_total: Mapped[Decimal] = mapped_column(Money)
    # Cache only. The source of truth is authorized_total - SUM(approved invoices);
    # po_matcher.reconcile_po() recomputes it on every allocation.
    remaining_balance: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(24), default="OPEN")  # OPEN|PARTIALLY_INVOICED|FULLY_INVOICED|CLOSED
    description: Mapped[str | None] = mapped_column(String(300))

    vendor: Mapped[Vendor] = relationship(back_populates="purchase_orders")
    lines: Mapped[list["POLine"]] = relationship(
        back_populates="po", order_by="POLine.line_no", cascade="all, delete-orphan"
    )
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="po")


class POLine(Base):
    __tablename__ = "po_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_description: Mapped[str] = mapped_column(String(300))
    sku: Mapped[str | None] = mapped_column(String(60))
    quantity: Mapped[Decimal] = mapped_column(Money)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    tax_rate: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    authorized_amount: Mapped[Decimal] = mapped_column(Money)  # qty * price * (1 + tax)

    po: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str | None] = mapped_column(String(80))
    invoice_number_norm: Mapped[str | None] = mapped_column(String(80), index=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), index=True)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    vendor_name_raw: Mapped[str | None] = mapped_column(String(200))
    po_number_raw: Mapped[str | None] = mapped_column(String(60))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    tax_amount: Mapped[Decimal | None] = mapped_column(Money)
    total_amount: Mapped[Decimal | None] = mapped_column(Money)
    extraction_data: Mapped[dict | None] = mapped_column(JSON)
    extraction_method: Mapped[str | None] = mapped_column(String(60))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    corrections: Mapped[list] = mapped_column(JSON, default=list)
    original_file_path: Mapped[str | None] = mapped_column(String(500))
    original_filename: Mapped[str | None] = mapped_column(String(300))
    file_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(12), default="UPLOAD")  # UPLOAD | HISTORY
    processing_status: Mapped[str] = mapped_column(String(20), default="UPLOADED")  # UPLOADED|PROCESSING|PROCESSED|PROCESSING_ERROR
    final_decision: Mapped[str | None] = mapped_column(String(20))  # APPROVED|NEEDS_REVIEW|REJECTED|PROCESSING_ERROR
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decision_detail: Mapped[dict | None] = mapped_column(JSON)
    decision_source: Mapped[str | None] = mapped_column(String(10))  # AUTO | MANUAL
    review_state: Mapped[str | None] = mapped_column(String(30))  # OPEN | CLARIFICATION_REQUESTED | RESOLVED
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    vendor: Mapped[Vendor | None] = relationship(foreign_keys=[vendor_id])
    po: Mapped[PurchaseOrder | None] = relationship(back_populates="invoices", foreign_keys=[po_id])
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", order_by="InvoiceLine.line_no", cascade="all, delete-orphan"
    )
    runs: Mapped[list["ProcessingRun"]] = relationship(back_populates="invoice", order_by="ProcessingRun.started_at")
    validations: Mapped[list["ValidationResult"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="ValidationResult.id"
    )

    __table_args__ = (Index("ix_invoice_vendor_number", "vendor_id", "invoice_number_norm"),)


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(400))
    sku: Mapped[str | None] = mapped_column(String(60))
    quantity: Mapped[Decimal | None] = mapped_column(Money)
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    tax_rate: Mapped[Decimal | None] = mapped_column(Money)
    line_total: Mapped[Decimal | None] = mapped_column(Money)
    matched_po_line_id: Mapped[int | None] = mapped_column(ForeignKey("po_lines.id"))

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class ProcessingRun(Base):
    __tablename__ = "processing_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    filename: Mapped[str | None] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(14), default="FULL")  # FULL | REVALIDATION
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    current_stage: Mapped[str | None] = mapped_column(String(40))
    processing_status: Mapped[str] = mapped_column(String(12), default="QUEUED")  # QUEUED|RUNNING|COMPLETED|FAILED
    execution_duration: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
    final_decision: Mapped[str | None] = mapped_column(String(20))

    invoice: Mapped[Invoice] = relationship(back_populates="runs")
    stages: Mapped[list["StageEvent"]] = relationship(
        back_populates="run", order_by="StageEvent.order", cascade="all, delete-orphan"
    )


class StageEvent(Base):
    __tablename__ = "stage_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_pk: Mapped[int] = mapped_column(ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column(Integer)
    stage_key: Mapped[str] = mapped_column(String(40))
    stage_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default="QUEUED")  # QUEUED|RUNNING|COMPLETED|WARNING|FAILED|SKIPPED
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    data: Mapped[dict | None] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[ProcessingRun] = relationship(back_populates="stages")
    __table_args__ = (UniqueConstraint("run_pk", "stage_key"),)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    rule_id: Mapped[str] = mapped_column(String(8))
    rule_name: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(16))  # PASS|FAIL|REVIEW|NOT_APPLICABLE
    expected_value: Mapped[str | None] = mapped_column(Text)
    actual_value: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    hard_block: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[dict | None] = mapped_column(JSON)

    invoice: Mapped[Invoice] = relationship(back_populates="validations")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    previous_value: Mapped[dict | list | str | None] = mapped_column(JSON)
    new_value: Mapped[dict | list | str | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
