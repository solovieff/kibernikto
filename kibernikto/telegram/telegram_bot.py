from kibernikto.interactors import OpenAIExecutor, OpenAiExecutorConfig


class TelegramBot(OpenAIExecutor):
    def __init__(self, config: OpenAiExecutorConfig, master_id, username):
        self.master_id = master_id
        self.username = username
        super().__init__(config=config)

    def should_react(self, message_text):
        if not message_text:
            return False
        parent_should = super().should_react(message_text)
        return parent_should or self.username in message_text

    def check_master(self, user_id, message):
        return self.master_call in message or user_id == self.master_id
