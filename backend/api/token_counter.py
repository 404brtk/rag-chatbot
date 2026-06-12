import tiktoken

from .repositories import StoredMessage
from .attachments import load_text_attachment


class TokenCounter:
    @staticmethod
    def _encoding_for_model(model: str):
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            return tiktoken.get_encoding("cl100k_base")

    def estimate_text_tokens(self, text: str, model: str) -> int:
        enc = self._encoding_for_model(model)
        count = len(enc.encode(text))
        if not model.startswith(("gpt-", "text-embedding-", "claude-", "gemini-")):
            return int(count * 1.35)
        return count

    def estimate_message_tokens(self, message: StoredMessage, model: str) -> int:
        image_token_cost = 0
        parts: list[str] = [message.content]

        if message.attachments:
            for att in message.attachments:
                mime = att.get("mimeType", "")
                if mime.startswith("image/"):
                    image_token_cost += 200
                else:
                    filename = att.get("id", "")
                    file_content = load_text_attachment(filename)
                    if file_content:
                        parts.append(
                            f"\n--- File: {att['name']} ---\n{file_content}\n----------------"
                        )
                    else:
                        parts.append(
                            f"\n--- File: {att['name']} ---\nSize: {att['size']} bytes\n----------------"
                        )

        text_to_encode = "".join(parts)
        return 3 + self.estimate_text_tokens(text_to_encode, model) + image_token_cost

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
