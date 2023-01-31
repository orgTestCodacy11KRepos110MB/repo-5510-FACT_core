import datetime
import abc
import typing
import time
import queue
import logging
from objects.file import FileObject
import io

from multiprocessing import Queue, Process
from pydantic.dataclasses import dataclass
import dataclasses
import signal

# Design:
# Feststellung 1: Ein Plugin braucht keinen State. Jede Datei wird unabhängig analysiert,
# also muss man nichts außerhalb von lokalen Variablen in der `analyze` (früher `process_object`)
# speichern.
# Feststellung 2: Ein plugin "Worker" hat erstmal nichts mit der Klasse des Plugins zu tun.
# Ein plugin muss im wesentlichen nur eine datei analysieren, mit wie vielen Prozessen das gestartet wird
# usw. gehört eher in den Aufgabenbereich des Schedulers.
#
# Diese beiden Feststellungen motivieren die Klassen Worker und PluginRunner.
#
# Um zu Testen ob das ganze prinzipiell klappt und wie aufwendig die implementation ist habe ich die Klasse
# `AnalysisBasePluginAdapterMixin` geschrieben.
#
#
# Offene Fragen:
# - Die Namensgebung von `analyze`, `Analysis` und `get_analysis` ist etwas verwirrend.
#     * Was genau ist jetzt eine Analyse? Nur das "result" oder das result mit Metadaten?
# - Ist die Trennung von AnalysisBasePlugin in PluginV1, PluginRunner und Worker prinzipiell eine gute Idee?
# - Beziehung der Klassen `Analysis` und `schema.AnalysisEntry`?
#     * Beide Klassen sind sehr ähnlich und beschreiben mehr oder weniger das gleiche.
#     * Vielleicht ist eine Methode à la `AnalysisEntry.fromAnalysis(a: Analysis)` gut`?
#
# - Argumente der Methode `analyze`?
#     * Dateipfad um cli tools darauf laufen zu lassen
#     * FileHandle um die Dateil zu lesen (Vielleicht `io.FileIO` in lazy, also die Datei wird erst geöffnet,
#           wenn man z.B. read aufruft?)
#     * Virtual file path
#     * Sonst noch etwas?
#
# Probleme:
# - Der Scheduler Code ist insgesamt etwas unstrukturiert und unklar.
#     * Durch die Trennung von AnalysisBasePlugin in PluginV1, PluginRunner und Worker
#         muss der Scheudler code auch etwas verändert werden.
# - Mit jeder Revision des PluginV{1,2,..} muss der Scheduler angepasst werden.
#     * Idee: Mixins die mit minmaler Anpassung erlauben die neuen plugins so wie die alten zu benutzen.
#         Beim der geplanten überarbeitung des Schedulers kann man dann alles auf die neuen Plugins anpassen.
#         Bis dahin ist die PluinVN Klasse optimalerweise so weit, dass wir keine größeren Änderungen mehr erwarten.
# - AnalysisBasePluginAdapterMixin kann ohne Weiteres nicht die volle Funktionalität vom AnalysisBasePlugin bieten
#


# https://docs.mdanalysis.org/stable/_modules/MDAnalysis/lib/picklable_file_io.html#FileIOPicklable
# Lizens?!
class PickelableFileIO(io.FileIO):
    def __init__(self, name, mode='r'):
        self._mode = mode
        super().__init__(name, mode)

    def __getstate__(self):
        if self._mode != 'r':
            raise RuntimeError("Can only pickle files that were opened "
                               "in read mode, not {}".format(self._mode))
        return self.name, self.tell()

    def __setstate__(self, args):
        name = args[0]
        super().__init__(name, mode='r')
        self.seek(args[1])



class AnalysisBasePluginAdapterMixin:
    """A mixin that makes PluginV1 compatible to AnalysisBasePlugin"""

    @property
    def FILE(self):
        # What is this even used for?
        return None

    @property
    def NAME(self):
        return self.metadata.name

    @property
    def DESCRIPTION(self):
        return self.metadata.description

    @property
    def DEPENDENCIES(self):
        return self.metadata.dependencies

    @property
    def VERSION(self):
        return self.metadata.version

    @property
    def RECURSIVE(self):
        return False

    @property
    def TIMEOUT(self):
        return 10

    @property
    def SYSTEM_VERSION(self):
        return self.metadata.version

    @property
    def MIME_BLACKLIST(self):
        return self.metadata.mime_blacklist

    @property
    def MIME_WHITELIST(self):
        return self.metadata.mime_whitelist

    @property
    def ANALYSIS_STATS_LIMIT(self):
        return 1000

    def shutdown(self):
        # TODO we should know the runners here
        return None


@dataclass
class Analysis:
    #: A single human readable sentence describing the result
    summary: str
    #: The ``datetime.datetime`` when the analysis was started
    start_time: datetime.datetime
    #: The name of the plugin
    plugin: str
    #: The version of the plugin
    plugin_version: str
    #: The result of the plugin.
    #: MUST match the `:py:class:PluginV1.MetaData.Schema` of the plugin.
    result: object


class PluginV1(metaclass=abc.ABCMeta):
    """An abstract class that all analysis plugins must inherit from.

    This class MAY NOT depend on FACT_core code.
    """
    @dataclass
    class MetaData:
        """A class containing all metadata that describes the plugin"""
        #: Name of the plugin
        name: str
        #: The plugins description
        #: Must be a single sentence
        description: str
        #: The version of the plugin
        #: MUST adhere to semantic versioning
        version: str
        #: A list of all plugins that this plugin depends on
        dependencies: list[str]
        #: List of mimetypes that should not be processed
        mime_blacklist: list
        #: List of mimetypes that should be processed
        mime_whitelist: list
        #: Pydantic dataclass of the object returned by `py:func:analyse`
        Schema: typing.Type

    def __init__(self, metadata: MetaData):
        self.metadata: PluginV1.MetaData = metadata

    # The type of MetaData.Schema
    Schema = typing.TypeVar("T")

    @abc.abstractmethod
    def summarize(self, result: Schema) -> str:
        """Returns a string that summarizes the analysis

        :param result: The analysis as returned by TODO
        """

    @abc.abstractmethod
    def analyze(self, file_handle) -> Schema:
        """Analyze an binary.

        :param file_handle: The file contents.
        """

    @typing.final
    def get_analysis(self, file_handle) -> Analysis:
        start_time = datetime.datetime.now()
        result = self.analyze(file_handle)
        summary = self.summarize(result)

        return Analysis(
            start_time=start_time,
            summary=summary,
            result=result,
            plugin=self.metadata.name,
            plugin_version=self.metadata.version,
        )


class PluginRunner:

    @dataclass
    class Config:
        """A class containing all parameters of the runner"""
        process_count: int
        delay: int
        #: Timeout in seconds after which the analysis is aborted
        timeout: int

    @dataclass(config=dict(arbitrary_types_allowed=True))
    class Task:
        file_handle: object
        file_object: FileObject

    def __init__(self, plugin: PluginV1, config: Config):
        self._plugin = plugin
        self._config = config

        self._in_queue = Queue()
        self.out_queue = Queue()
        self.out_queue.close()

        worker_config = Worker.Config(
            delay=self._config.delay,
            timeout=self._config.timeout,
        )
        self._workers = [Worker(
            plugin=plugin,
            config=worker_config,
            in_queue=self._in_queue,
            out_queue=self.out_queue,
        ) for _ in range(self._config.process_count)]

    def start(self):
        for worker in self._workers:
            worker.start()

    def shutdown(self):
        for worker in self._workers:
            worker.terminate()

    def queue_analysis(self, file_object):
        self._in_queue.put(PluginRunner.Task(
            file_handle=PickelableFileIO(file_object.file_path),
            file_object=file_object,
        ))


class Worker:
    # Extends BaseException instead of Exception to avoid beeing caught by `except Exception`.
    class _TimeoutException(BaseException):
        """Raised when the analysis times out"""

    @dataclass
    class Config:
        """A class containing all parameters of the worker"""
        delay: int
        #: Timeout in seconds after which the analysis is aborted
        timeout: int

    def __init__(self, plugin: PluginV1, config: Config, in_queue: Queue, out_queue: Queue):
        self._plugin = plugin
        self._config = config

        self._in_queue = in_queue
        self._in_queue.close()
        self._out_queue = out_queue

        self._process = Process(
            target=self._entrypoint,
            name=f"{plugin.metadata.name} worker",
        )

    def start(self):
        self._process.start()

    def terminate(self):
        self._process.terminate()

    def _entrypoint(self):
        """Entrypoint for the worker processes."""
        run = True

        def _handle_sigterm(signum, frame):
            del signum, frame
            logging.critical(f"{self._process} received SIGTERM. Shutting down.")
            nonlocal run
            run = False

        signal.signal(signal.SIGTERM, _handle_sigterm)

        def _raise_timeout(signum, frame):
            del signum, frame
            raise Worker._TimeoutException()

        signal.signal(signal.SIGALRM, _raise_timeout)

        while run:
            try:
                # We must have some delay here to avoid blocking even after _handle_sigterm is called
                task = self._in_queue.get(self._config.delay)
                file_object = task.file_object
                file_handle = task.file_handle
            except queue.Empty:
                continue

            signal.alarm(self._config.timeout)
            try:
                analysis = self._plugin.get_analysis(file_handle)
                signal.alarm(0)
                # Dont like any of the logic here. The logic should reside somewhere else imo.
                processed_analysis = {
                    analysis.plugin: {
                        "analysis_date": time.mktime(analysis.start_time.timetuple()),
                        "plugin_version": analysis.plugin_version,
                        "system_version": analysis.plugin_version,
                        "result": dataclasses.asdict(analysis.result),
                        "summary": analysis.summary,
                    },
                }

                file_object.processed_analysis.update(processed_analysis)
                logging.critical(file_object.processed_analysis)
            except Worker._TimeoutException:
                logging.critical(f"{self._process} timed out after {self._config.timeout} seconds.")
                file_object.analysis_exception = (self._plugin.metadata.name, "Analysis timed out")
            except Exception as e:
                logging.critical(f"{self._process} got a exception during analysis: {e}")
                file_object.analysis_exception = (self._plugin.metadata.name, "Analysis threw an exception")

            self._out_queue.put(file_object)


