#!/usr/bin/env python3
"""
Unit: CQRS Command Bus and Handler Registry
Menguji pendaftaran handler, dispatch command, dan error handling.
"""

from __future__ import annotations

from application.commands_cqrs.command_bus_unified import Command, CommandBus, CommandResult
from application.commands_cqrs.command_handler_registry import get_command_handler_registry
from application.commands_cqrs.command_validator import CommandValidator


# ============================================================================
# Dummy command classes
# ============================================================================
class DummyCommand(Command):
    def __init__(self, data: str, **kwargs):
        super().__init__(command_type="DummyCommand", **kwargs)
        self.data = data

        class AnotherCommand(Command):
            def __init__(self, value: int, **kwargs):
                super().__init__(command_type="AnotherCommand", **kwargs)
                self.value = value

                # ============================================================================
                # Async handlers (async functions) - required by registry
                # ============================================================================
                async def dummy_handler(cmd: DummyCommand) -> CommandResult:
                    return CommandResult.success(
                        command_id=cmd.command_id, data=f"Processed {cmd.data}"
                    )

                    async def failing_handler(cmd: DummyCommand) -> CommandResult:
                        raise ValueError("Something went wrong")

                        # ============================================================================
                        # Command handler objects with handle method (for CommandBus)
                        # ============================================================================
                        class DummyHandlerObject:
                            def handle(self, cmd: DummyCommand) -> CommandResult:
                                return CommandResult.success(
                                    command_id=cmd.command_id, data=f"Processed {cmd.data}"
                                )

                                class FailingHandlerObject:
                                    def handle(self, cmd: DummyCommand) -> CommandResult:
                                        raise ValueError("Something went wrong")

                                        # ============================================================================
                                        # Tests
                                        # ============================================================================
                                        def test_command_handler_registry_register_and_get():
                                            registry = get_command_handler_registry()
                                            registry.clear()
                                            registry.register_handler("DummyCommand", dummy_handler)
                                            retrieved = registry.get_handler("DummyCommand")
                                            assert retrieved is not None
                                            assert callable(retrieved)

                                            def test_command_handler_registry_raises_for_unregistered():
                                                registry = get_command_handler_registry()
                                                registry.clear()
                                                assert (
                                                    registry.get_handler("UnknownCommand") is None
                                                )
                                                assert (
                                                    registry.has_handler("UnknownCommand") is False
                                                )

                                                def test_command_bus_dispatch_success():
                                                    bus = CommandBus()
                                                    handler = DummyHandlerObject()
                                                    bus.register_handler(DummyCommand, handler)
                                                    cmd = DummyCommand(data="test")
                                                    result = bus.dispatch(cmd)
                                                    assert result.is_success()
                                                    assert result.data == "Processed test"

                                                    def test_command_bus_dispatch_failure():
                                                        bus = CommandBus()
                                                        handler = FailingHandlerObject()
                                                        bus.register_handler(DummyCommand, handler)
                                                        cmd = DummyCommand(data="test")
                                                        result = bus.dispatch(cmd)
                                                        assert result.is_failure()
                                                        assert (
                                                            "Something went wrong" in result.error
                                                        )

                                                        def test_command_validator_validation_passes():
                                                            validator = CommandValidator()

                                                            def validate_dummy(
                                                                cmd: DummyCommand,
                                                            ) -> bool:
                                                                return len(cmd.data) > 0

                                                                validator.add_rule(
                                                                    DummyCommand, validate_dummy
                                                                )
                                                                cmd = DummyCommand(data="valid")
                                                                result = validator.validate(cmd)
                                                                assert result is True

                                                                def test_command_validator_validation_fails():
                                                                    validator = CommandValidator()

                                                                    def validate_dummy(
                                                                        cmd: DummyCommand,
                                                                    ) -> bool:
                                                                        return len(cmd.data) > 0

                                                                        validator.add_rule(
                                                                            DummyCommand,
                                                                            validate_dummy,
                                                                        )
                                                                        cmd = DummyCommand(data="")
                                                                        result = validator.validate(
                                                                            cmd
                                                                        )
                                                                        assert result is False

                                                                        def test_command_bus_with_validation():
                                                                            bus = CommandBus()
                                                                            validator = (
                                                                                CommandValidator()
                                                                            )

                                                                            def validate_dummy(
                                                                                cmd: DummyCommand,
                                                                            ) -> bool:
                                                                                return (
                                                                                    cmd.data != ""
                                                                                )

                                                                                validator.add_rule(
                                                                                    DummyCommand,
                                                                                    validate_dummy,
                                                                                )
                                                                                bus._validator = validator  # Set validator directly
                                                                                handler = DummyHandlerObject()
                                                                                bus.register_handler(
                                                                                    DummyCommand,
                                                                                    handler,
                                                                                )

                                                                                cmd_invalid = (
                                                                                    DummyCommand(
                                                                                        data=""
                                                                                    )
                                                                                )
                                                                                result = (
                                                                                    bus.dispatch(
                                                                                        cmd_invalid
                                                                                    )
                                                                                )
                                                                                assert result.is_failure()
                                                                                assert (
                                                                                    "Validation failed"
                                                                                    in result.error
                                                                                )

                                                                                cmd_valid = (
                                                                                    DummyCommand(
                                                                                        data="ok"
                                                                                    )
                                                                                )
                                                                                result = (
                                                                                    bus.dispatch(
                                                                                        cmd_valid
                                                                                    )
                                                                                )
                                                                                assert result.is_success()
