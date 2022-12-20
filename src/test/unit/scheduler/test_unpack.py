from multiprocessing import Event

import pytest

from objects.firmware import Firmware
from test.common_helper import get_test_data_dir


@pytest.mark.cfg_defaults(
    {
        'unpack': {
            'threads': '2',
            'max-depth': '3',
            'whitelist': '',
        },
        'expert-settings': {
            'block-delay': '1',
            'unpack-throttle-limit': '10',
        },
    },
)
@pytest.mark.SchedulerTestConfig(dict(start_processes=True))
class TestUnpackScheduler:
    def test_unpack_a_container_including_another_container(self, unpacking_scheduler, post_unpack_queue):
        test_fw = Firmware(file_path=f'{get_test_data_dir()}/container/test_zip.tar.gz')
        unpacking_scheduler.add_task(test_fw)
        outer_container = post_unpack_queue.get(timeout=5)
        assert len(outer_container.files_included) == 2, 'not all children of root found'
        assert (
            'ab4153d747f530f9bc3a4b71907386f50472ea5ae975c61c0bacd918f1388d4b_227' in outer_container.files_included
        ), 'included container not extracted. Unpacker tar.gz modul broken?'
        included_files = [post_unpack_queue.get(timeout=5), post_unpack_queue.get(timeout=5)]
        for item in included_files:
            if item.uid == 'ab4153d747f530f9bc3a4b71907386f50472ea5ae975c61c0bacd918f1388d4b_227':
                assert len(item.files_included) == 1, 'number of files in included container not correct'
            else:
                assert (
                    item.uid == 'faa11db49f32a90b51dfc3f0254f9fd7a7b46d0b570abd47e1943b86d554447a_28'
                ), 'none container file not rescheduled'

    @pytest.mark.skip(reason='TODO this test is useless')
    def test_get_combined_analysis_workload(self, unpacking_scheduler):
        result = unpacking_scheduler._get_combined_analysis_workload()  # pylint: disable=protected-access
        assert result == 3, 'workload calculation not correct'

    @pytest.mark.cfg_defaults(
        {
            'expert-settings': {
                'unpack-throttle-limit': -1,
            }
        }
    )
    @pytest.mark.SchedulerTestConfig(dict(start_processes=False))
    def test_throttle(self, unpacking_scheduler, monkeypatch):
        sleep_was_called = Event()
        with monkeypatch.context() as mkp:
            mkp.setattr('scheduler.unpacking_scheduler.sleep', lambda _: sleep_was_called.set())
            # FIXME Once processes are not started in __init__ anymore call `start` here
            unpacking_scheduler.start_unpack_workers()
            unpacking_scheduler.work_load_process = unpacking_scheduler.start_work_load_monitor()

        sleep_was_called.wait(timeout=10)

        assert unpacking_scheduler.throttle_condition.value == 1, 'unpack load throttle not functional'

        unpacking_scheduler.shutdown()
