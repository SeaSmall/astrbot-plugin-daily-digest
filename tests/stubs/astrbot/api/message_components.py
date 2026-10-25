class Image:
    def __init__(self, file=None, **k):
        self.file = file if file is not None else k.get("url", "")
        self.url = k.get("url", "")

    @classmethod
    def fromBytes(cls, data):
        return cls("base64://stub")


class Plain:
    def __init__(self, text="", **k):
        self.text = text


class File:
    def __init__(self, name="", file="", url=""):
        self.name = name
        self.file = file
        self.url = url