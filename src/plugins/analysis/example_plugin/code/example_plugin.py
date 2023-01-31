from plugins import analysis
from pydantic import dataclasses
import io


@dataclasses.dataclass
class ResultSchema:
    number: int
    name: str
    first_byte: str


class AnalysisPlugin(analysis.PluginV1, analysis.AnalysisBasePluginAdapterMixin):
    def __init__(self):
        metadata = analysis.PluginV1.MetaData(
            name="ExamplePlugin",
            description="An example description",
            version="0.0.0",
            mime_blacklist=[],
            mime_whitelist=[],
            dependencies=[],
            Schema=ResultSchema,
        )
        super().__init__(
            metadata=metadata,
        )

    def summarize(self, result):
        del result
        return "This is a good summary"

    def analyze(self, file_handle: io.FileIO):
        first_byte = file_handle.read(1)
        return ResultSchema(
            number=42,
            name=file_handle.name,
            first_byte=first_byte.hex(),
        )
