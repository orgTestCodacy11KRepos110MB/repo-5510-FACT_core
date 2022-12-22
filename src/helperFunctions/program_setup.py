'''
    Firmware Analysis and Comparison Tool (FACT)
    Copyright (C) 2015-2019  Fraunhofer FKIE

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import argparse
import logging
import sys

from common_helper_files import create_dir_for_file

from config import cfg
from helperFunctions.logging import ColoringFormatter
from version import __VERSION__


def setup_argparser(name, description, command_line_options=sys.argv, version=__VERSION__):
    '''
    Sets up an ArgumentParser with some default flags and parses
    command_line_options.

    :return: The populated namespace from ArgumentParser.parse_args
    '''

    parser = argparse.ArgumentParser(description=f'{name} - {description}')
    parser.add_argument('-V', '--version', action='version', version=f'{name} {version}')
    parser.add_argument('-l', '--log_file', help='path to log file', default=None)
    parser.add_argument(
        '-L', '--log_level', help='define the log level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default=None
    )
    parser.add_argument('-C', '--config_file', help='set path to config File', default=None)
    parser.add_argument(
        '-t', '--testing', default=False, action='store_true', help='shutdown system after one iteration'
    )
    parser.add_argument('--no-radare', default=False, action='store_true', help='don\'t start radare server')
    return parser.parse_args(command_line_options[1:])


def get_logging_config(args, component):
    """
    Returns a tuple of (logfile, loglevel) read from args and the config file.
    Assumes that `config.load` was called beforehand.
    """
    if args.log_level:
        log_level = logging.getLevelName(args.log_level)
    else:
        log_level = logging.getLevelName(cfg.logging.loglevel)

    # TODO this check also belongs in src/config.py:_verify_config
    # See getLevelName implementation for why this check works
    if isinstance(log_level, str):
        raise Exception(f'Invalid log level: {cfg.logging.loglevel}')

    # I don't like this check but I currently can't find a better way to do this
    if component not in ['frontend', 'backend', 'database']:
        return f'/tmp/fact_{component}.log', log_level
    else:
        if args.log_file:
            log_file = args.log_file
        else:
            log_file = getattr(cfg.logging, f'logfile_{component}')

        # FIXME Ideally the config object should represent the config as given by main.cfg.
        #       Since there is no other way to expose this global state we save in the config.
        cfg.logging.loglevel = logging.getLevelName(log_level)
        setattr(cfg.logging, f'logfile_{component}', log_file)

        return log_file, log_level


def setup_logging(logfile, loglevel):
    log_format = dict(fmt='[%(asctime)s][%(module)s][%(levelname)s]: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    logger = logging.getLogger()
    # Pass all messages to handlers
    logger.setLevel(logging.NOTSET)

    create_dir_for_file(logfile)
    file_log = logging.FileHandler(logfile)
    file_log.setLevel(loglevel)
    file_log.setFormatter(logging.Formatter(**log_format))
    logger.addHandler(file_log)

    console_log = logging.StreamHandler()
    console_log.setLevel(loglevel)
    console_log.setFormatter(ColoringFormatter(**log_format))
    logger.addHandler(console_log)
