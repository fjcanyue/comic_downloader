from __future__ import annotations

import sys
from collections.abc import Mapping

from prompt_toolkit import PromptSession
from prompt_toolkit.buffer import CompletionState
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.output import Output


class CommandCompleter(Completer):
    """Complete only the command word, leaving search terms, URLs and arguments alone."""

    def __init__(self, commands: Mapping[str, str]):
        self.commands = dict(sorted(commands.items()))

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        prefix = document.text_before_cursor.lstrip()
        if document.text_after_cursor or any(char.isspace() for char in prefix):
            return
        if not prefix and not complete_event.completion_requested:
            return
        for command, description in self.commands.items():
            if command.startswith(prefix):
                yield Completion(command, start_position=-len(prefix), display_meta=description)


def create_command_prompt(
    commands: Mapping[str, str], *, input: Input | None = None, output: Output | None = None
) -> PromptSession[str]:
    keys = KeyBindings()
    completer = CommandCompleter(commands)

    @keys.add('tab')
    @keys.add('s-tab')
    def complete(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        reverse = event.key_sequence[0].key == 's-tab'
        state = buffer.complete_state
        if state and state.completions:
            current = state.complete_index
            index = (-1 if reverse else 0) if current is None else current + (-1 if reverse else 1)
            buffer.go_to_completion(index % len(state.completions))
        else:
            # Command names are local and cheap: finish Tab before a queued Enter can execute.
            completions = list(
                completer.get_completions(buffer.document, CompleteEvent(completion_requested=True))
            )
            if completions:
                buffer.complete_state = CompletionState(buffer.document, completions)
                buffer.go_to_completion(len(completions) - 1 if reverse else 0)
                buffer.on_completions_changed.fire()

    @keys.add('escape', filter=Condition(lambda: session.default_buffer.complete_state is not None))
    def cancel_completion(event: KeyPressEvent) -> None:
        event.current_buffer.cancel_completion()

    if sys.platform == 'win32':

        @keys.add('c-z', filter=Condition(lambda: not session.default_buffer.text))
        def eof(event: KeyPressEvent) -> None:
            event.app.exit(exception=EOFError())

    session: PromptSession[str] = PromptSession(
        completer=completer,
        complete_while_typing=True,
        key_bindings=keys,
        input=input,
        output=output,
    )
    return session
