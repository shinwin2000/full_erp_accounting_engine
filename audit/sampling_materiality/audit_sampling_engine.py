#!/usr/bin/env python3
"""
Module: audit_sampling_engine.py
Layer: Domain / Audit
Responsibility: Statistical sampling engine for audit procedures.
"""

from __future__ import annotations

import math
import random
from decimal import Decimal
from enum import Enum
from typing import Any


class SampleType(Enum):
    """Jenis metode sampling audit."""

    RANDOM = "random"
    STRATIFIED = "stratified"
    MONETARY_UNIT = "monetary_unit"
    HAUCK_ROESSLER = "hauck_roessler"
    SYSTEMATIC = "systematic"


class AuditSamplingEngine:
    """Statistical sampling engine for audit procedures."""

    def monetary_unit_sampling(
        self,
        population: list[Any],
        monetary_values: list[Decimal],
        confidence_level: float = 0.95,
        materiality: Decimal = Decimal("1000000"),
    ) -> list[Any]:
        """
        Monetary Unit Sampling (MUS) - PPS sampling.
        """
        if not population:
            return []
        total = sum(monetary_values)
        if total == 0:
            return []
        sampling_interval = total / (math.ceil(total / materiality) if total > materiality else 1)
        if sampling_interval <= 0:
            return []
        selected = []
        cumulative = Decimal("0")
        for i, val in enumerate(monetary_values):
            cumulative += val
            if cumulative >= sampling_interval:
                selected.append(population[i])
                cumulative -= sampling_interval
        return selected

    def random_sampling(self, population: list[Any], sample_size: int) -> list[Any]:
        """Simple random sampling without replacement."""
        if sample_size >= len(population):
            return population[:]
        return random.sample(population, sample_size)

    def stratified_sampling(
        self, population_by_stratum: dict[str, list[Any]], sample_sizes: dict[str, int]
    ) -> dict[str, list[Any]]:
        """Stratified sampling per stratum."""
        result = {}
        for stratum, items in population_by_stratum.items():
            size = sample_sizes.get(stratum, 0)
            if size > 0 and items:
                if size >= len(items):
                    result[stratum] = items[:]
                else:
                    result[stratum] = random.sample(items, size)
            else:
                result[stratum] = []
        return result

    def hauck_roessler_sampling(
        self, population: list[Any], values: list[Decimal], min_value: Decimal, max_value: Decimal
    ) -> list[Any]:
        """Sampling for high-risk/high-value items (Hauck-Roessler)."""
        selected = []
        for i, val in enumerate(values):
            if min_value <= val <= max_value:
                selected.append(population[i])
        return selected

    def systematic_sampling(self, population: list[Any], sample_size: int) -> list[Any]:
        """Systematic sampling (every k-th element)."""
        if sample_size >= len(population):
            return population[:]
        interval = len(population) / sample_size
        start = random.randint(0, int(interval) - 1)
        selected = []
        for i in range(sample_size):
            idx = int(start + i * interval)
            if idx < len(population):
                selected.append(population[idx])
        return selected

    def select_sample(
        self,
        population: list[Any],
        sample_type: SampleType,
        sample_size: int | None = None,
        confidence_level: float = 0.95,
        expected_error_rate: float = 0.01,
        materiality: Decimal | None = None,
        monetary_values: list[Decimal] | None = None,
        strata: dict[str, list[Any]] | None = None,
        strata_sizes: dict[str, int] | None = None,
        min_value: Decimal = Decimal("0"),
        max_value: Decimal = Decimal("inf"),
    ) -> tuple[list[Any], Decimal | None]:
        """
        Generic sample selection based on type.
        Returns (sample_items, sampling_error).
        """
        if sample_type == SampleType.RANDOM:
            if sample_size is None:
                raise ValueError("sample_size required for random sampling")
            items = self.random_sampling(population, sample_size)
            error = None
        elif sample_type == SampleType.STRATIFIED:
            if strata is None or strata_sizes is None:
                raise ValueError("strata and strata_sizes required for stratified sampling")
            items_dict = self.stratified_sampling(strata, strata_sizes)
            items = [item for sublist in items_dict.values() for item in sublist]
            error = None
        elif sample_type == SampleType.MONETARY_UNIT:
            if monetary_values is None or materiality is None:
                raise ValueError("monetary_values and materiality required for MUS")
            items = self.monetary_unit_sampling(
                population, monetary_values, confidence_level, materiality
            )
            error = None
        elif sample_type == SampleType.HAUCK_ROESSLER:
            if monetary_values is None:
                raise ValueError("monetary_values required for Hauck-Roessler sampling")
            items = self.hauck_roessler_sampling(population, monetary_values, min_value, max_value)
            error = None
        elif sample_type == SampleType.SYSTEMATIC:
            if sample_size is None:
                raise ValueError("sample_size required for systematic sampling")
            items = self.systematic_sampling(population, sample_size)
            error = None
        else:
            raise ValueError(f"Unsupported sample type: {sample_type}")

        # Estimate sampling error for simple random
        if sample_type == SampleType.RANDOM and len(items) > 1:
            error_rate = expected_error_rate
            error_margin = Decimal(
                str(1.96 * math.sqrt(error_rate * (1 - error_rate) / len(items)))
            )
            error = error_margin * Decimal("100")
        else:
            error = None

        return items, error


__all__ = ["AuditSamplingEngine", "SampleType"]
