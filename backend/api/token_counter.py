import tiktoken

from .repositories import StoredMessage


class TokenCounter:
    @staticmethod
    def _encoding_for_model(model: str):
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            return tiktoken.get_encoding("cl100k_base")

    def estimate_text_tokens(self, text: str, model: str) -> int:
        enc = self._encoding_for_model(model)
        return len(enc.encode(text))

    def estimate_message_tokens(self, message: StoredMessage, model: str) -> int:
        return 3 + self.estimate_text_tokens(message.content, model)

    def estimate_system_tokens(self, system_prompt: str, model: str) -> int:
        if not system_prompt.strip():
            return 0
        return 3 + self.estimate_text_tokens(system_prompt, model)

    def truncate_text_to_max_tokens(
        self, text: str, model: str, max_tokens: int
    ) -> str:
        if max_tokens <= 0:
            return ""
        enc = self._encoding_for_model(model)
        ids = enc.encode(text)
        if len(ids) <= max_tokens:
            return text
        return enc.decode(ids[:max_tokens]).strip()
