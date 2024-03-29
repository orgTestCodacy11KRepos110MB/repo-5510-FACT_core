from __future__ import annotations

from collections.abc import Sequence
from random import sample, seed

seed()


def avg(seq: Sequence[float]) -> float:
    '''
    Returns the average of seq.
    '''
    if len(seq) == 0:
        return 0
    return sum(seq) / len(seq)


def shuffled(sequence):
    '''
    Copies and shuffles an array.

    :param sequence: The array to be shuffled
    :return: A shuffled copy of `sequence`
    '''
    return sample(sequence, len(sequence))
