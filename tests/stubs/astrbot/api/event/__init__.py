"""桩：astrbot.api.event（仅用于本地冒烟测试，不参与线上运行）。"""

# 插件本体用的是 `from astrbot.api.event import filter, AstrMessageEvent`
from . import filter  # noqa: F401


class AstrMessageEvent:
    """桩：仅用于类型标注与测试。"""


class MessageChain:
    def __init__(self, chain=None):
        self.chain = chain or []

    @classmethod
    def message(cls, text):
        return cls(chain=[{"type": "text", "text": text}])

    @classmethod
    def url_image(cls, url):
        return cls(chain=[{"type": "image", "url": url}])

    @classmethod
    def file_image(cls, path):
        return cls(chain=[{"type": "image", "file": path}])

    @classmethod
    def base64_image(cls, b64):
        return cls(chain=[{"type": "image", "base64": b64}])
