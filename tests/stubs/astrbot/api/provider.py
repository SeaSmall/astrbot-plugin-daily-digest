class ProviderRequest:
    def __init__(self):
        self.extra_user_content_parts = []


class LLMResponse:
    def __init__(self, text=""):
        self.completion_text = text
        self.result = text
        self.text = text