class SubError(Exception):
    pass

class MessageError(Exception):
    def __init__(self, msg, position):
        super().__init__(msg)
        self.msg = msg
        self.position = position
        end = position.buffer.find('\n', position.lineposition+1)
        if end == -1:
            end = len(position.buffer)
        self.excerpt = position.buffer[position.lineposition:end]
        self.caret = "-" * (position.col) + '^'

    def __str__(self):
        return f"{self.position}\n{self.msg}\n{self.excerpt}\n{self.caret}"


class ParseError(MessageError):
    pass


class AkiSyntaxError(MessageError):
    pass


class CodegenError(MessageError):
    pass


class CodegenWarning(CodegenError):
    def __init__(self, msg, position):
        super().__init__(msg, position)
        self.msg = ">>> warning >>> "+self.msg

    def print(self, instance):
        if not instance.suppress_warnings:
            print(self)


class BlockExit(Exception):
    pass


class ReloadException(Exception):
    pass


class ParameterFormatError(Exception):
    pass
