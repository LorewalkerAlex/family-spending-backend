"""Build and own the single-process backend object graph."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date

from family_spending_backend.application.enrichment import EnrichmentService
from family_spending_backend.application.feedback import FeedbackService
from family_spending_backend.application.manual_input import ManualInputService
from family_spending_backend.application.mapping_review import MappingReviewService
from family_spending_backend.application.models import statement_dates_for_reconciled_evidence
from family_spending_backend.application.ports.authentication import Authenticator
from family_spending_backend.application.recommendation import MappingRecommendationService
from family_spending_backend.application.scheduling import ScheduledInputService
from family_spending_backend.application.source_sync import SourceSyncService
from family_spending_backend.config import Settings
from family_spending_backend.domain.reconciliation import ReconciliationEngine
from family_spending_backend.interfaces.http.authentication import DisabledAuthenticator
from family_spending_backend.persistence.filesystem import (
    FilesystemCmbEmailEvidenceStore,
    FilesystemEnrichmentDecisionStore,
    FilesystemFeedbackStore,
    FilesystemIdentityStore,
    FilesystemLayout,
    FilesystemManualEvidenceStore,
    FilesystemMappingStore,
    FilesystemScheduleStore,
    FileUnitOfWork,
)
from family_spending_backend.read_model import ReadModelBootstrap
from family_spending_backend.runtime import (
    MutationCoordinator,
    RuntimeState,
    SchedulerSupervisor,
    SchedulerTrigger,
    SourceSupervisor,
)
from family_spending_backend.runtime.instance_lock import InstanceLock
from family_spending_backend.sources.cmb_email.cache import CmbParserCache
from family_spending_backend.sources.cmb_email.imap_163 import Imap163Connector
from family_spending_backend.sources.cmb_email.ingestion import CmbEmailIngestionService
from family_spending_backend.sources.cmb_email.reconciliation import CmbEmailReconciliationPolicy
from family_spending_backend.sources.cmb_email.source import CmbEmailSource
from family_spending_backend.sources.manual.reconciliation import ManualReconciliationPolicy
from family_spending_backend.sources.manual.source import ManualSource


@dataclass(slots=True)
class ApplicationContainer:
    """Typed access to process-owned adapters, services, and lifecycle."""

    settings: Settings
    filesystem_layout: FilesystemLayout
    runtime_state: RuntimeState
    identity_store: FilesystemIdentityStore
    manual_evidence_store: FilesystemManualEvidenceStore
    cmb_email_evidence_store: FilesystemCmbEmailEvidenceStore
    cmb_parser_cache: CmbParserCache
    mapping_store: FilesystemMappingStore
    enrichment_store: FilesystemEnrichmentDecisionStore
    feedback_store: FilesystemFeedbackStore
    schedule_store: FilesystemScheduleStore
    manual_input_service: ManualInputService
    enrichment_service: EnrichmentService
    mapping_review_service: MappingReviewService
    source_sync_service: SourceSyncService
    feedback_service: FeedbackService
    scheduled_input_service: ScheduledInputService
    scheduler_trigger: SchedulerTrigger
    scheduler_supervisor: SchedulerSupervisor
    source_supervisor: SourceSupervisor | None
    instance_lock: InstanceLock
    authenticator: Authenticator
    read_model_bootstrap: ReadModelBootstrap

    @contextmanager
    def lifespan(self) -> Iterator[None]:
        """Start and stop all resources as one failure-safe process boundary."""

        self.instance_lock.acquire()
        scheduler_started = False
        source_started = False
        try:
            self.filesystem_layout.initialize()
            read_model = self.read_model_bootstrap.build()
            self.runtime_state.publish_initial(read_model)
            if read_model.unreconciled_source_record_ids:
                self.source_sync_service.sync()
            if self.settings.scheduler_enabled:
                self.scheduler_trigger.run_once()
                self.scheduler_supervisor.start()
                scheduler_started = True
            if self.source_supervisor is not None:
                self.source_supervisor.start()
                source_started = True
            yield
        finally:
            if source_started and self.source_supervisor is not None:
                self.source_supervisor.stop()
            if scheduler_started:
                self.scheduler_supervisor.stop()
            self.instance_lock.release()


def build_container(settings: Settings) -> ApplicationContainer:
    """Compose the concrete single-process implementation."""

    layout = FilesystemLayout(settings.data_root)
    instance_lock = InstanceLock(layout.root)
    parser_cache = CmbParserCache(settings.parser_version)
    runtime_state = RuntimeState(settings, parser_cache_stats=parser_cache)
    identity_store = FilesystemIdentityStore(layout)
    manual_evidence_store = FilesystemManualEvidenceStore(layout)
    cmb_email_evidence_store = FilesystemCmbEmailEvidenceStore(layout)
    mapping_store = FilesystemMappingStore(layout)
    enrichment_store = FilesystemEnrichmentDecisionStore(layout)
    feedback_store = FilesystemFeedbackStore(layout)
    schedule_store = FilesystemScheduleStore(layout)
    manual_source = ManualSource(manual_evidence_store)
    cmb_email_source = CmbEmailSource(cmb_email_evidence_store, parser_cache)

    def load_source_records():
        return (*cmb_email_source.load_records(), *manual_source.load_records())

    def load_statement_dates():
        return statement_dates_for_reconciled_evidence(
            load_source_records(),
            identity_store.load(),
            cmb_email_source.load_statement_dates_by_evidence(),
        )

    coordinator = MutationCoordinator(runtime_state)
    reconciliation = ReconciliationEngine(
        (CmbEmailReconciliationPolicy(), ManualReconciliationPolicy())
    )
    manual_input_service = ManualInputService(
        evidence_store=manual_evidence_store,
        identity_store=identity_store,
        mapping_store=mapping_store,
        enrichment_store=enrichment_store,
        load_statement_dates=load_statement_dates,
        runtime=runtime_state,
        load_source_records=load_source_records,
        reconciliation=reconciliation,
        coordinator=coordinator,
        open_unit_of_work=lambda label: FileUnitOfWork(
            (layout.manual_evidence, layout.source_links, layout.enrichment_decisions),
            label=label,
        ),
    )
    enrichment_service = EnrichmentService(
        enrichment_store=enrichment_store,
        runtime=runtime_state,
        coordinator=coordinator,
        open_unit_of_work=lambda label: FileUnitOfWork((layout.enrichment_decisions,), label=label),
    )
    mapping_review_service = MappingReviewService(
        mapping_store=mapping_store,
        runtime=runtime_state,
        coordinator=coordinator,
        open_unit_of_work=lambda label: FileUnitOfWork(
            (layout.merchant_mappings, layout.category_mappings), label=label
        ),
        recommendations=MappingRecommendationService(),
    )
    source_sync_service = SourceSyncService(
        load_source_records=load_source_records,
        reconciliation=reconciliation,
        identity_store=identity_store,
        mapping_store=mapping_store,
        enrichment_store=enrichment_store,
        load_statement_dates=load_statement_dates,
        runtime=runtime_state,
        coordinator=coordinator,
        open_unit_of_work=lambda label: FileUnitOfWork(
            (layout.source_links, layout.enrichment_decisions), label=label
        ),
    )
    feedback_service = FeedbackService(
        store=feedback_store,
        runtime=runtime_state,
        coordinator=coordinator,
        open_unit_of_work=lambda label: FileUnitOfWork((layout.feedback,), label=label),
    )
    scheduled_input_service = ScheduledInputService(
        schedule_store=schedule_store,
        manual_store=manual_evidence_store,
        enrichment_store=enrichment_store,
        identity_store=identity_store,
        source_sync=source_sync_service,
        runtime=runtime_state,
        coordinator=coordinator,
        open_unit_of_work=lambda label: FileUnitOfWork(
            (
                layout.scheduled_rules,
                layout.schedule_execution,
                layout.manual_evidence,
                layout.source_links,
                layout.enrichment_decisions,
            ),
            label=label,
        ),
    )
    scheduler_trigger = SchedulerTrigger(
        scheduled_input_service.run_due,
        runtime=runtime_state,
        today=date.today,
    )
    scheduler_supervisor = SchedulerSupervisor(
        scheduler_trigger,
        interval_seconds=settings.scheduler_interval_seconds,
    )
    source_supervisor: SourceSupervisor | None = None
    if settings.cmb_email_poll_enabled:
        assert settings.imap_address is not None
        assert settings.imap_auth_code is not None
        connector = Imap163Connector(
            address=settings.imap_address,
            auth_code=settings.imap_auth_code.get_secret_value(),
            host=settings.imap_host,
            port=settings.imap_port,
            mailbox=settings.imap_mailbox,
            subject_keyword=settings.imap_subject_keyword,
            since=settings.imap_since,
            timeout_seconds=settings.imap_timeout_seconds,
        )
        source_supervisor = SourceSupervisor(
            (
                CmbEmailIngestionService(
                    connector=connector,
                    evidence_writer=cmb_email_evidence_store,
                    source_sync=source_sync_service,
                    runtime=runtime_state,
                    coordinator=coordinator,
                    open_unit_of_work=lambda evidence, label: FileUnitOfWork(
                        (
                            *(layout.cmb_email_evidence / item.filename for item in evidence),
                            layout.source_links,
                            layout.enrichment_decisions,
                        ),
                        label=label,
                    ),
                ),
            ),
            source_sync=source_sync_service.sync,
            runtime=runtime_state,
            interval_seconds=settings.email_poll_interval_seconds,
        )

    read_model_bootstrap = ReadModelBootstrap(
        layout,
        load_source_records=load_source_records,
        identity_store=identity_store,
        mapping_store=mapping_store,
        enrichment_store=enrichment_store,
        load_statement_dates=cmb_email_source.load_statement_dates_by_evidence,
        feedback_store=feedback_store,
        schedule_store=schedule_store,
    )
    return ApplicationContainer(
        settings=settings,
        filesystem_layout=layout,
        runtime_state=runtime_state,
        identity_store=identity_store,
        manual_evidence_store=manual_evidence_store,
        cmb_email_evidence_store=cmb_email_evidence_store,
        cmb_parser_cache=parser_cache,
        mapping_store=mapping_store,
        enrichment_store=enrichment_store,
        feedback_store=feedback_store,
        schedule_store=schedule_store,
        manual_input_service=manual_input_service,
        enrichment_service=enrichment_service,
        mapping_review_service=mapping_review_service,
        source_sync_service=source_sync_service,
        feedback_service=feedback_service,
        scheduled_input_service=scheduled_input_service,
        scheduler_trigger=scheduler_trigger,
        scheduler_supervisor=scheduler_supervisor,
        source_supervisor=source_supervisor,
        instance_lock=instance_lock,
        authenticator=DisabledAuthenticator(),
        read_model_bootstrap=read_model_bootstrap,
    )
