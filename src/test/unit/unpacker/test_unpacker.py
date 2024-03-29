# pylint: disable=no-self-use,wrong-import-order
from pathlib import Path

import pytest

from objects.file import FileObject
from storage.unpacking_locks import UnpackingLockManager
from test.common_helper import create_test_file_object, get_test_data_dir
from unpacker.unpack import Unpacker

TEST_DATA_DIR = Path(get_test_data_dir())
EXTRACTION_DIR = TEST_DATA_DIR / 'files'


@pytest.fixture
def unpacker():
    _unpacker = Unpacker(unpacking_locks=UnpackingLockManager())
    yield _unpacker


@pytest.fixture
def test_fo():
    _test_fo = create_test_file_object()
    yield _test_fo


@pytest.mark.cfg_defaults(
    {
        'unpack': {
            'max-depth': '3',
            'whitelist': 'text/plain, image/png',
        },
    }
)
class TestUnpackerCore:
    def test_dont_store_zero_file(self, unpacker, test_fo):
        file_paths = [EXTRACTION_DIR / 'zero_byte', EXTRACTION_DIR / 'get_files_test' / 'testfile1']
        file_objects = unpacker.generate_and_store_file_objects(file_paths, EXTRACTION_DIR, test_fo)
        file_objects = list(file_objects.values())
        assert len(file_objects) == 1, 'number of objects not correct'
        assert file_objects[0].file_name == 'testfile1', 'wrong object created'
        parent_uid = test_fo.uid
        assert f'|{parent_uid}|/get_files_test/testfile1' in file_objects[0].virtual_file_path[test_fo.uid]

    def test_remove_duplicates_child_equals_parent(self, unpacker):
        parent = FileObject(binary=b'parent_content')
        result = unpacker.remove_duplicates({parent.uid: parent}, parent)
        assert len(result) == 0, 'parent not removed from list'

    def test_file_is_locked(self, unpacker, test_fo):
        assert not unpacker.unpacking_locks.unpacking_lock_is_set(test_fo.uid)
        file_paths = [TEST_DATA_DIR / 'get_files_test' / 'testfile1']
        unpacker.generate_and_store_file_objects(file_paths, EXTRACTION_DIR, test_fo)
        assert unpacker.unpacking_locks.unpacking_lock_is_set(test_fo.uid)


@pytest.mark.cfg_defaults(
    {
        'unpack': {
            'max-depth': '3',
            'whitelist': 'text/plain, image/png',
        },
    }
)
class TestUnpackerCoreMain:

    test_file_path = str(TEST_DATA_DIR / 'container/test.zip')

    def main_unpack_check(self, unpacker, test_object, number_unpacked_files, first_unpacker):
        extracted_files = unpacker.unpack(test_object)
        assert len(test_object.files_included) == number_unpacked_files, 'not all files added to parent'
        assert len(extracted_files) == number_unpacked_files, 'not all files found'
        assert test_object.processed_analysis['unpacker']['plugin_used'] == first_unpacker, 'Wrong plugin in Meta'
        assert (
            test_object.processed_analysis['unpacker']['number_of_unpacked_files'] == number_unpacked_files
        ), 'Number of unpacked files wrong in Meta'
        self.check_depths_of_children(test_object, extracted_files)

    @staticmethod
    def check_depths_of_children(parent, extracted_files):
        for item in extracted_files:
            assert item.depth == parent.depth + 1, 'depth of child not correct'

    def test_main_unpack_function(self, unpacker):
        test_file = FileObject(file_path=self.test_file_path)
        self.main_unpack_check(unpacker, test_file, 3, '7z')

    def test_unpacking_depth_reached(self, unpacker):
        test_file = FileObject(file_path=self.test_file_path)
        test_file.depth = 10
        unpacker.unpack(test_file)
        assert 'unpacker' in test_file.processed_analysis
        assert 'maximum unpacking depth was reached' in test_file.processed_analysis['unpacker']['info']
