from __future__ import annotations

from hashlib import md5, new
from shlex import split
from subprocess import run

import ssdeep
import tlsh

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
        functions = _get_list_of_imported_functions(file_object.file_path)
        if functions:
            return md5(','.join(sorted(functions)).encode()).hexdigest()
    return None


def _get_list_of_imported_functions(path: str) -> list[str]:
    '''
    Uses `readelf` from binutils to find all imported symbols in an ELF binary

    :param path: The file path of the ELF file
    :return: a list of all imported symbols
    '''
    output = run(split(f'readelf -sW {path}'), capture_output=True, text=True, check=False).stdout
    symbols = []
    for line in output.splitlines():
        if 'FUNC' not in line:  # we only want functions not objects, etc.
            continue
        size, function = _parse_readelf_line(line)
        if function and size == 0:  # size 0 -> imported function
            if '@' in function:  # may look like <function_name>@<library> but we want only the function name
                function = function[: function.find('@')]
            if len(function) > 20:
                function = f'{function[:17]}...'  # mimic lief (cut off long function names) to match old hashes
            symbols.append(function)
    return sorted(symbols)


def _parse_readelf_line(line: str) -> tuple[int | None, str | None]:
    '''
    readelf -s output looks something like this (the last part is optional):
       Num:    Value          Size Type    Bind   Vis      Ndx Name
         5: 0000000000000000     0 FUNC    GLOBAL DEFAULT  UND free@GLIBC_2.2.5 (3)
    '''
    try:
        _, _, size, _, _, _, _, function, *_ = [w for w in line.split(' ') if w]
        return int(size), function
    except ValueError:
        return None, None


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
