from openai._types import NOT_GIVEN

from kibernikto.interactors import OpenAIExecutor, OpenAiExecutorConfig


class TelegramBot(OpenAIExecutor):
    def __init__(self, config: OpenAiExecutorConfig, master_id, username, key=NOT_GIVEN):
        self.key = key
        self.master_id = master_id
        self.username = username
        super().__init__(config=config)

    def should_react(self, message_text):
        if not message_text:
            return False
        parent_should = super().should_react(message_text)
        mt_lower = message_text.lower()
        if self.full_config.name.lower() in mt_lower:
            return True
        return parent_should or self.username.lower() in mt_lower

    def check_master(self, user_id, message):
        return self.master_call in message or user_id == self.master_id
