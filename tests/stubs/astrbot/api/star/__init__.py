class Context:
    pass


class Star:
    """桩：最小 Star 基类（不实现 __init_subclass__ 注册）。"""

    def __init__(self, context, config=None):
        self.context = context
        self.config = config or {}

    async def get_kv_data(self, key, default=None):
        return default

    async def put_kv_data(self, key, value):
        return None

    async def delete_kv_data(self, key):
        return None

    async def text_to_image(self, text, return_url=True):
        return None

    async def initialize(self):
        pass

    async def terminate(self):
        pass