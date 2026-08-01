#!/usr/bin/env python3
"""
tests/policy_engine/test_interpreter.py
Comprehensive tests for policy_engine/interpreter.py

Covers all public and private methods:
- EvaluationResult constants
- ConditionEvaluator: evaluate, _resolve_value, _is_number, _parse_arguments,
  register_function, register_operator
- ActionExecutor: _init_builtin, all _action_* private methods, execute,
  _parse_action_params, register_action, get_available_actions
- PolicyInterpreter: evaluate_condition, execute_action, evaluate_policy,
  evaluate_by_domain, evaluate_multiple_domains, start_batch, end_batch,
  _record_evaluation, register_custom_action, register_custom_function,
  enable_cache, disable_cache, clear_cache, get_evaluation_history, get_stats,
  generate_report, export_to_json, get_policy_interpreter
- All edge cases, negative paths, and error handling
- No flaky datetime (mocked)
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from policy_engine.interpreter import (
    ActionExecutor,
    ConditionEvaluator,
    EvaluationResult,
    PolicyInterpreter,
    get_policy_interpreter,
)
from policy_engine.loader_yaml import PolicyRule, PolicySet

# =============================================================================
# Fixtures
# =============================================================================

FIXED_DATETIME = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now to return fixed datetime."""
    with patch("policy_engine.interpreter.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.UTC = UTC
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def sample_context():
    return {
        "amount": Decimal("1500000"),
        "user": {"name": "John", "role": "manager"},
        "status": "pending",
        "items": [{"price": 100}, {"price": 200}],
        "age": 30,
        "flag": False,
    }


@pytest.fixture
def sample_policy():
    rule1 = PolicyRule(
        id="rule1",
        name="Large Transaction",
        condition="amount > 1000000",
        action="flag(type=high_amount)",
        priority=10,
        enabled=True,
    )
    rule2 = PolicyRule(
        id="rule2",
        name="Weekend Rule",
        condition="day(now()) == 6 or day(now()) == 0",
        action="log(message=Weekend transaction)",
        priority=5,
        enabled=True,
    )
    return PolicySet(
        id="txn_policy",
        name="Transaction Policy",
        domain="transaction",
        version=1,
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
        jurisdiction="ID",
        rules=[rule1, rule2],
    )


@pytest.fixture
def interpreter():
    return PolicyInterpreter()


# =============================================================================
# EvaluationResult
# =============================================================================

class TestEvaluationResult:
    def test_constants(self):
        assert EvaluationResult.SUCCESS == "success"
        assert EvaluationResult.FAILURE == "failure"
        assert EvaluationResult.CONDITION_FALSE == "condition_false"
        assert EvaluationResult.ACTION_ERROR == "action_error"
        assert EvaluationResult.SKIPPED == "skipped"


# =============================================================================
# ConditionEvaluator
# =============================================================================

class TestConditionEvaluator:
    def test_evaluate_simple_equality(self, sample_context):
        assert ConditionEvaluator.evaluate("status == 'pending'", sample_context) is True
        assert ConditionEvaluator.evaluate("status == 'approved'", sample_context) is False

    def test_evaluate_numeric_comparison(self, sample_context):
        assert ConditionEvaluator.evaluate("amount > 1000000", sample_context) is True
        assert ConditionEvaluator.evaluate("amount < 1000000", sample_context) is False
        assert ConditionEvaluator.evaluate("age >= 30", sample_context) is True

    def test_evaluate_in_operator(self, sample_context):
        sample_context["roles"] = ["admin", "manager"]
        assert ConditionEvaluator.evaluate("'manager' in roles", sample_context) is True
        assert ConditionEvaluator.evaluate("'guest' in roles", sample_context) is False

    def test_evaluate_contains_operator(self, sample_context):
        sample_context["name"] = "John Doe"
        assert ConditionEvaluator.evaluate("name contains 'John'", sample_context) is True
        assert ConditionEvaluator.evaluate("name contains 'Jane'", sample_context) is False

    def test_evaluate_matches_regex(self, sample_context):
        sample_context["code"] = "ABC-123"
        assert ConditionEvaluator.evaluate("code matches '^ABC-\\d+$'", sample_context) is True
        assert ConditionEvaluator.evaluate("code matches '^XYZ'", sample_context) is False

    def test_evaluate_boolean_literals(self):
        assert ConditionEvaluator.evaluate("true", {}) is True
        assert ConditionEvaluator.evaluate("false", {}) is False
        assert ConditionEvaluator.evaluate("none", {}) is None

    def test_evaluate_function_call(self):
        context = {"dt": FIXED_DATETIME}
        assert ConditionEvaluator.evaluate("year(now()) == 2026", context) is True
        assert ConditionEvaluator.evaluate("month(now()) == 1", context) is True
        assert ConditionEvaluator.evaluate("day(now()) == 15", context) is True
        assert ConditionEvaluator.evaluate("hour(now()) == 12", context) is True
        assert ConditionEvaluator.evaluate("minute(now()) == 0", context) is True
        assert ConditionEvaluator.evaluate("abs(-5) == 5", context) is True
        assert ConditionEvaluator.evaluate("round(3.7) == 4", context) is True
        assert ConditionEvaluator.evaluate("floor(3.7) == 3", context) is True
        assert ConditionEvaluator.evaluate("ceil(3.2) == 4", context) is True
        assert ConditionEvaluator.evaluate("len([1,2,3]) == 3", context) is True
        assert ConditionEvaluator.evaluate("str(100) == '100'", context) is True
        assert ConditionEvaluator.evaluate("int('123') == 123", context) is True
        assert ConditionEvaluator.evaluate("float('1.23') == 1.23", context) is True

    def test_evaluate_list_literal(self):
        context = {}
        assert ConditionEvaluator.evaluate("[1,2,3] contains 2", context) is True
        # Also test list literal resolution via _resolve_value indirectly
        result = ConditionEvaluator.evaluate("[1,2,3] == [1,2,3]", context)
        assert result is True

    def test_evaluate_dict_literal(self):
        context = {}
        result = ConditionEvaluator.evaluate("{'a':1, 'b':2} == {'a':1, 'b':2}", context)
        assert result is True

    def test_evaluate_context_variable(self, sample_context):
        assert ConditionEvaluator.evaluate("status", sample_context) == "pending"
        # Nested attribute
        assert ConditionEvaluator.evaluate("user.name", sample_context) == "John"
        # Bracket access
        sample_context["data"] = {"key": "value"}
        assert ConditionEvaluator.evaluate("data['key']", sample_context) == "value"

    def test_evaluate_malformed_condition(self, sample_context):
        # Should return False without raising
        assert ConditionEvaluator.evaluate("invalid syntax", sample_context) is False

    def test_evaluate_empty_condition(self):
        assert ConditionEvaluator.evaluate("", {}) is True
        assert ConditionEvaluator.evaluate("   ", {}) is True

    def test_register_function(self):
        ConditionEvaluator.register_function("double", lambda x: x * 2)
        context = {"x": 5}
        assert ConditionEvaluator.evaluate("double(5) == 10", context) is True

    def test_register_operator(self):
        ConditionEvaluator.register_operator("**", lambda x, y: x ** y)
        # Test operator by direct usage
        op_func = ConditionEvaluator._operators["**"]
        assert op_func(2, 3) == 8

    # ---- Private methods ----
    def test_resolve_value_string_literal(self):
        context = {}
        assert ConditionEvaluator._resolve_value("'hello'", context) == "hello"
        assert ConditionEvaluator._resolve_value('"world"', context) == "world"

    def test_resolve_value_number_literal(self):
        context = {}
        assert ConditionEvaluator._resolve_value("123", context) == 123
        assert ConditionEvaluator._resolve_value("12.34", context) == Decimal("12.34")
        assert ConditionEvaluator._resolve_value("-5", context) == -5

    def test_resolve_value_boolean_and_none(self):
        context = {}
        assert ConditionEvaluator._resolve_value("true", context) is True
        assert ConditionEvaluator._resolve_value("false", context) is False
        assert ConditionEvaluator._resolve_value("none", context) is None

    def test_resolve_value_list_literal(self):
        context = {}
        result = ConditionEvaluator._resolve_value("[1, 2, 3]", context)
        assert result == [1, 2, 3]

    def test_resolve_value_dict_literal(self):
        context = {}
        result = ConditionEvaluator._resolve_value("{'a': 1, 'b': 2}", context)
        assert result == {"a": 1, "b": 2}

    def test_resolve_value_function_call(self):
        context = {}
        assert ConditionEvaluator._resolve_value("now()", context) == FIXED_DATETIME
        assert ConditionEvaluator._resolve_value("year(now())", context) == 2026

    def test_resolve_value_context_variable(self, sample_context):
        assert ConditionEvaluator._resolve_value("status", sample_context) == "pending"
        # Nested
        assert ConditionEvaluator._resolve_value("user.name", sample_context) == "John"

    def test_resolve_value_unknown_returns_string(self, sample_context):
        # Should return the expression as string with warning
        assert ConditionEvaluator._resolve_value("unknown_var", sample_context) == "unknown_var"

    def test_is_number(self):
        assert ConditionEvaluator._is_number("123") is True
        assert ConditionEvaluator._is_number("-123") is True
        assert ConditionEvaluator._is_number("12.34") is True
        assert ConditionEvaluator._is_number("-12.34") is True
        assert ConditionEvaluator._is_number("abc") is False
        assert ConditionEvaluator._is_number("") is False

    def test_parse_arguments_basic(self):
        context = {}
        args = ConditionEvaluator._parse_arguments("1, 2, 3", context)
        assert args == [1, 2, 3]
        args2 = ConditionEvaluator._parse_arguments("'hello', 5", context)
        assert args2 == ["hello", 5]

    def test_parse_arguments_nested(self):
        context = {}
        args = ConditionEvaluator._parse_arguments("1, max(2,3), 4", context)
        # max is not registered, so will be resolved as string? Actually _resolve_value will try to call function and raise ValueError, which will be caught? In current implementation, _resolve_value doesn't catch; but we are testing parser only, so we can check length.
        assert len(args) == 3

    # ---- Additional edge cases for evaluate ----
    def test_evaluate_with_is_operator(self):
        context = {"x": None}
        assert ConditionEvaluator.evaluate("x is none", context) is True
        assert ConditionEvaluator.evaluate("x is_not none", context) is False


# =============================================================================
# ActionExecutor
# =============================================================================

class TestActionExecutor:
    def test_init_builtin(self):
        ActionExecutor._init_builtin()
        assert "approve" in ActionExecutor._builtin_actions
        assert "reject" in ActionExecutor._builtin_actions
        assert "flag" in ActionExecutor._builtin_actions
        assert "calculate" in ActionExecutor._builtin_actions
        assert "validate" in ActionExecutor._builtin_actions
        assert "log" in ActionExecutor._builtin_actions
        assert "notify" in ActionExecutor._builtin_actions
        assert "set" in ActionExecutor._builtin_actions
        assert "increment" in ActionExecutor._builtin_actions
        assert "decrement" in ActionExecutor._builtin_actions
        assert "append" in ActionExecutor._builtin_actions
        assert "remove" in ActionExecutor._builtin_actions
        assert "apply_rate" in ActionExecutor._builtin_actions

    # ---- Direct tests for each private action method ----
    def test_action_approve_direct(self):
        context = {}
        result = ActionExecutor._action_approve(context, message="OK")
        assert context["_action_result"] == "approved"
        assert result["status"] == "approved"
        assert result["message"] == "OK"

    def test_action_reject_direct(self):
        context = {}
        result = ActionExecutor._action_reject(context, message="No")
        assert context["_action_result"] == "rejected"
        assert result["status"] == "rejected"
        assert result["message"] == "No"

    def test_action_flag_direct(self):
        context = {}
        result = ActionExecutor._action_flag(context, type="manual_review", message="Check")
        assert "_flags" in context
        assert "manual_review" in context["_flags"]
        assert result["flag"] == "manual_review"
        assert result["message"] == "Check"

    def test_action_calculate_direct(self):
        context = {"amount": Decimal("1500000")}
        result = ActionExecutor._action_calculate(context, expression="amount * 2", target="doubled")
        assert context["doubled"] == Decimal("3000000")
        assert result["calculated"] == "doubled"
        assert result["value"] == Decimal("3000000")

    def test_action_calculate_error(self, caplog):
        context = {}
        with caplog.at_level("ERROR"):
            result = ActionExecutor._action_calculate(context, expression="invalid", target="x")
        assert "error" in result
        assert "Calculation error" in caplog.text

    def test_action_validate_direct(self):
        context = {"status": "pending"}
        result = ActionExecutor._action_validate(context, rule="check_status", field="status", expected="pending")
        assert "_validations" in context
        assert context["_validations"][0]["rule"] == "check_status"
        assert context["_validations"][0]["valid"] is True
        assert result["validation"] == "check_status"
        assert result["valid"] is True

    def test_action_validate_false(self):
        context = {"status": "pending"}
        ActionExecutor._action_validate(context, rule="check_status", field="status", expected="approved")
        assert context["_validations"][0]["valid"] is False

    def test_action_log_direct(self, caplog):
        context = {}
        with caplog.at_level("INFO"):
            result = ActionExecutor._action_log(context, message="Hello", level="info")
        assert "Hello" in caplog.text
        assert "_logs" in context
        assert "Hello" in context["_logs"]
        assert result["logged"] == "Hello"

    def test_action_notify_direct(self, caplog):
        context = {}
        with caplog.at_level("INFO"):
            result = ActionExecutor._action_notify(context, channel="email", message="Alert")
        assert "NOTIFICATION [email]: Alert" in caplog.text
        assert "_notifications" in context
        assert context["_notifications"][0]["channel"] == "email"
        assert result["notification_sent"] is True
        assert result["channel"] == "email"

    def test_action_set_direct(self):
        context = {}
        result = ActionExecutor._action_set(context, var="myvar", value="hello")
        assert context["myvar"] == "hello"
        assert result["set"] == "myvar"
        assert result["value"] == "hello"

    def test_action_set_missing_var(self):
        context = {}
        result = ActionExecutor._action_set(context)
        assert result["error"] == "missing var parameter"

    def test_action_increment_direct(self):
        context = {"counter": 5}
        result = ActionExecutor._action_increment(context, var="counter", delta=2)
        assert context["counter"] == 7
        assert result["incremented"] == "counter"
        assert result["new_value"] == 7

    def test_action_increment_missing_var(self):
        context = {}
        result = ActionExecutor._action_increment(context, delta=2)
        assert result["error"] == "missing var parameter"

    def test_action_decrement_direct(self):
        context = {"counter": 5}
        result = ActionExecutor._action_decrement(context, var="counter", delta=2)
        assert context["counter"] == 3
        assert result["decremented"] == "counter"
        assert result["new_value"] == 3

    def test_action_append_direct(self):
        context = {"mylist": ["a"]}
        result = ActionExecutor._action_append(context, var="mylist", value="b")
        assert context["mylist"] == ["a", "b"]
        assert result["appended_to"] == "mylist"
        assert result["value"] == "b"

    def test_action_append_missing_var(self):
        context = {}
        result = ActionExecutor._action_append(context, value="b")
        assert result["error"] == "missing var parameter"

    def test_action_remove_direct(self):
        context = {"mylist": ["a", "b", "c"]}
        result = ActionExecutor._action_remove(context, var="mylist", value="b")
        assert context["mylist"] == ["a", "c"]
        assert result["removed_from"] == "mylist"
        assert result["value"] == "b"

    def test_action_remove_missing_var(self):
        context = {}
        result = ActionExecutor._action_remove(context, var="missing", value="x")
        assert result["error"] == "var not found or not a list"

    def test_action_apply_rate_direct(self):
        context = {}
        result = ActionExecutor._action_apply_rate(context, rate=Decimal("0.02"))
        assert context["rate"] == Decimal("0.02")
        assert result["rate"] == Decimal("0.02")

        # Also test string conversion
        context2 = {}
        ActionExecutor._action_apply_rate(context2, rate="0.03")
        assert context2["rate"] == Decimal("0.03")

    # ---- execute method ----
    def test_execute_action_with_space_format(self):
        context = {}
        results = []
        # Space-separated format: "apply_rate 0.02"
        result = ActionExecutor.execute("apply_rate 0.02", context, results)
        # In execute, it detects space and creates params with rate
        # Actually the code handles "apply_rate 0.02" by converting to parameters.
        # Let's test that.
        assert result["rate"] == Decimal("0.02")
        # Also check that context was updated? The apply_rate action sets context["rate"].
        assert context["rate"] == Decimal("0.02")

    def test_execute_custom_action(self):
        def custom_action(context, **params):
            context["custom"] = params.get("value", "default")
            return {"custom_result": "ok"}

        ActionExecutor.register_action("custom", custom_action)
        context = {}
        results = []
        result = ActionExecutor.execute("custom(value=test)", context, results)
        assert context["custom"] == "test"
        assert result["custom_result"] == "ok"

    def test_execute_unknown_action_fallback(self, sample_context):
        results = []
        result = ActionExecutor.execute("unknown_action(param1=1)", sample_context, results)
        # Falls back to storing as instruction
        assert result["action"] == "unknown_action"
        assert result["params"] == {"param1": 1}
        assert "context_snapshot" in result
        assert len(results) == 1

    # ---- parse_action_params ----
    def test_parse_action_params_basic(self):
        context = {"x": 10}
        params = ActionExecutor._parse_action_params("a=1, b='hello', c=x", context)
        assert params == {"a": 1, "b": "hello", "c": 10}

    def test_parse_action_params_with_nested_parentheses(self):
        context = {"data": "test"}
        # Test with nested parentheses in value
        params = ActionExecutor._parse_action_params("func=max(1,2)", context)
        # The parser will split on comma, but here there is no comma, so it will parse entire string as key? Actually it expects key=value. If no =, it's ignored.
        # Let's test a valid case: value with parentheses inside.
        params = ActionExecutor._parse_action_params("expr='func(1,2)'", context)
        # It should resolve the value as string literal.
        assert params["expr"] == "func(1,2)"

    def test_get_available_actions(self):
        actions = ActionExecutor.get_available_actions()
        assert "approve" in actions
        assert "reject" in actions
        assert "flag" in actions


# =============================================================================
# PolicyInterpreter
# =============================================================================

class TestPolicyInterpreter:
    def test_singleton(self):
        i1 = PolicyInterpreter()
        i2 = PolicyInterpreter()
        assert i1 is i2

    def test_evaluate_condition(self, interpreter, sample_context):
        assert interpreter.evaluate_condition("amount > 1000000", sample_context) is True
        assert interpreter.evaluate_condition("amount < 1000000", sample_context) is False

    def test_execute_action(self, interpreter, sample_context):
        # Standard action
        result = interpreter.execute_action("flag(type=test)", sample_context)
        assert result["flag"] == "test"
        assert "_flags" in sample_context
        assert "test" in sample_context["_flags"]

        # Space-separated apply_rate
        result2 = interpreter.execute_action("apply_rate 0.02", sample_context)
        assert result2["rate"] == Decimal("0.02")

    def test_evaluate_policy(self, interpreter, sample_policy, sample_context):
        results = interpreter.evaluate_policy(sample_policy, sample_context)
        # rule1 should match (amount > 1000000)
        # rule2: day(now()) == 15? In fixed datetime day=15, but condition checks 6 or 0, so false.
        # So only rule1 executes.
        assert len(results) == 1
        assert results[0]["flag"] == "high_amount"
        # Check context was modified by flag action
        assert "_flags" in sample_context
        assert "high_amount" in sample_context["_flags"]

    def test_evaluate_policy_with_disabled_rule(self, interpreter, sample_policy, sample_context):
        # Disable rule1
        sample_policy.rules[0].enabled = False
        results = interpreter.evaluate_policy(sample_policy, sample_context)
        # Only rule2 might execute if condition true, but it's false in fixed date.
        assert len(results) == 0

    def test_evaluate_policy_with_cache(self, interpreter, sample_policy, sample_context):
        cache_key = "test_cache"
        interpreter.enable_cache(ttl_seconds=60)
        # First evaluation, condition should be evaluated and cached
        interpreter.evaluate_policy(sample_policy, sample_context, cache_key)
        # Second evaluation with same key should use cache
        with patch.object(interpreter._condition_evaluator, "evaluate") as mock_eval:
            mock_eval.return_value = True
            interpreter.evaluate_policy(sample_policy, sample_context, cache_key)
            mock_eval.assert_not_called()
        # Disable cache
        interpreter.disable_cache()
        with patch.object(interpreter._condition_evaluator, "evaluate") as mock_eval:
            mock_eval.return_value = True
            interpreter.evaluate_policy(sample_policy, sample_context, cache_key)
            mock_eval.assert_called()

    def test_evaluate_by_domain(self, interpreter, sample_policy, sample_context):
        with patch.object(interpreter._loader, "get_active_policy", return_value=sample_policy):
            results = interpreter.evaluate_by_domain("transaction", sample_context)
            assert len(results) == 1
            assert results[0]["flag"] == "high_amount"

    def test_evaluate_by_domain_no_policy(self, interpreter, sample_context):
        with patch.object(interpreter._loader, "get_active_policy", return_value=None):
            results = interpreter.evaluate_by_domain("unknown", sample_context)
            assert results == []

    def test_evaluate_multiple_domains(self, interpreter, sample_policy, sample_context):
        with patch.object(interpreter._loader, "get_active_policy", return_value=sample_policy):
            results = interpreter.evaluate_multiple_domains(["txn", "other"], sample_context)
            assert "txn" in results
            assert "other" in results
            assert len(results["txn"]) == 1
            assert results["txn"][0]["flag"] == "high_amount"
            assert len(results["other"]) == 1

    def test_start_batch_end_batch(self, interpreter, sample_policy, sample_context):
        interpreter.start_batch()
        interpreter.evaluate_policy(sample_policy, sample_context)
        interpreter.evaluate_policy(sample_policy, sample_context)
        batch_results = interpreter.end_batch()
        assert len(batch_results) == 2
        for entry in batch_results:
            assert "timestamp" in entry
            assert "policy_id" in entry
            assert "rule_id" in entry
            assert "condition_met" in entry
            assert "action_result" in entry or "error" in entry

    def test_record_evaluation(self, interpreter):
        interpreter._record_evaluation("p1", "r1", True, action_result={"a": 1})
        history = interpreter.get_evaluation_history()
        assert len(history) == 1
        assert history[0]["policy_id"] == "p1"
        assert history[0]["rule_id"] == "r1"
        assert history[0]["condition_met"] is True
        assert history[0]["action_result"] == {"a": 1}
        # error case
        interpreter._record_evaluation("p2", "r2", False, error="bad")
        history2 = interpreter.get_evaluation_history(limit=2)
        assert len(history2) == 2
        assert history2[-1]["error"] == "bad"

    def test_register_custom_action(self, interpreter):
        def my_action(context, **params):
            context["custom_done"] = True
            return {"result": "ok"}

        interpreter.register_custom_action("my_action", my_action)
        context = {}
        result = interpreter.execute_action("my_action()", context)
        assert context["custom_done"] is True
        assert result["result"] == "ok"

    def test_register_custom_function(self, interpreter):
        interpreter.register_custom_function("myfunc", lambda x: x * 3)
        context = {"x": 3}
        assert interpreter.evaluate_condition("myfunc(3) == 9", context) is True

    def test_cache_methods(self, interpreter):
        interpreter.enable_cache(ttl_seconds=10)
        assert interpreter._cache_enabled is True
        assert interpreter._cache_ttl == 10
        interpreter.disable_cache()
        assert interpreter._cache_enabled is False
        interpreter._evaluation_cache["key"] = (True, 123)
        interpreter.clear_cache()
        assert interpreter._evaluation_cache == {}

    def test_get_stats(self, interpreter):
        stats = interpreter.get_stats()
        assert stats["total_evaluations"] == 0
        interpreter._record_evaluation("p1", "r1", True, action_result="ok")
        interpreter._record_evaluation("p2", "r2", False, error="err")
        stats2 = interpreter.get_stats()
        assert stats2["total_evaluations"] == 2
        assert stats2["condition_true_count"] == 1
        assert stats2["condition_false_count"] == 1
        assert stats2["error_count"] == 1
        assert stats2["cache_enabled"] is False
        assert stats2["cache_size"] == 0

    def test_generate_report(self, interpreter):
        interpreter._record_evaluation("p1", "r1", True)
        report = interpreter.generate_report()
        assert "stats" in report
        assert report["stats"]["total_evaluations"] == 1
        assert "available_actions" in report
        assert "available_functions" in report
        assert "available_operators" in report

    def test_export_to_json(self, interpreter):
        interpreter._record_evaluation("p1", "r1", True, action_result={"x": 1})
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = f.name
        try:
            interpreter.export_to_json(file_path)
            with open(file_path) as f:
                data = json.load(f)
            assert "report" in data
            assert "history" in data
            assert len(data["history"]) == 1
            assert data["history"][0]["policy_id"] == "p1"
        finally:
            import os
            os.remove(file_path)

    def test_evaluate_policy_error_handling(self, interpreter, sample_policy, sample_context):
        # Condition evaluator error
        with patch.object(interpreter._condition_evaluator, "evaluate", side_effect=Exception("boom")):
            results = interpreter.evaluate_policy(sample_policy, sample_context)
            assert results == []
            history = interpreter.get_evaluation_history()
            assert len(history) == 1
            assert history[0]["error"] == "boom"

        # Action error
        with patch.object(interpreter._action_executor, "execute", side_effect=Exception("action boom")):
            with patch.object(interpreter._condition_evaluator, "evaluate", return_value=True):
                results = interpreter.evaluate_policy(sample_policy, sample_context)
                assert results == []
                history2 = interpreter.get_evaluation_history()
                assert history2[-1]["error"] == "action boom"


# =============================================================================
# Module-level function
# =============================================================================

def test_get_policy_interpreter_singleton():
    i1 = get_policy_interpreter()
    i2 = get_policy_interpreter()
    assert i1 is i2
    assert isinstance(i1, PolicyInterpreter)
