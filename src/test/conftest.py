# pylint: disable=redefined-outer-name
import dataclasses
from multiprocessing import Event, Queue, Value
from typing import List, NamedTuple, Type, TypeVar

import pytest
from pydantic import BaseModel, Extra
from pydantic.dataclasses import dataclass
from pytest import MonkeyPatch

import config
from scheduler.analysis import AnalysisScheduler
from scheduler.comparison_scheduler import ComparisonScheduler
from scheduler.unpacking_scheduler import UnpackingScheduler
from storage.db_connection import ReadOnlyConnection, ReadWriteConnection
from storage.db_interface_admin import AdminDbInterface
from storage.db_interface_backend import BackendDbInterface
from storage.db_interface_common import DbInterfaceCommon
from storage.db_interface_comparison import ComparisonDbInterface
from storage.db_interface_frontend import FrontEndDbInterface
from storage.db_interface_frontend_editing import FrontendEditingDbInterface
from storage.db_interface_stats import StatsUpdateDbInterface
from storage.db_setup import DbSetup
from storage.unpacking_locks import UnpackingLockManager
from test.common_helper import clear_test_tables, setup_test_tables
from test.integration.common import MockDbInterface as BackEndDbInterfaceMock
from test.integration.common import MockFSOrganizer as FSOrganizerMock

T = TypeVar('T')


def merge_markers(request, name: str, dtype: Type[T]) -> T:
    """Merge all markers from closest to farthest. Closer markers overwrite markers that are farther away.

    The marker must either get an instance of ``dtype`` as an argument or have one or more keyword arguments.
    The keyword arguments must be accepted by the ``dtype.__init__``.``

    :param request: The pytest request where the markers will be taken from.
    :param name: The name of the marker.
    :param dtype: The type that the marker should have. Must be a ``pydantic.dataclasses.dataclass`` or ``dict``.

    :return: An instance of ``dtype``.
    """
    _err = ValueError(
        f'The argument(s) to marker {name} must be either an instance of {dtype} or keyword arguments, not both.'
    )
    # Not well documented but iter_markers iterates from closest to farthest
    # https://docs.pytest.org/en/7.1.x/reference/reference.html?highlight=iter_markers#custom-marks
    marker_dict = {}
    for marker in reversed(list(request.node.iter_markers(name))):
        if marker.kwargs and marker.args:
            raise _err

        if marker.kwargs:
            marker_dict.update(marker.kwargs)
        elif marker.args:
            argument = marker.args[0]
            assert isinstance(argument, dtype)
            if isinstance(argument, dict):
                marker_dict.update(argument)
            else:
                marker_dict.update(dataclasses.asdict(argument))
        else:
            raise _err
    return dtype(**marker_dict)


@pytest.fixture
def create_tables():
    """Creates the tables that backend needs.
    This is equivalent to executing ``init_postgres.py``.
    """
    db_setup = DbSetup()
    setup_test_tables(db_setup)
    yield
    clear_test_tables(db_setup)


class DatabaseInterfaces(NamedTuple):
    common: DbInterfaceCommon
    backend: BackendDbInterface
    frontend: FrontEndDbInterface
    frontend_editing: FrontendEditingDbInterface
    admin: AdminDbInterface
    comparison: ComparisonDbInterface
    stats_update: StatsUpdateDbInterface


class MockConfig(BaseModel, extra=Extra.forbid):
    """This class is a mock of ``config.py:Config``.
    It must contain exactly what is needed for everything in the storage module to work.
    This can be found e.g. by using ripgrep: ``rg 'cfg\\.'``.
    """

    class MockDataStorage(BaseModel, extra=Extra.forbid):
        postgres_server: str
        postgres_port: int
        postgres_database: str
        postgres_test_database: str

        postgres_ro_user: str
        postgres_ro_pw: str

        postgres_rw_user: str
        postgres_rw_pw: str

        postgres_del_user: str
        postgres_del_pw: str

        postgres_admin_user: str
        postgres_admin_pw: str

        redis_fact_db: str
        redis_test_db: str
        redis_host: str
        redis_port: int

    data_storage: MockDataStorage


class MockIntercom:
    def __init__(self):
        self.deleted_files = []

    def delete_file(self, uid_list: List[str]):
        self.deleted_files.extend(uid_list)


# FIXME This fixture should have session scope to avoid re-conneting to postgress for every test.
#       Since re-connecting probably isn't that expensive it's fine to do it for now.
# Integration tests test the system as a whole so one can reasonably expect the database to be populated.
@pytest.fixture(scope='function')
def _database_interfaces():
    """Creates the tables that backend needs.
    This is equivalent to executing ``init_postgres.py``.
    """
    # Since this fixture is session scope it cant use the function scoped fixture cfg_tuple.
    # To create the database we need the database section to be loaded.
    # We just patch it here.
    with pytest.MonkeyPatch.context() as mpk:
        config.load()
        # Make sure to match the config here with the one in src/conftest.py:_get_test_config_tuple
        sections = {
            'data-storage': {
                'postgres-server': 'localhost',
                'postgres-port': '5432',
                'postgres-database': 'fact_test',
                'postgres-test-database': 'fact_test',
                'postgres-ro-user': config.cfg.data_storage.postgres_ro_user,
                'postgres-ro-pw': config.cfg.data_storage.postgres_ro_pw,
                'postgres-rw-user': config.cfg.data_storage.postgres_rw_user,
                'postgres-rw-pw': config.cfg.data_storage.postgres_rw_pw,
                'postgres-del-user': config.cfg.data_storage.postgres_del_user,
                'postgres-del-pw': config.cfg.data_storage.postgres_del_pw,
                'postgres-admin-user': config.cfg.data_storage.postgres_del_user,
                'postgres-admin-pw': config.cfg.data_storage.postgres_del_pw,
                'redis-fact-db': config.cfg.data_storage.redis_test_db,  # Note: This is unused in testing
                'redis-test-db': config.cfg.data_storage.redis_test_db,  # Note: This is unused in production
                'redis-host': config.cfg.data_storage.redis_host,
                'redis-port': config.cfg.data_storage.redis_port,
            },
        }

        config._replace_hyphens_with_underscores(sections)
        cfg = MockConfig(**sections)

        mpk.setattr('config._cfg', cfg)

        db_setup = DbSetup()

        ro_connection = ReadOnlyConnection()
        rw_connection = ReadWriteConnection()

        common = DbInterfaceCommon(connection=ro_connection)
        backend = BackendDbInterface(connection=rw_connection)
        frontend = FrontEndDbInterface(connection=ro_connection)
        frontend_editing = FrontendEditingDbInterface(connection=rw_connection)
        comparison = ComparisonDbInterface(connection=rw_connection)
        admin = AdminDbInterface(intercom=MockIntercom())
        stats_update = StatsUpdateDbInterface(connection=rw_connection)

    setup_test_tables(db_setup)

    yield DatabaseInterfaces(common, backend, frontend, frontend_editing, admin, comparison, stats_update)

    clear_test_tables(db_setup)


@pytest.fixture(scope='function')
def database_interfaces(
    _database_interfaces,
) -> DatabaseInterfaces:
    """Returns an object containing all database intefaces.
    The database is emptied after this fixture goes out of scope.
    """
    try:
        yield _database_interfaces
    finally:
        # clear rows from test db between tests
        _database_interfaces.admin.connection.base.metadata.drop_all(bind=_database_interfaces.admin.connection.engine)
        _database_interfaces.admin.connection.base.metadata.create_all(
            bind=_database_interfaces.admin.connection.engine
        )
        # clean intercom mock
        if hasattr(_database_interfaces.admin.intercom, 'deleted_files'):
            _database_interfaces.admin.intercom.deleted_files.clear()


@pytest.fixture
def common_db(database_interfaces):
    """Convinience fixture. Equivalent to ``database_interfaces.common``."""
    yield database_interfaces.common


@pytest.fixture
def backend_db(database_interfaces) -> BackendDbInterface:
    """Convinience fixture. Equivalent to ``database_interfaces.backend``."""
    yield database_interfaces.backend


@pytest.fixture
def frontend_db(database_interfaces):
    """Convinience fixture. Equivalent to ``database_interfaces.frontend``."""
    yield database_interfaces.frontend


@pytest.fixture
def frontend_editing_db(database_interfaces):
    """Convinience fixture. Equivalent to ``database_interfaces.frontend_editing``."""
    yield database_interfaces.frontend_editing


@pytest.fixture
def admin_db(database_interfaces):
    """Convinience fixture. Equivalent to ``database_interfaces.admin``."""
    yield database_interfaces.admin


@pytest.fixture
def comparison_db(database_interfaces):
    """Convinience fixture. Equivalent to ``database_interfaces.comparison``."""
    yield database_interfaces.comparison


@pytest.fixture
def stats_update_db(database_interfaces):
    """Convinience fixture. Equivalent to ``database_interfaces.stats_update``."""
    yield database_interfaces.stats_update


@pytest.fixture
def post_analysis_queue() -> Queue:
    """A Queue in which the arguments of :py:func:`AnalysisScheduler.post_analysis` are put whenever it is called."""
    yield Queue()


@pytest.fixture
def pre_analysis_queue() -> Queue:
    """A Queue in which the arguments of :py:func:`AnalysisScheduler.pre_analysis` are put whenever it is called."""
    yield Queue()


@pytest.fixture
def analysis_finished_event() -> Event:
    """An event that is set once the :py:func:`analysis_scheduler` has analyzed
    :py:attribute:`SchedulerTestConfig.items_to_analyze` items.

    .. seealso::

       The documentation of :py:class:`SchedulerTestConfig`."""
    yield Event()


@pytest.fixture
def analysis_finished_counter() -> Value:
    """A :py:class:`Value` counting how many analysies are finished."""
    return Value('i', 0)


@pytest.fixture
def analysis_scheduler(
    request,
    pre_analysis_queue,
    post_analysis_queue,
    analysis_finished_event,
    analysis_finished_counter,
) -> AnalysisScheduler:
    """Returns an instance of :py:class:`~scheduler.analysis.AnalysisScheduler`.
    The scheduler has some extra testing features. See :py:class:`SchedulerTestConfig` for the features.
    """
    test_config = merge_markers(request, 'SchedulerTestConfig', SchedulerTestConfig.get_subclass_from_request(request))

    # FIXME Don't patch
    # The reason for patching is documented in :py:func:`AnalysisScheduler.start`.
    with MonkeyPatch.context() as mkp:
        mkp.setattr(AnalysisScheduler, '_load_plugins', lambda _: None)
        _analysis_scheduler = AnalysisScheduler(
            pre_analysis=lambda _: None,
            post_analysis=lambda *_: None,
            unpacking_locks=UnpackingLockManager(),
        )

    _analysis_scheduler.db_backend_service = test_config.backend_db_class()

    def _pre_analysis_hook(fw):
        pre_analysis_queue.put(fw)
        if test_config.pipeline:
            _analysis_scheduler.db_backend_service.add_object(fw)

    _analysis_scheduler.pre_analysis = _pre_analysis_hook

    def _post_analysis_hook(*args):
        post_analysis_queue.put(args)
        analysis_finished_counter.value += 1
        # We use == here insead of >= to not set the thing when items_to_analyze is 0
        if analysis_finished_counter.value == test_config.items_to_analyze:
            analysis_finished_event.set()

        if test_config.pipeline:
            _analysis_scheduler.db_backend_service.add_analysis(*args)

    # test_unpack_and_analyse.py
    _analysis_scheduler.post_analysis = _post_analysis_hook

    def _instanciate_plugin_wo_starting(plugin_class):
        with MonkeyPatch.context() as mkp:
            mkp.setattr(plugin_class, 'start', lambda _: None)

        return plugin_class

    # FIXME This is a hack
    # We want to load plugins but don't actually start them
    # Due to a bug which is documented in AnalysisScheduler._load_plugins we have to do it really wired
    with MonkeyPatch.context() as mkp:
        if not test_config.start_processes:
            mkp.setattr(_analysis_scheduler, '_instanciate_plugin', _instanciate_plugin_wo_starting)
        _analysis_scheduler._load_plugins()

    if test_config.start_processes:
        _analysis_scheduler.start()

    yield _analysis_scheduler
    # TODO scope: Maybe get inspired by the database_interface fixture.
    # Have a module scoped thing, then have a function scoped thing that makes sure that all queues are reset.
    # This would prevent calling exec and fork for every test function
    # But we have to make sure that the config is the one set for the very specific function in

    if test_config.start_processes:
        _analysis_scheduler.shutdown()


@pytest.fixture
def post_unpack_queue() -> Queue:
    """A queue that is filled with the arguments of post_unpack of the unpacker"""
    yield Queue()


@pytest.fixture
def unpacking_scheduler(request, post_unpack_queue) -> UnpackingScheduler:
    """Returns an instance of :py:class:`~scheduler.unpacking_scheduler.UnpackingScheduler`.
    The scheduler has some extra testing features. See :py:class:`SchedulerTestConfig` for the features.
    """
    test_config = merge_markers(request, 'SchedulerTestConfig', SchedulerTestConfig.get_subclass_from_request(request))
    if test_config.pipeline:
        _analysis_scheduler = request.getfixturevalue('analysis_scheduler')

    _unpacking_scheduler = UnpackingScheduler(
        post_unpack=lambda _: None,
        fs_organizer=None,
        # TODO must this be the same as in analysis_scheduler?
        unpacking_locks=UnpackingLockManager(),
    )

    _unpacking_scheduler.fs_organizer = test_config.fs_organizer_class()

    def _post_unpack_hook(fw):
        post_unpack_queue.put(fw)
        if test_config.pipeline:
            _analysis_scheduler.start_analysis_of_object(fw)

    _unpacking_scheduler.post_unpack = _post_unpack_hook

    if test_config.start_processes:
        _unpacking_scheduler.start()

    yield _unpacking_scheduler

    if test_config.start_processes:
        _unpacking_scheduler.shutdown()


@pytest.fixture
def comparison_finished_event() -> Event:
    """The retunred event is set once the comparison_scheduler is finished comparing.
    Note that the event must be reset if you want to compare multiple firmwares in one test.
    """
    yield Event()


@pytest.fixture
def comparison_scheduler(request, comparison_finished_event) -> ComparisonScheduler:
    """Returns an instance of :py:class:`~scheduler.comparison_scheduler.ComparisonScheduler`.
    The scheduler has some extra testing features. See :py:class:`SchedulerTestConfig` for the features.
    """
    test_config = merge_markers(request, 'SchedulerTestConfig', SchedulerTestConfig.get_subclass_from_request(request))
    _comparison_scheduler = ComparisonScheduler()

    _comparison_scheduler.db_interface = test_config.comparison_db_class()

    def _callback_hook():
        comparison_finished_event.set()

    _comparison_scheduler.callback = _callback_hook

    if test_config.start_processes:
        _comparison_scheduler.start()

    yield _comparison_scheduler

    if test_config.start_processes:
        _comparison_scheduler.shutdown()


@dataclass
class SchedulerTestConfig:
    """A declarative class that describes the desired behavior for the fixtures :py:func:`~analysis_finished_event`,
     :py:func:`unpacking_scheduler` and :py:func:`comparison_scheduler`.

    The fixtures don't do any assertions, they MUST be done by the test using the fixtures.
    """

    #: The amount of items that the :py:class:`~scheduler.analysis.AnalysisScheduler` must analyze before
    #: :py:func:`analysis_finished_event` gets set.
    items_to_analyze: int = 0
    #: Set the class that is used as :py:class:`~storage.db_interface_backend.BackendDbInterface`.
    #: This can be either a mocked class or the actual :py:class:`~storage.db_interface_backend.BackendDbInterface`.
    #: This is used by the :py:func:`analysis_scheduler`
    backend_db_class: Type = BackEndDbInterfaceMock
    #: Set the class that is used as :py:class:`~storage.db_interface_comparison.ComparisonDbInterface`.
    #: This can be either a mocked class or the actual :py:class:`~storage.db_interface_comparison.ComparisonDbInterface`.
    #: This is used by the :py:func:`comparison_scheduler`
    comparison_db_class: Type = ComparisonDbInterface
    #: Set the class that is used as :py:class:`~storage.fsorganizer.FSOrganizer`.
    #: This can be either a mocked class or the actual :py:class:`~storage.fsorganizer.FSOrganizer`.
    #: This is used by the :py:func:`unpacking_scheduler`
    fs_organizer_class: Type = FSOrganizerMock
    #: If set to ``True`` the :py:func:`unpacking_scheduler` and :py:func:`analysis_scheduler` are connected via their
    #: hooks.
    #: To be percise the analysis is started after unpacking.
    #: Also the objects to be analysed and the finished analysis is added to the backend database.
    pipeline: bool = False
    #: If set to ``False`` no processes will be started.
    start_processes: bool = True

    @staticmethod
    def get_subclass_from_request(request: pytest.FixtureRequest) -> Type['SchedulerTestConfig']:
        err = ValueError(f'{request.module} is neither a unit,acceptance or integration test')

        modules = request.module.__name__.split('.')
        if len(modules) < 2:
            raise err
        test_type = modules[1]
        if test_type == 'unit':
            from test.unit.conftest import SchedulerUnitTestConfig

            return SchedulerUnitTestConfig
        elif test_type == 'acceptance':
            from test.acceptance.conftest import SchedulerAcceptanceTestConfig

            return SchedulerAcceptanceTestConfig
        elif test_type == 'integration':
            from test.integration.conftest import SchedulerIntegrationTestConfig

            return SchedulerIntegrationTestConfig
        else:
            raise err
