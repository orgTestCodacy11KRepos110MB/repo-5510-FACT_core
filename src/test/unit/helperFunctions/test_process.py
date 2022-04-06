import logging
from time import sleep

import pytest

from helperFunctions.process import ExceptionSafeProcess, check_worker_exceptions, new_worker_was_started


def breaking_process(wait: bool = False):
    if wait:
        sleep(.5)
    raise RuntimeError('now that\'s annoying')


def test_exception_safe_process():
    with pytest.raises(RuntimeError):
        breaking_process()

    process = ExceptionSafeProcess(target=breaking_process)
    process.start()
    process.join()
    assert process.exception
    assert str(process.exception[0]) == 'now that\'s annoying'


@pytest.mark.cfg_defaults({
    'expert-settings': {'throw-exceptions': 'true'}
})
def test_check_worker_exceptions(cfg_tuple):
    _, configparser_cfg = cfg_tuple
    process_list = [ExceptionSafeProcess(target=breaking_process, args=(True, ))]
    process_list[0].start()

    result = check_worker_exceptions(process_list, 'foo', config=configparser_cfg)
    assert not result
    assert len(process_list) == 1
    sleep(1)
    result = check_worker_exceptions(process_list, 'foo', config=configparser_cfg)
    assert result
    assert len(process_list) == 0


@pytest.mark.cfg_defaults({
    'expert-settings': {'throw-exceptions': 'false'}
})
def test_check_worker_restart(caplog, cfg_tuple):
    _, configparser_cfg = cfg_tuple
    worker = ExceptionSafeProcess(target=breaking_process, args=(True, ))
    process_list = [worker]
    worker.start()

    sleep(1)
    with caplog.at_level(logging.INFO):
        result = check_worker_exceptions(process_list, 'foo', configparser_cfg, worker_function=lambda _: None)
        assert not result
        assert len(process_list) == 1
        assert process_list[0] != worker
        assert 'Exception in foo' in caplog.messages[0]
        assert 'restarting foo' in caplog.messages[-1]
        process_list[0].join()


def test_new_worker_was_started():
    def target():
        pass

    old, new = ExceptionSafeProcess(target=target), ExceptionSafeProcess(target=target)

    assert new_worker_was_started(old, new)
    assert not new_worker_was_started(old, old)
