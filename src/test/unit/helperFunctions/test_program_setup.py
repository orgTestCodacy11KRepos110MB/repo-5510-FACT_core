import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from helperFunctions.program_setup import get_logging_config, setup_logging
from test.common_helper import get_test_data_dir  # pylint: disable=wrong-import-order


class ArgumentMock:
    config_file = get_test_data_dir() + '/load_cfg_test'
    log_file = '/tmp/fact_test_argument_log_file.log'
    log_level = 'DEBUG'
    silent = False
    debug = False


config_mock = {
    'logging': {
        'logfile-frontend': '/tmp/fact_test_frontend.log',
        'logfile-backend': '/tmp/fact_test_backend.log',
        'logfile-database': '/tmp/fact_test_database.log',
        'loglevel': 'DEBUG',
    }
}


def test_get_logging_config(cfg_tuple):
    cfg, _ = cfg_tuple
    logfile, loglevel = get_logging_config(ArgumentMock, 'frontend')
    assert logfile == ArgumentMock.log_file
    assert loglevel == logging.getLevelName(ArgumentMock.log_level)
    assert cfg.logging.logfile_frontend == logfile

    logfile, loglevel = get_logging_config(ArgumentMock, 'non-default')


def test_setup_logging():
    with TemporaryDirectory(prefix='fact_test_') as tmp_dir:
        log_file_path = tmp_dir + '/factlogfile'
        setup_logging(log_file_path, logging.DEBUG)
        logger = logging.getLogger()
        assert logger.getEffectiveLevel() == logging.NOTSET
        assert Path(log_file_path).exists()
