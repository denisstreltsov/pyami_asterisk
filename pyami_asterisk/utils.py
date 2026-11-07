import uuid

EOL = b"\r\n"


def _convert_bytes_to_dict(data: bytes) -> dict:
    """Parse one AMI packet into a dict.

    A key repeated in the packet (``Variable``, ``Output``, ...) maps to a list of all its values in
    order; other keys map to a string. A value containing ``": "`` is kept whole. A line without
    ``": "`` is a key with an empty value when it is ``Key:``, otherwise it is raw text (as in the answer
    to a legacy ``Command`` action) and is collected under ``Output``.
    """
    response = {}
    for line in data.decode("utf-8", errors='ignore').split(EOL.decode()):
        if line == "":
            continue
        key, sep, value = line.partition(": ")
        if not sep:
            if line.endswith(":") and " " not in line:
                key, value = line[:-1], ""
            else:
                key, value = "Output", line
        if key not in response:
            response[key] = value
        elif isinstance(response[key], list):
            response[key].append(value)
        else:
            response[key] = [response[key], value]
    return response


def _to_text(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _convert_dict_to_bytes(data: dict) -> bytes:
    """Write an action as one AMI packet.

    A list or tuple value is written as one line per item. Non-string values are written as text
    (``True``/``False`` as ``true``/``false``); a ``None`` value leaves the key out. A key or value
    containing CR or LF would inject extra lines into the packet and is refused with ``ValueError``.
    """
    lines = []
    for key, value in data.items():
        if value is None:
            continue
        key = _to_text(key)
        for item in value if isinstance(value, (list, tuple)) else [value]:
            item = _to_text(item)
            if "\r" in key or "\n" in key or "\r" in item or "\n" in item:
                raise ValueError(f"AMI action field {key!r} contains CR or LF")
            lines.append(key + ": " + item + EOL.decode())
    return ("".join(lines) + EOL.decode()).encode()


class IdGenerator:
    """Generate some uuid for actions:"""

    # 1.5.2 appended every instance here and never freed them; kept (empty) for compatibility
    instances = []

    def __init__(self, prefix):
        self.prefix = prefix
        self.uid = str(uuid.uuid4())
        self.generator = self.get_generator()

    def get_generator(self):
        i = 0
        max_val = 10000
        while True:
            yield "%s/%s/%d/%d" % (self.prefix, self.uid, (i // max_val) + 1, (i % max_val) + 1)
            i += 1

    def __call__(self):
        return next(self.generator)

    def __repr__(self):
        return "<%s prefix:%s (uid:%s)>" % (self.__class__.__name__, self.prefix, self.uid)
