#!/usr/bin/env python3
"""
Package: domain.equity_retained

Equity & Retained Earnings domain module.

Exports all public classes, enums, value objects, entities,
aggregates, events, validators, and repository protocols.
"""

from domain.equity_retained.aggregate_root import (
    DuplicateTransactionError,
    EquityAggregate,
    EquityAggregateError,
    EquityRepository,
    InsufficientPaidInCapitalError,
    InsufficientRetainedEarningsError,
    TransactionNotFoundError,
)
from domain.equity_retained.capital_contribution_entity import (
    CapitalContributionEntity,
    CapitalContributionError,
    CapitalContributionRepository,
    ContributionStatus,
    ContributionType,
    InvalidContributionAmountError,
    InvalidSharePercentageError,
)
from domain.equity_retained.capital_contribution_entity import (
    InvalidStatusTransitionError as CapitalContributionInvalidStatusTransitionError,
)
from domain.equity_retained.capital_withdrawal_entity import (
    CapitalWithdrawalEntity,
    CapitalWithdrawalError,
    CapitalWithdrawalRepository,
    InvalidWithdrawalAmountError,
    WithdrawalExceedsCapitalError,
    WithdrawalStatus,
    WithdrawalType,
)
from domain.equity_retained.capital_withdrawal_entity import (
    InvalidStatusTransitionError as CapitalWithdrawalInvalidStatusTransitionError,
)
from domain.equity_retained.dividend_declaration_entity import (
    AllocationMismatchError,
    DividendDeclarationEntity,
    DividendDeclarationRepository,
    DividendError,
    DividendShareholderAllocation,
    DividendStatus,
    DividendType,
    InvalidDividendAmountError,
    InvalidDividendDatesError,
    allocate_dividend_by_shares,
    calculate_dividend_per_share,
)
from domain.equity_retained.dividend_declaration_entity import (
    InvalidStatusTransitionError as DividendInvalidStatusTransitionError,
)
from domain.equity_retained.domain_events import (
    CapitalContributionApprovedEvent,
    CapitalContributionCancelledEvent,
    CapitalContributionPostedEvent,
    CapitalContributionRecordedEvent,
    CapitalWithdrawalApprovedEvent,
    CapitalWithdrawalCancelledEvent,
    CapitalWithdrawalPostedEvent,
    CapitalWithdrawalRecordedEvent,
    DividendApprovedEvent,
    DividendCancelledEvent,
    DividendDeclaredEvent,
    DividendPaidEvent,
    DividendPartiallyPaidEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    RetainedEarningsAdjustedEvent,
    RetainedEarningsTransferEvent,
    RetainedEarningsUpdatedEvent,
    deserialize_domain_event,
    serialize_domain_event,
)
from domain.equity_retained.invariants import (
    CapitalContributionInvariants,
    CapitalWithdrawalInvariants,
    DividendInvariants,
    EquityInvariantEnforcer,
    InvariantResult,
    RetainedEarningsInvariants,
    validate_capital_contribution_invariants,
    validate_capital_withdrawal_invariants,
    validate_currency_code,
    validate_date_sequence,
    validate_dividend_declaration_invariants,
    validate_non_negative_amount,
    validate_percentage,
    validate_positive_amount,
    validate_version,
)
from domain.equity_retained.retained_earnings_entity import (
    DuplicatePeriodError as RetainedEarningsDuplicatePeriodError,
)
from domain.equity_retained.retained_earnings_entity import (
    InsufficientRetainedEarningsError as RetainedEarningsInsufficientError,
)
from domain.equity_retained.retained_earnings_entity import (
    RetainedEarningsEntity,
    RetainedEarningsEntry,
    RetainedEarningsEntryType,
    RetainedEarningsError,
    RetainedEarningsPeriod,
    RetainedEarningsRepository,
)

__all__ = [
    # Capital Contribution
    "ContributionType",
    "ContributionStatus",
    "CapitalContributionEntity",
    "CapitalContributionRepository",
    "CapitalContributionError",
    "InvalidContributionAmountError",
    "InvalidSharePercentageError",
    "CapitalContributionInvalidStatusTransitionError",
    # Capital Withdrawal
    "WithdrawalType",
    "WithdrawalStatus",
    "CapitalWithdrawalEntity",
    "CapitalWithdrawalRepository",
    "CapitalWithdrawalError",
    "InvalidWithdrawalAmountError",
    "WithdrawalExceedsCapitalError",
    "CapitalWithdrawalInvalidStatusTransitionError",
    # Retained Earnings
    "RetainedEarningsEntryType",
    "RetainedEarningsPeriod",
    "RetainedEarningsEntry",
    "RetainedEarningsEntity",
    "RetainedEarningsRepository",
    "RetainedEarningsError",
    "RetainedEarningsInsufficientError",
    "RetainedEarningsDuplicatePeriodError",
    # Dividend
    "DividendType",
    "DividendStatus",
    "DividendShareholderAllocation",
    "DividendDeclarationEntity",
    "DividendDeclarationRepository",
    "DividendError",
    "InvalidDividendAmountError",
    "InvalidDividendDatesError",
    "AllocationMismatchError",
    "DividendInvalidStatusTransitionError",
    "calculate_dividend_per_share",
    "allocate_dividend_by_shares",
    # Aggregate
    "EquityAggregate",
    "EquityRepository",
    "EquityAggregateError",
    "InsufficientPaidInCapitalError",
    "InsufficientRetainedEarningsError",
    "DuplicateTransactionError",
    "TransactionNotFoundError",
    # Domain Events
    "DomainEventType",
    "DomainEvent",
    "CapitalContributionRecordedEvent",
    "CapitalContributionApprovedEvent",
    "CapitalContributionPostedEvent",
    "CapitalContributionCancelledEvent",
    "CapitalWithdrawalRecordedEvent",
    "CapitalWithdrawalApprovedEvent",
    "CapitalWithdrawalPostedEvent",
    "CapitalWithdrawalCancelledEvent",
    "RetainedEarningsUpdatedEvent",
    "RetainedEarningsAdjustedEvent",
    "RetainedEarningsTransferEvent",
    "DividendDeclaredEvent",
    "DividendApprovedEvent",
    "DividendPaidEvent",
    "DividendPartiallyPaidEvent",
    "DividendCancelledEvent",
    "DomainEventPublisher",
    "deserialize_domain_event",
    "serialize_domain_event",
    # Invariants & Validators
    "InvariantResult",
    "CapitalContributionInvariants",
    "CapitalWithdrawalInvariants",
    "RetainedEarningsInvariants",
    "DividendInvariants",
    "EquityInvariantEnforcer",
    "validate_capital_contribution_invariants",
    "validate_capital_withdrawal_invariants",
    "validate_dividend_declaration_invariants",
    "validate_positive_amount",
    "validate_non_negative_amount",
    "validate_currency_code",
    "validate_percentage",
    "validate_date_sequence",
    "validate_version",
]
