"""Run-scoped dependency containers for Kibernikto agents.

A ``deps`` object is created by the caller, passed into
:meth:`KiberniktoAgent.run` and mutated in place by tools during the run. It
is the side-channel that lets a tool deliver binary results (images, files,
audio, ...) to the user even though a tool's *return value* only ever flows
back to the model, never to the end user.

The base :class:`KiberniktoDeps` is provider/transport agnostic. Transport
layers subclass it to attach their own context — see
:class:`kibernikto.telegram.agent.telegram_agent.TelegramDeps`.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import BinaryContent, UserContent


@dataclass
class KiberniktoDeps:
    """Base run-scoped dependencies shared by every Kibernikto agent.

    Tools receive this via ``RunContext[KiberniktoDeps]`` and append any binary
    they want delivered to the user to :attr:`attachments`. The reply layer
    sends ``result.output`` (text) together with these attachments after the
    run finishes.
    """

    attachments: list[BinaryContent] = field(default_factory=list)
    """Binaries produced by tools to be delivered to the user (images, files, audio...)."""

    user_message_parts: list[UserContent] = field(default_factory=list)
    """The ``UserContent`` parts that made up the user's request (text, ImageUrl, ...).

    Populated by the transport layer before each run. Tools can inspect it to
    recover originals — e.g. the image tool reuses any ``ImageUrl`` parts for
    image-to-image generation without asking the main model to copy URLs back.
    """

    extra: dict[str, Any] = field(default_factory=dict)
    """Free-form bag for any additional run-scoped data tools want to share."""

    def add_attachment(self, content: BinaryContent) -> None:
        """Queue a single binary for delivery to the user."""
        self.attachments.append(content)

    def add_attachments(self, contents: list[BinaryContent]) -> None:
        """Queue several binaries for delivery to the user."""
        self.attachments.extend(contents)
