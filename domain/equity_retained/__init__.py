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
    "AllocationMismatchError",
    "CapitalContributionApprovedEvent",
    "CapitalContributionCancelledEvent",
    "CapitalContributionEntity",
    "CapitalContributionError",
    "CapitalContributionInvalidStatusTransitionError",
    "CapitalContributionInvariants",
    "CapitalContributionPostedEvent",
    "CapitalContributionRecordedEvent",
    "CapitalContributionRepository",
    "CapitalWithdrawalApprovedEvent",
    "CapitalWithdrawalCancelledEvent",
    "CapitalWithdrawalEntity",
    "CapitalWithdrawalError",
    "CapitalWithdrawalInvalidStatusTransitionError",
    "CapitalWithdrawalInvariants",
    "CapitalWithdrawalPostedEvent",
    "CapitalWithdrawalRecordedEvent",
    "CapitalWithdrawalRepository",
    "ContributionStatus",
    # Capital Contribution
    "ContributionType",
    "DividendApprovedEvent",
    "DividendCancelledEvent",
    "DividendDeclarationEntity",
    "DividendDeclarationRepository",
    "DividendDeclaredEvent",
    "DividendError",
    "DividendInvalidStatusTransitionError",
    "DividendInvariants",
    "DividendPaidEvent",
    "DividendPartiallyPaidEvent",
    "DividendShareholderAllocation",
    "DividendStatus",
    # Dividend
    "DividendType",
    "DomainEvent",
    "DomainEventPublisher",
    # Domain Events
    "DomainEventType",
    "DuplicateTransactionError",
    # Aggregate
    "EquityAggregate",
    "EquityAggregateError",
    "EquityInvariantEnforcer",
    "EquityRepository",
    "InsufficientPaidInCapitalError",
    "InsufficientRetainedEarningsError",
    "InvalidContributionAmountError",
    "InvalidDividendAmountError",
    "InvalidDividendDatesError",
    "InvalidSharePercentageError",
    "InvalidWithdrawalAmountError",
    # Invariants & Validators
    "InvariantResult",
    "RetainedEarningsAdjustedEvent",
    "RetainedEarningsDuplicatePeriodError",
    "RetainedEarningsEntity",
    "RetainedEarningsEntry",
    # Retained Earnings
    "RetainedEarningsEntryType",
    "RetainedEarningsError",
    "RetainedEarningsInsufficientError",
    "RetainedEarningsInvariants",
    "RetainedEarningsPeriod",
    "RetainedEarningsRepository",
    "RetainedEarningsTransferEvent",
    "RetainedEarningsUpdatedEvent",
    "TransactionNotFoundError",
    "WithdrawalExceedsCapitalError",
    "WithdrawalStatus",
    # Capital Withdrawal
    "WithdrawalType",
    "allocate_dividend_by_shares",
    "calculate_dividend_per_share",
    "deserialize_domain_event",
    "serialize_domain_event",
    "validate_capital_contribution_invariants",
    "validate_capital_withdrawal_invariants",
    "validate_currency_code",
    "validate_date_sequence",
    "validate_dividend_declaration_invariants",
    "validate_non_negative_amount",
    "validate_percentage",
    "validate_positive_amount",
    "validate_version",
]
