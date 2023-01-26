from __future__ import annotations

import logging
from hashlib import md5, new

import ssdeep
import tlsh
from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile

from helperFunctions.data_conversion import make_bytes

ELF_MIME_TYPES = ['application/x-executable', 'application/x-object', 'application/x-sharedlib']


def get_hash(hash_function, binary):
    '''
    Hashes binary with hash_function.

    :param hash_function: The hash function to use. See hashlib for more
    :param binary: The data to hash, either as string or array of Integers
    :return: The hash as hexstring
    '''
    binary = make_bytes(binary)
    raw_hash = new(hash_function)
    raw_hash.update(binary)
    string_hash = raw_hash.hexdigest()
    return string_hash


def get_sha256(code):
    return get_hash('sha256', code)


def get_md5(code):
    return get_hash('md5', code)


def get_ssdeep(code):
    binary = make_bytes(code)
    raw_hash = ssdeep.Hash()
    raw_hash.update(binary)
    return raw_hash.digest()


def get_tlsh(code):
    tlsh_hash = tlsh.hash(make_bytes(code))  # pylint: disable=c-extension-no-member
    return tlsh_hash if tlsh_hash != 'TNULL' else ''


def get_tlsh_comparison(first, second):
    return tlsh.diff(first, second)  # pylint: disable=c-extension-no-member


def get_imphash(file_object) -> str | None:
    '''
    Generates and returns the md5 hash of the (sorted) imported functions of an ELF file represented by `file_object`.
    Returns `None` if there are no imports or if an exception occurs.

    :param file_object: The FileObject of which the imphash shall be computed
    '''
    if _is_elf_file(file_object):
        try:
            functions = _get_list_of_imported_functions(file_object.file_path)
            if functions:
                return md5(','.join(sorted(functions)).encode()).hexdigest()
        except Exception:  # pylint: disable=broad-except # we must not crash here as this is used by a mandatory plugin
            logging.exception(f'Could not compute imphash for {file_object.file_path}')
    return None


def _get_list_of_imported_functions(path: str) -> list[str]:
    try:
        with open(path, 'rb') as fp:
            imports = [
                s.name
                for s in ELFFile(fp).get_section_by_name('.dynsym').iter_symbols()
                if s.name and s.entry.st_info['type'] == 'STT_FUNC' and s.entry.st_size == 0  # size 0 -> imported
            ]
            # mimic lief (cut off long function names) to match old hashes
            return sorted(f if len(f) <= 20 else f'{f[:17]}...' for f in imports)
    except (ELFError, AttributeError):  # not an ELF file or no .dynsym section -> no imports
        return []


def _is_elf_file(file_object):
    return file_object.processed_analysis['file_type']['mime'] in ELF_MIME_TYPES


def normalize_lief_items(functions):
    '''
    Shorthand to convert a list of objects to a list of strings
    '''
    return [str(function) for function in functions]


class _StandardOutWriter:
    def write(self, _):
        pass
