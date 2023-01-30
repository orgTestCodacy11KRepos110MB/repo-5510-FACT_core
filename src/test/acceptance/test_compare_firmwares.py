import pytest

from test.acceptance.conftest import SchedulerAcceptanceTestConfig, upload_test_firmware


def _add_firmwares_to_compare(test_client, test_fw_a, test_fw_c):
    rv = test_client.get(f'/analysis/{test_fw_a.uid}')
    assert test_fw_a.uid in rv.data.decode()
    rv = test_client.get(f'/comparison/add/{test_fw_a.uid}', follow_redirects=True)
    assert 'Firmware Selected for Comparison' in rv.data.decode()

    rv = test_client.get(f'/analysis/{test_fw_c.uid}')
    assert test_fw_c.uid in rv.data.decode()
    assert test_fw_c.name in rv.data.decode()
    rv = test_client.get(f'/comparison/add/{test_fw_c.uid}', follow_redirects=True)
    assert 'Remove All' in rv.data.decode()


def _start_compare(test_client):
    rv = test_client.get('/compare', follow_redirects=True)
    assert b'Your compare task is in progress.' in rv.data, 'compare wait page not displayed correctly'


def _show_comparison_results(test_client, test_fw_a, test_fw_c):
    rv = test_client.get(f'/compare/{test_fw_a.uid};{test_fw_c.uid}')
    assert test_fw_a.name.encode() in rv.data, 'test firmware a comparison not displayed correctly'
    assert test_fw_c.name.encode() in rv.data, 'test firmware b comparison not displayed correctly'
    assert b'File Coverage' in rv.data, 'comparison page not displayed correctly'


def _show_home_page(test_client):
    rv = test_client.get('/')
    assert b'Latest Comparisons' in rv.data, 'latest comparisons not displayed on "home"'


def _show_compare_browse(test_client, test_fw_a):
    rv = test_client.get('/database/browse_compare')
    assert test_fw_a.name.encode() in rv.data, 'no compare result shown in browse'


def _show_analysis_without_compare_list(test_client, test_fw_a):
    rv = test_client.get(f'/analysis/{test_fw_a.uid}')
    assert b'Show list of known comparisons' not in rv.data


def _show_analysis_with_compare_list(test_client, test_fw_a):
    rv = test_client.get(f'/analysis/{test_fw_a.uid}')
    assert b'Show list of known comparisons' in rv.data


@pytest.mark.SchedulerTestConfig(
    SchedulerAcceptanceTestConfig(
        # 8 files and 2 plugins
        items_to_analyze=8
        * 2,
    ),
)
@pytest.mark.usefixtures('intercom_backend_binding')
@pytest.mark.skip(reason='TODO see code')
def test_compare_firmwares(test_fw_a, test_fw_c, test_client, analysis_finished_event, comparison_finished_event):
    # TODO somehow using test_fw_c prevents the analysis_scheduler from properly shutting down
    # ```
    # @pytest.mark.SchedulerTestConfig(dict(items_to_analyze=16))
    # @pytest.mark.usefixtures("intercom_backend_binding")
    # def test_bar(test_fw_a, test_fw_c, test_client, analysis_finished_event):
    #     upload_test_firmware(test_client, test_fw_a)
    #     upload_test_firmware(test_client, test_fw_c)
    #     assert analysis_finished_event.wait(timeout=20)
    # ```
    for firmware in [test_fw_a, test_fw_c]:
        upload_test_firmware(test_client, firmware)
    assert analysis_finished_event.wait(timeout=20)
    _show_analysis_without_compare_list(test_client, test_fw_a)
    _add_firmwares_to_compare(test_client, test_fw_a, test_fw_c)
    _start_compare(test_client)
    assert comparison_finished_event.wait(timeout=20)
    _show_comparison_results(test_client, test_fw_a, test_fw_c)
    _show_home_page(test_client)
    _show_compare_browse(test_client, test_fw_a)
    _show_analysis_with_compare_list(test_client, test_fw_a)
